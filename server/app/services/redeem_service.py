"""兑换码服务:仅管理后台可发布/管理;玩家兑换走哈希匹配 + 原子抢占 + 限速。

安全设计:
- 码值只存 SHA-256 哈希(DB 泄露不暴露明文),列表仅回前 6 位提示(hint)
- 创建响应只回一次明文;批量生成不允许指定码值
- 无效/停用/过期统一报 20010 REDEEM_INVALID(不泄露码是否存在,防枚举)
- 次数抢占 = 条件 UPDATE(used_count < max_uses),rowcount!=1 即并发抢空 → 20012
- 每人限领由 redeem_claims 计数 + UNIQUE(player, code) 双重保证
- 尝试限速(redeem.cooldown_seconds,成功失败都算,防爆破)
- 奖励发放复用 grant_reward(金币/经验/道具全走账本)
"""
import hashlib
import secrets
import string
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.utils import ensure_aware
from app.models import GameConfig, Player, RedeemClaim, RedeemCode
from app.services.goal_service import grant_reward

_REDEEM_KEYS = ("redeem.cooldown_seconds",)
_REDEEM_DEFAULTS = {"redeem.cooldown_seconds": 60}


def _config(db: Session) -> dict:
    rows = {
        c.key: c.value
        for c in db.query(GameConfig).filter(GameConfig.key.in_(_REDEEM_KEYS)).all()
    }
    cfg = dict(_REDEEM_DEFAULTS)
    cfg.update({k: v for k, v in rows.items() if v is not None})
    cfg["redeem.cooldown_seconds"] = max(0, int(cfg["redeem.cooldown_seconds"]))
    return cfg


def _hash_code(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def _validate_code(code: str) -> None:
    if not code or not (6 <= len(code) <= 24) or not code.isalnum():
        raise AppError("INVALID_PARAMS", "兑换码格式不正确", code=10001)


def _gen_code() -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(12))


def _normalize_reward(reward: dict) -> dict:
    """奖励校验:coins/exp 非负 int;items 为 [{code, quantity>0}]。"""
    reward = reward or {}
    coins = max(0, int(reward.get("coins", 0) or 0))
    exp = max(0, int(reward.get("exp", 0) or 0))
    items = []
    for it in (reward.get("items") or []):
        code = str(it.get("code") or "").strip()
        qty = max(1, int(it.get("quantity", 1) or 1))
        if not code:
            raise AppError("INVALID_PARAMS", "道具奖励需提供 code", code=10001)
        items.append({"code": code, "quantity": qty})
    if not (coins or exp or items):
        raise AppError("INVALID_PARAMS", "奖励不能为空(coins/exp/items 至少一项)", code=10001)
    return {"coins": coins, "exp": exp, "items": items}


def _parse_expires(raw: str | None) -> datetime | None:
    if raw is None:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        raise AppError("INVALID_PARAMS", "expires_at 格式不正确(ISO8601)", code=10001)


# ---------- 管理端(admin JWT) ----------


def create_code(db: Session, admin_id, payload: dict) -> dict:
    """发布兑换码:单个(可指定码值)或批量 count 个(随机码)。

    明文只在创建响应返回一次;库中只存 sha256 + 前 6 位 hint。
    """
    reward = _normalize_reward(payload.get("reward"))
    count = max(1, min(int(payload.get("count", 1) or 1), 100))
    max_uses = max(0, int(payload.get("max_uses", 1) or 1))
    per_player_limit = max(1, int(payload.get("per_player_limit", 1) or 1))
    expires_at = _parse_expires(payload.get("expires_at"))
    batch = (payload.get("batch_name") or "").strip()[:64]
    custom = (payload.get("code") or "").strip().upper()
    if custom and count > 1:
        raise AppError("INVALID_PARAMS", "批量生成不能指定码值", code=10001)
    issued = []
    for _ in range(count):
        code = custom or _gen_code()
        _validate_code(code)
        if db.query(RedeemCode.id).filter(RedeemCode.code_hash == _hash_code(code)).first():
            raise AppError("REDEEM_CODE_EXISTS", "兑换码已存在", code=20015)
        db.add(
            RedeemCode(
                code_hash=_hash_code(code),
                code_hint=code[:6],
                reward=reward,
                batch_name=batch,
                max_uses=max_uses,
                per_player_limit=per_player_limit,
                expires_at=expires_at,
                active=1,
                created_by=admin_id,
            )
        )
        issued.append(code)
    db.commit()
    return {
        "count": count,
        "codes": issued,  # 明文仅此一次
        "batch_name": batch,
        "max_uses": max_uses,
        "per_player_limit": per_player_limit,
        "expires_at": expires_at.isoformat() if expires_at else None,
    }


