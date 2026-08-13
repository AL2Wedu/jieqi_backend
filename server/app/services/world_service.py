"""每用户世界时钟:节气从全局单例改为玩家独立。

每个玩家维护自己的累计世界时间 world_accum(相对全局纪元的"世界秒"):
- 在线(最近一次心跳在阈值内):按全局 time_scale × 1.0 推进
- 离线:按全局 time_scale × offline_factor 推进(默认 0.25,`game_config.world.offline_factor` 可配)

植物生长始终走墙钟(farm_service.crop_view 直接用 datetime.now()),与此无关。
"""
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.utils import ensure_aware
from app.models import GameConfig, Player
from app.services.calendar_service import calendar_dict, global_elapsed, term_at

_DEFAULT_OFFLINE_FACTOR = 0.25
_DEFAULT_ONLINE_THRESHOLD = 300  # 秒

_KEYS = ("world.offline_factor", "world.online_threshold_sec")


def world_config(db: Session) -> dict:
    """离线倍速 / 在线判定阈值(game_config 可配,带默认值)。"""
    rows = {
        c.key: c.value
        for c in db.query(GameConfig).filter(GameConfig.key.in_(_KEYS)).all()
    }
    try:
        offline_factor = float(rows.get("world.offline_factor", _DEFAULT_OFFLINE_FACTOR))
    except (TypeError, ValueError):
        offline_factor = _DEFAULT_OFFLINE_FACTOR
    try:
        online_threshold = float(
            rows.get("world.online_threshold_sec", _DEFAULT_ONLINE_THRESHOLD)
        )
    except (TypeError, ValueError):
        online_threshold = _DEFAULT_ONLINE_THRESHOLD
    return {
        "offline_factor": max(0.0, min(1.0, offline_factor)),
        "online_threshold": max(1.0, online_threshold),
    }


def is_online(player: Player, now: datetime | None = None, threshold: float = _DEFAULT_ONLINE_THRESHOLD) -> bool:
    now = now or datetime.now(timezone.utc)
    if player.last_active_at is None:
        return False
    return (now - ensure_aware(player.last_active_at)).total_seconds() <= threshold


def _elapsed_since_last_sync(db: Session, player: Player, now: datetime) -> float:
    """自上次同步以来、受全局暂停钳制的真实秒数(>0)。"""
    from app.services.calendar_service import get_clock

    last_sync = ensure_aware(player.world_last_sync)
    if last_sync is None:
        return 0.0
    dt = (now - last_sync).total_seconds()
    if dt <= 0:
        return 0.0
    clock = get_clock(db)
    paused = ensure_aware(clock.paused_at) if clock.paused_at else None
    if paused is not None:
        # 全局暂停冻结:只累计到暂停时刻为止
        dt = max(0.0, min(dt, (paused - last_sync).total_seconds()))
    return dt


def sync_world(db: Session, player: Player, now: datetime | None = None) -> None:
    """同步并写回累计世界时间 + 在线心跳。玩家每次认证请求都会调用。"""
    cfg = world_config(db)
    now = now or datetime.now(timezone.utc)
    last_sync = ensure_aware(player.world_last_sync)
    if last_sync is None:
        # 首次:继承全局参考世界位置(老玩家零成本迁移)
        player.world_accum = global_elapsed(db, now)
    else:
        dt = _elapsed_since_last_sync(db, player, now)
        if dt > 0:
            online = is_online(player, now, cfg["online_threshold"])
            rate = _rate(db, 1.0 if online else cfg["offline_factor"])
            player.world_accum = float(player.world_accum or 0.0) + dt * rate
    player.world_last_sync = now
    player.last_active_at = now


def _rate(db: Session, factor: float) -> float:
    from app.services.calendar_service import get_clock

    return float(get_clock(db).time_scale) * factor


def current_term(db: Session, player: Player) -> tuple:
    """玩家当前节气三元组 (term, cycle, remaining_sec)。"""
    return term_at(db, float(player.world_accum or 0.0))


def current_calendar(db: Session, player: Player) -> dict:
    term, cycle, remaining = current_term(db, player)
    return calendar_dict(term, cycle, remaining)


def peek_term(db: Session, player: Player, now: datetime | None = None) -> tuple:
    """只读估算当前节气(不落库),供管理端列表用。"""
    now = now or datetime.now(timezone.utc)
    cfg = world_config(db)
    last_sync = ensure_aware(player.world_last_sync)
    if last_sync is None:
        accum = global_elapsed(db, now)
    else:
        dt = _elapsed_since_last_sync(db, player, now)
        online = is_online(player, now, cfg["online_threshold"])
        rate = _rate(db, 1.0 if online else cfg["offline_factor"])
        accum = float(player.world_accum or 0.0) + dt * rate
    return term_at(db, accum)


def set_world(
    db: Session, player: Player, accum: float | None = None, reset: bool = False
) -> dict:
    """管理端覆盖/重置玩家世界:reset → 回到纪元起点(立春);accum → 设定世界秒。"""
    if reset:
        player.world_accum = 0.0
    elif accum is not None:
        player.world_accum = max(0.0, float(accum))
    else:
        raise ValueError("must provide accum or reset")
    now = datetime.now(timezone.utc)
    player.world_last_sync = now
    player.last_active_at = now
    db.commit()
    return {"player_id": str(player.id), "accum": player.world_accum, **current_calendar(db, player)}
