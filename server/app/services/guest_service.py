"""AI 客人议价出售:玩家与 LLM 扮演的客人讨价还价,成交按议定价结算。

- 会话域:ai_guest_sessions / ai_guest_messages(上下文持久化,无 Redis 依赖)
- AI 输出强约束 JSON,服务端权威校验(成交价 ∈ [floor, ceil] × 市场价,防作弊)
- 状态机:bargaining →(deal=true / 玩家 accept)→ done 结算
                   →(turns ≥ max_turns)→ closed 不成交
                   →(玩家 cancel)→ cancelled
- 成本控制:单活跃会话 / start 冷却 / max_turns / 历史截断 / 用量进 ai_usage
"""
import json
import random
import re
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.utils import ensure_aware
from app.models import (
    AiGuestMessage,
    AiGuestSession,
    Crop,
    CropStorage,
    GameConfig,
    Player,
)
from app.services import ai_service, shop_service

_KEYS = (
    "guest.enabled",
    "guest.cooldown_seconds",
    "guest.max_turns",
    "guest.price_floor",
    "guest.price_ceil",
    "guest.context_messages",
    "guest.json_retries",
)
_DEFAULTS = {
    "guest.enabled": True,
    "guest.cooldown_seconds": 30,
    "guest.max_turns": 8,
    "guest.price_floor": 0.5,
    "guest.price_ceil": 1.5,
    "guest.context_messages": 12,
    "guest.json_retries": 1,
}
_MOODS = ("plain", "happy", "sad", "confused")
_GUESTS_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "guests.json"


def guest_config(db: Session) -> dict:
    rows = {
        c.key: c.value
        for c in db.query(GameConfig).filter(GameConfig.key.in_(_KEYS)).all()
    }
    cfg = dict(_DEFAULTS)
    for k, v in rows.items():
        if v is not None:
            cfg[k] = v
    cfg["guest.cooldown_seconds"] = max(0, int(cfg["guest.cooldown_seconds"]))
    cfg["guest.max_turns"] = max(1, min(20, int(cfg["guest.max_turns"])))
    cfg["guest.price_floor"] = max(0.1, float(cfg["guest.price_floor"]))
    cfg["guest.price_ceil"] = max(cfg["guest.price_floor"], float(cfg["guest.price_ceil"]))
    cfg["guest.context_messages"] = max(2, int(cfg["guest.context_messages"]))
    cfg["guest.json_retries"] = max(0, min(3, int(cfg["guest.json_retries"])))
    return cfg


def save_guest_config(db: Session, data: dict) -> dict:
    for key in _KEYS:
        if key in data and data[key] is not None:
            row = db.query(GameConfig).filter(GameConfig.key == key).first()
            if row:
                row.value = data[key]
            else:
                db.add(GameConfig(key=key, value=data[key]))
    db.commit()
    return guest_config(db)


def load_guests() -> list[dict]:
    return json.loads(_GUESTS_PATH.read_text(encoding="utf-8"))


def _pick_guest() -> dict:
    """安全随机选客:密码学安全随机源(SystemRandom),防预测/防刷。"""
    guests = load_guests()
    return guests[random.SystemRandom().randrange(len(guests))]


def _guest_by_key(key: str) -> dict | None:
    for g in load_guests():
        if g["key"] == key:
            return g
    return None


def _avatar_url(g: dict) -> str:
    """客人头像 URL:guests.json 的 avatar 字段(animals 素材)→ /v1/assets/images/..."""
    return f"/v1/assets/images/{g['avatar']}?w=128"


def encounter_guest(db: Session, player: Player) -> dict:
    """遇到客人:返回随机客人(名称+头像),并锁定到该玩家。

    锁定语义:玩家已有 guest_encounter_key(上次遇到未完成买卖)→ 返回同一位;
    无锁定 → SystemRandom 安全随机一位并持久化锁定。会话结束(成交/关闭/赶客)
    时由 _finish 解锁,之后 encounter 才会重新随机。
    """
    if player.guest_encounter_key:
        g = _guest_by_key(player.guest_encounter_key)
        if g:
            return {
                "guest_key": g["key"],
                "guest_name": g["name"],
                "avatar_url": _avatar_url(g),
                "locked": True,
            }
        # 锁定 key 失效(guests.json 改版)→ 解锁重随机
        player.guest_encounter_key = None
    g = _pick_guest()
    player.guest_encounter_key = g["key"]
    db.commit()
    return {
        "guest_key": g["key"],
        "guest_name": g["name"],
        "avatar_url": _avatar_url(g),
        "locked": False,
    }


# ---------- 会话 ----------

