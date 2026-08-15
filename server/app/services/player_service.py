"""玩家服务:档案 / 改名(限速) / 数字 ID 查询。"""
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.utils import ensure_aware
from app.models import Farm, GameConfig, Player, User
from app.services.auth_service import player_summary

# 改名限速配置:game_config 可后台热调(默认 7 天)
_RENAME_KEYS = ("rename.cooldown_seconds",)
_RENAME_DEFAULTS = {"rename.cooldown_seconds": 604800}


def _rename_config(db: Session) -> dict:
    rows = {
        c.key: c.value
        for c in db.query(GameConfig).filter(GameConfig.key.in_(_RENAME_KEYS)).all()
    }
    cfg = dict(_RENAME_DEFAULTS)
    cfg.update({k: v for k, v in rows.items() if v is not None})
    cfg["rename.cooldown_seconds"] = max(0, int(cfg["rename.cooldown_seconds"]))
    return cfg


def get_me(db: Session, player: Player) -> dict:
    user = db.query(User).filter(User.id == player.user_id).first()
    farm = db.query(Farm).filter(Farm.owner_id == player.id).first()
    return player_summary(player, farm, user)


def rename_player(db: Session, player: Player, new_name: str) -> dict:
    """玩家改名:限速(rename.cooldown_seconds,默认 7 天)+ 同步 User.name / Player.name。

    安全:服务端限速(非客户端);重名合法(已放开);改后登录名随之变化。
    """
    new_name = (new_name or "").strip()
    if not new_name or len(new_name) > 16:
        raise AppError("INVALID_PARAMS", "名字需 1-16 个字符", code=10001)
    user = db.query(User).filter(User.id == player.user_id).first()
    if user is None:
        raise AppError("USER_NOT_FOUND", "用户不存在", code=20002)
    if user.name == new_name:
        raise AppError("INVALID_PARAMS", "新名字与当前名字相同", code=10001)
    cfg = _rename_config(db)
    cd = cfg["rename.cooldown_seconds"]
    now = datetime.now(timezone.utc)
    last = ensure_aware(player.rename_last_at)
    if last is not None and cd > 0:
        remaining = int((last + timedelta(seconds=cd) - now).total_seconds())
        if remaining > 0:
            raise AppError(
                "RENAME_TOO_FREQUENT",
                f"改名过于频繁,请 {remaining} 秒后再试",
                code=20008,
            )
    user.name = new_name
    player.name = new_name
    player.rename_last_at = now
    db.commit()
    return {
        "name": new_name,
        "rename_last_at": now.isoformat(timespec="seconds"),
        "next_rename_at": (now + timedelta(seconds=cd)).isoformat(timespec="seconds"),
    }


def get_by_uid(db: Session, player: Player, uid_num: int) -> dict:
    """按对外纯数字 ID 查询任意玩家公开资料(与 /v1/social/players/{id} 同构)。"""
    user = db.query(User).filter(User.uid_num == int(uid_num)).first()
    if not user:
        raise AppError("UID_NOT_FOUND", "数字 ID 不存在", code=20013)
    target = db.query(Player).filter(Player.user_id == user.id).first()
    if not target:
        raise AppError("UID_NOT_FOUND", "数字 ID 不存在", code=20013)
    from app.services.social_service import _profile_view, _relation

    view = _profile_view(db, target)
    view["relation"] = _relation(db, player, target.id)
    return view