def list_codes(db: Session, limit: int = 20, offset: int = 0) -> dict:
    """兑换码列表(运营视图):只回前 6 位 hint,不回哈希/明文。"""
    total = db.query(RedeemCode.id).count()
    rows = (
        db.query(RedeemCode)
        .order_by(RedeemCode.created_at.desc())
        .limit(max(1, min(int(limit), 50)))
        .offset(max(0, int(offset)))
        .all()
    )
    return {
        "total": total,
        "items": [
            {
                "code_id": str(r.id),
                "code_hint": r.code_hint,  # 明文前 6 位(识别用)
                "batch_name": r.batch_name,
                "reward": r.reward,
                "max_uses": r.max_uses,
                "used_count": r.used_count,
                "remaining": None if r.max_uses == 0 else r.max_uses - r.used_count,
                "per_player_limit": r.per_player_limit,
                "expires_at": r.expires_at.isoformat(timespec="seconds") if r.expires_at else None,
                "active": r.active == 1,
                "created_at": r.created_at.isoformat(timespec="seconds"),
            }
            for r in rows
        ],
    }


def update_code(db: Session, admin_id, code_id: str, payload: dict) -> dict:
    """更新兑换码:停用/启用、次数上限、过期时间(软管理,不删除)。"""
    try:
        rc = db.query(RedeemCode).filter(RedeemCode.id == uuid.UUID(str(code_id))).first()
    except (ValueError, TypeError):
        rc = None
    if not rc:
        raise AppError("REDEEM_NOT_FOUND", "兑换码不存在", code=20016)
    if payload.get("active") is not None:
        rc.active = 1 if payload["active"] else 0
    if payload.get("max_uses") is not None:
        rc.max_uses = max(0, int(payload["max_uses"]))
    if payload.get("per_player_limit") is not None:
        rc.per_player_limit = max(1, int(payload["per_player_limit"]))
    if "expires_at" in payload:
        rc.expires_at = _parse_expires(payload.get("expires_at"))
    db.commit()
    return {"code_id": str(rc.id), "active": rc.active == 1, "max_uses": rc.max_uses,
            "per_player_limit": rc.per_player_limit,
            "expires_at": rc.expires_at.isoformat(timespec="seconds") if rc.expires_at else None}


# ---------- 玩家端 ----------


def redeem(db: Session, player: Player, code: str) -> dict:
    """兑换码兑换:限速 → 哈希查码 → 原子抢占次数 → 每人限领 → 发奖励(账本)。"""
    code = (code or "").strip().upper()
    _validate_code(code)
    now = datetime.now(timezone.utc)
    cfg = _config(db)
    cd = cfg["redeem.cooldown_seconds"]
    # 限速(成功失败都算;窗口从首次尝试起算,不因重复尝试延长)
    last = ensure_aware(player.redeem_last_attempt_at)
    if last is not None and cd > 0:
        remaining = int((last + timedelta(seconds=cd) - now).total_seconds())
        if remaining > 0:
            raise AppError(
                "REDEEM_RATE_LIMITED", f"兑换过于频繁,请 {remaining} 秒后再试", code=20009
            )
    player.redeem_last_attempt_at = now
    # 哈希查码;无效/停用/过期统一报错(防枚举)
    rc = db.query(RedeemCode).filter(RedeemCode.code_hash == _hash_code(code)).first()
    if not rc or rc.active != 1 or (rc.expires_at and ensure_aware(rc.expires_at) < now):
        db.commit()
        raise AppError("REDEEM_INVALID", "无效的兑换码", code=20010)
    # 每人限领(先查后抢,防并发下回滚次数互相踩踏)
    cnt = (
        db.query(RedeemClaim.id)
        .filter(
            RedeemClaim.player_id == player.id,
            RedeemClaim.redeem_code_id == rc.id,
        )
        .count()
    )
    if cnt >= rc.per_player_limit:
        db.commit()
        raise AppError("REDEEM_CLAIMED", "该兑换码已兑换过", code=20011)
    # 原子抢占次数:仅当 未停用 且 (不限次数 或 未用满) 才 +1;并发只命中一次
    claimed = (
        db.query(RedeemCode)
        .filter(
            RedeemCode.id == rc.id,
            RedeemCode.active == 1,
            or_(RedeemCode.max_uses == 0, RedeemCode.used_count < RedeemCode.max_uses),
        )
        .update({RedeemCode.used_count: RedeemCode.used_count + 1})
    )
    if claimed != 1:
        db.commit()
        raise AppError("REDEEM_EXHAUSTED", "兑换码已用完", code=20012)
    # 发奖励(走账本)+ 记领取
    result = grant_reward(db, player, rc.reward, reason=f"redeem:{rc.batch_name or code[:8]}")
    db.add(RedeemClaim(player_id=player.id, redeem_code_id=rc.id, claimed_at=now))
    db.commit()
    return {"claimed": True, "batch_name": rc.batch_name, "reward": result}