def _get_session(db: Session, player: Player, session_id: str) -> AiGuestSession:
    try:
        import uuid

        sid = uuid.UUID(session_id)
    except ValueError:
        raise AppError("GUEST_NOT_FOUND", "会话不存在", code=29003)
    s = db.get(AiGuestSession, sid)
    if not s or s.player_id != player.id:
        raise AppError("GUEST_NOT_FOUND", "会话不存在或不属于你", code=29003)
    return s


def _check_bargaining(s: AiGuestSession) -> None:
    if s.status != "bargaining":
        raise AppError("GUEST_CLOSED", f"会话已结束({s.status})", code=29004)


def start_guest(db: Session, player: Player, crop_id: str) -> dict:
    """开启议价会话:冷却 / 单活跃会话 / 收成仓校验 / 市场价快照 / 随机客 / AI 开场白。"""
    cfg = guest_config(db)
    if not cfg["guest.enabled"]:
        raise AppError("GUEST_DISABLED", "AI 客人暂未开放", code=29006)
    # 冷却:最近一个已结束会话的 finished_at
    last = (
        db.query(AiGuestSession)
        .filter(
            AiGuestSession.player_id == player.id,
            AiGuestSession.finished_at.isnot(None),
        )
        .order_by(AiGuestSession.finished_at.desc())
        .first()
    )
    if last is not None:
        elapsed = (
            datetime.now(timezone.utc) - ensure_aware(last.finished_at)
        ).total_seconds()
        if elapsed < cfg["guest.cooldown_seconds"]:
            raise AppError(
                "GUEST_COOLDOWN",
                f"客人刚走,{int(cfg['guest.cooldown_seconds'] - elapsed)} 秒后再招呼",
                code=29002,
            )
    # 单活跃会话(事务内查,防并发)
    active = (
        db.query(AiGuestSession)
        .filter(AiGuestSession.player_id == player.id, AiGuestSession.status == "bargaining")
        .first()
    )
    if active:
        raise AppError("GUEST_BUSY", "已有客人正在谈,先谈完这单", code=29001)
    try:
        import uuid

        cid = uuid.UUID(crop_id)
    except ValueError:
        raise AppError("CROP_NOT_FOUND", "作物不存在", code=21005)
    crop = db.get(Crop, cid)
    if not crop:
        raise AppError("CROP_NOT_FOUND", "作物不存在", code=21005)
    row = (
        db.query(CropStorage)
        .filter(CropStorage.player_id == player.id, CropStorage.crop_id == cid)
        .first()
    )
    if not row or (row.quantity + row.wilted_quantity) < 1:
        raise AppError("NOT_ENOUGH_CROP", "收成仓没有可卖的收成", code=22007)
    # 市场价快照 + 枯萎折扣比例
    settings = shop_service.get_settings(db)
    season = shop_service.current_season(db, player)
    base = shop_service._crop_price(crop, settings, season)
    wilted = shop_service._wilted_price(crop, settings, season)
    # 客人:优先用 encounter 锁定的那位(遇到谁就是谁);无锁定则安全随机
    guest = _guest_by_key(player.guest_encounter_key) if player.guest_encounter_key else None
    if guest is None:
        guest = _pick_guest()
        player.guest_encounter_key = guest["key"]
    lo, hi = guest["offer_range"]
    target_min = max(1, round(base * lo))
    target_max = max(target_min, round(base * hi))
    s = AiGuestSession(
        player_id=player.id,
        crop_id=crop.id,
        guest_key=guest["key"],
        guest_name=guest["name"],
        base_price=base,
        wilted_ratio=(wilted / base) if base else 0.2,
        offer=0,
        target_min=target_min,
        target_max=target_max,
    )
    db.add(s)
    db.flush()
    # 开场白:直接给 AI 首条回复(算 1 轮),mood=plain
    opening = guest["opening"].replace("{菜}", crop.name)
    reply = _fallback_reply(s, opening, guest["name"], "plain", round((target_min + target_max) / 2))
    db.add(
        AiGuestMessage(
            session_id=s.id, role="guest", content=opening, reply=reply
        )
    )
    s.offer = reply["offer"]
    s.last_mood = "plain"
    s.turns = 1
    db.commit()
    return _snapshot(s)


# ---------- AI 调用管线 ----------

def _build_messages_impl(s: AiGuestSession, crop: Crop, history: list[dict], user_msg: str, retrying: bool, cfg: dict) -> list[dict]:
    system = (
        f"你是{s.guest_name},一位{_guest_personality(s)}的客人,来买玩家的{crop.name}。\n"
        f"市场参考价是 {s.base_price} 金币,你的心理价位是 {s.target_min}~{s.target_max} 金币。\n"
        "规则:\n"
        "1. 用自然口语讨价还价,每次回复必须同时给出你的报价 offer(金币整数)。\n"
        f"2. mood 只能取 {'/'.join(_MOODS)}:玩家报价高于你心理价→happy;低于→sad;重复纠缠→confused。\n"
        "3. deal 表示\"是否接受玩家当前报价成交\":接受→true(回复也要表达成交意愿);不接受→false(继续还价,可小幅让步)。\n"
        "4. 只输出一个 JSON 对象(不要 markdown 代码块,不要多余文字):\n"
        '{"reply_text": "...", "guest_name": "' + s.guest_name + '", "mood": "plain|happy|sad|confused", "offer": <整数>, "deal": true|false}\n'
    )
    if retrying:
        system += "5. 你上一次输出不是合法 JSON!必须只输出一个合法 JSON 对象。\n"
    messages = [{"role": "system", "content": system}]
    for m in history[-int(cfg["guest.context_messages"]):]:
        messages.append({"role": m["role"], "content": m["content"]})
    messages.append({"role": "user", "content": user_msg})
    return messages


def _guest_personality(s: AiGuestSession) -> str:
    for g in load_guests():
        if g["key"] == s.guest_key:
            return g["personality"]
    return "普通顾客"


def _parse_reply(raw: str) -> dict:
    """正则提取首个 JSON 对象。"""
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        raise ValueError("no json object")
    return json.loads(m.group(0))


def _validate_reply(data: dict, s: AiGuestSession, crop: Crop, cfg: dict) -> dict:
    """服务端权威校验:字段类型 / mood 枚举 / offer 区间(越界截断)。

    offer 上限额外夹到作物单株卖价上限(max_value):正常市场卖出被封顶,
    客人议价也不应突破,防超市场价套现。
    """
    reply_text = str(data.get("reply_text") or "").strip()
    if not reply_text:
        raise ValueError("reply_text empty")
    mood = str(data.get("mood") or "plain")
    if mood not in _MOODS:
        mood = "plain"
    offer = int(data.get("offer"))
    floor = max(1, round(s.base_price * cfg["guest.price_floor"]))
    ceil = max(floor, round(s.base_price * cfg["guest.price_ceil"]))
    # 不突破单株价值上限(与 shop_service._crop_price 的 max_value 封顶一致);
    # base_price 已是 max_value 封顶价,故 floor ≤ ceil ≤ maxv 通常成立,这里仍兜底
    maxv = int((crop.settings or {}).get("max_value", 0) or 0)
    if maxv > 0:
        ceil = min(ceil, maxv)
    offer = max(floor, offer)
    offer = min(offer, ceil)
    deal = bool(data.get("deal"))
    return {"reply_text": reply_text, "guest_name": s.guest_name, "mood": mood, "offer": offer, "deal": deal}


def _fallback_reply(s: AiGuestSession, text: str, name: str, mood: str, offer: int) -> dict:
    return {"reply_text": text, "guest_name": name, "mood": mood, "offer": offer, "deal": False}


async def _ask(db: Session, player: Player, s: AiGuestSession, crop: Crop, user_msg: str) -> dict:
    """调 AI → 解析 → 校验 → 重试 → 兜底(回复 JSON)。"""
    cfg = guest_config(db)
    history = [
        {"role": m.role, "content": m.content}
        for m in db.query(AiGuestMessage)
        .filter(AiGuestMessage.session_id == s.id)
        .order_by(AiGuestMessage.created_at)
        .all()
    ]
    retries = cfg["guest.json_retries"]
    for attempt in range(retries + 1):
        messages = _build_messages_impl(s, crop, history, user_msg, attempt > 0, cfg)
        try:
            raw = await ai_service.chat(
                db,
                player,
                {"model": None, "messages": messages, "temperature": 0.8, "max_tokens": 300},
            )
            text = raw["choices"][0]["message"]["content"]
            return _validate_reply(_parse_reply(text), s, crop, cfg)
        except AppError:
            # AI 未启用/未配置/上游异常 → 兜底话术(会话不坏,客人继续等)
            if attempt < retries:
                continue
            return _fallback_reply(
                s,
                "……我再想想,这个价先按我说的来,你意下如何?",
                s.guest_name,
                "plain",
                s.offer or round((s.target_min + s.target_max) / 2),
            )
        except (KeyError, ValueError, TypeError, IndexError):
            if attempt < retries:
                continue
            return _fallback_reply(
                s,
                "……我再想想,这个价先按我说的来,你意下如何?",
                s.guest_name,
                "plain",
                s.offer or round((s.target_min + s.target_max) / 2),
            )
    raise AppError("GUEST_AI_RESPONSE", "AI 客人回复异常", code=29005)


# ---------- chat / accept / cancel / snapshot ----------

async def chat_guest(db: Session, player: Player, session_id: str, message: str) -> dict:
    s = _get_session(db, player, session_id)
    _check_bargaining(s)
    message = (message or "").strip()
    if not message:
        raise AppError("INVALID_PARAMS", "消息不能为空", code=10001)
    crop = db.get(Crop, s.crop_id)
    db.add(AiGuestMessage(session_id=s.id, role="user", content=message))
    db.flush()
    reply = await _ask(db, player, s, crop, message)
    db.add(AiGuestMessage(session_id=s.id, role="guest", content=reply["reply_text"], reply=reply))
    s.offer = reply["offer"]
    s.last_mood = reply["mood"]
    s.turns += 1
    out = {**reply, "status": s.status}
    if reply["deal"]:
        # 原子终结:仅当仍 bargaining 才结算,防并发双重成交
        if _try_finish(db, s, "done"):
            _finish(db, player, s, "done")
            out["status"] = "done"
            out["settle"] = _settle_session(db, player, s, reply["offer"])
        else:
            out["status"] = "closed"
            out["closed_reason"] = "concurrent_settle"
    elif s.turns >= guest_config(db)["guest.max_turns"]:
        _finish(db, player, s, "closed")
        out["status"] = "closed"
        out["closed_reason"] = "max_turns"
    db.commit()
    return out


def accept_guest(db: Session, player: Player, session_id: str) -> dict:
    s = _get_session(db, player, session_id)
    _check_bargaining(s)
    if s.offer < 1:
        raise AppError("GUEST_NO_OFFER", "客人还没报价", code=29007)
    # 原子终结:仅当仍 bargaining 才结算,防并发 accept/chat 双重成交
    if not _try_finish(db, s, "done"):
        raise AppError("GUEST_CLOSED", "会话已结束,无法重复成交", code=29004)
    _finish(db, player, s, "done")
    settle = _settle_session(db, player, s, s.offer)
    db.commit()
    return {"status": "done", "offer": s.offer, "settle": settle}


def cancel_guest(db: Session, player: Player, session_id: str) -> dict:
    s = _get_session(db, player, session_id)
    _check_bargaining(s)
    _finish(db, player, s, "cancelled")
    db.commit()
    return {"status": "cancelled"}


def get_guest(db: Session, player: Player, session_id: str) -> dict:
    s = _get_session(db, player, session_id)
    snap = _snapshot(s)
    snap["history"] = [
        {"role": m.role, "content": m.content}
        for m in db.query(AiGuestMessage)
        .filter(AiGuestMessage.session_id == s.id)
        .order_by(AiGuestMessage.created_at)
        .all()
    ]
    return snap


# ---------- 内部 ----------

def _finish(db: Session, player: Player, s: AiGuestSession, status: str) -> None:
    s.status = status
    s.finished_at = datetime.now(timezone.utc)
    # 买卖结束 → 解锁客人:下次 encounter 重新随机
    if player.guest_encounter_key == s.guest_key:
        player.guest_encounter_key = None


def _try_finish(db: Session, s: AiGuestSession, status: str) -> bool:
    """原子终结会话:仅当仍为 bargaining 才置为指定终态。

    用条件更新防止并发 accept/chat 双重结算(TOCTOU):两个并发请求都读到
    status=bargaining 时,只有一个 UPDATE 命中(rowcount=1),另一个 rowcount=0
    → 返回 False,调用方应拒绝结算。
    """
    now = datetime.now(timezone.utc)
    rows = (
        db.query(AiGuestSession)
        .filter(AiGuestSession.id == s.id, AiGuestSession.status == "bargaining")
        .update(
            {
                AiGuestSession.status: status,
                AiGuestSession.finished_at: now,
            }
        )
    )
    return rows == 1


def _settle_session(db: Session, player: Player, s: AiGuestSession, unit_price: int) -> dict:
    crop = db.get(Crop, s.crop_id)
    wilted_unit = max(1, round(unit_price * s.wilted_ratio))
    return shop_service._settle_sale(
        db, player, crop, 1, unit_price, wilted_unit, f"guest_sell:{s.guest_key}"
    )


def _snapshot(s: AiGuestSession) -> dict:
    g = _guest_by_key(s.guest_key) or {}
    return {
        "session_id": str(s.id),
        "crop_id": str(s.crop_id),
        "guest_key": s.guest_key,
        "guest_name": s.guest_name,
        "avatar_url": _avatar_url(g) if g else "",
        "mood": s.last_mood,
        "offer": s.offer,
        "status": s.status,
        "turns": s.turns,
        "target_min": s.target_min,
        "target_max": s.target_max,
        "base_price": s.base_price,
        "finished_at": s.finished_at.isoformat() if s.finished_at else None,
    }
