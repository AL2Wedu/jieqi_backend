"""调试接口(demo 专用):改配置 / 推进节气 / 催熟作物。上线由 DEBUG_ENABLED 关闭。

安全:
- debug_enabled 默认 False(需显式 DEBUG_ENABLED=true 开启,上线必须保持关闭)
- `/debug/config` 禁止写 ai.* / admin.* / jwt.* 敏感键(只能走管理后台)
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import get_current_player, get_db
from app.core.errors import AppError, ok
from app.models import Crop, GameConfig, Player
from app.schemas import DebugConfigRequest, DebugGrowRequest, PestTriggerRequest
from app.services import farm_service, pest_service, world_service

router = APIRouter(prefix="/debug", tags=["debug"])

# 敏感配置键:禁止经 /debug/config 修改(只能走管理后台)
_SENSITIVE_KEYS = ("ai.", "admin.", "jwt.")


def _guard() -> None:
    if not settings.debug_enabled:
        raise AppError("DEBUG_DISABLED", "调试接口已关闭", http_status=403, code=90001)


@router.post("/config")
def set_config(
    req: DebugConfigRequest,
    player: Player = Depends(get_current_player),
    db: Session = Depends(get_db),
):
    _guard()
    if any(req.key.startswith(prefix) for prefix in _SENSITIVE_KEYS):
        raise AppError(
            "INVALID_PARAMS", "该配置键为敏感项,请通过管理后台修改", code=10001
        )
    cfg = db.query(GameConfig).filter(GameConfig.key == req.key).first()
    if cfg:
        cfg.value = req.value
    else:
        db.add(GameConfig(key=req.key, value=req.value))
    db.commit()
    return ok({"key": req.key, "value": req.value})


@router.post("/term/advance")
def advance_term(
    player: Player = Depends(get_current_player),
    db: Session = Depends(get_db),
):
    _guard()
    term, _, _ = world_service.current_term(db, player)
    # 只推进调用者玩家的世界(向前一个节气时长),其他玩家互不影响
    player.world_accum = float(player.world_accum or 0.0) + term.duration_seconds
    now = datetime.now(timezone.utc)
    player.world_last_sync = now
    player.last_active_at = now
    db.commit()
    return ok(world_service.current_calendar(db, player))


@router.post("/grow")
def grow(
    req: DebugGrowRequest,
    player: Player = Depends(get_current_player),
    db: Session = Depends(get_db),
):
    _guard()
    ci = farm_service._get_active_crop(db, player, req.plot_id)
    crop = db.query(Crop).filter(Crop.id == ci.crop_id).first()
    ci.sowed_at = datetime.now(timezone.utc) - timedelta(seconds=crop.grow_seconds)
    db.commit()
    return ok({"plot_id": req.plot_id, "mature": True})


@router.post("/pest/trigger")
def pest_trigger(
    req: PestTriggerRequest,
    player: Player = Depends(get_current_player),
    db: Session = Depends(get_db),
):
    """调试:立刻给当前玩家触发一次虫害(big / small)。"""
    _guard()
    event = pest_service.fire_pest(db, player, forced_type=req.type)
    return ok(event)


@router.post("/pest/clear")
def pest_clear(
    player: Player = Depends(get_current_player),
    db: Session = Depends(get_db),
):
    """调试:清除当前玩家所有进行中的虫害(含寄生目标)。"""
    _guard()
    from app.models import PestEvent, PestTarget

    n_ev = (
        db.query(PestEvent)
        .filter(PestEvent.player_id == player.id, PestEvent.status == 0)
        .update({PestEvent.status: 1})
    )
    n_tg = (
        db.query(PestTarget)
        .filter(PestTarget.player_id == player.id, PestTarget.status == 0)
        .update({PestTarget.status: 1})
    )
    db.commit()
    return ok({"events": n_ev, "targets": n_tg})


@router.post("/weed/trigger")
def weed_trigger(
    player: Player = Depends(get_current_player),
    db: Session = Depends(get_db),
):
    """调试:立刻给当前玩家触发一次杂草生长(随机地块附杂草)。"""
    _guard()
    from app.services import weed_service

    targets = weed_service.fire_weed(db, player)
    db.commit()
    return ok({"type": "weed_growth", "targets": targets})


@router.post("/weed/clear")
def weed_clear(
    player: Player = Depends(get_current_player),
    db: Session = Depends(get_db),
):
    """调试:清除当前玩家所有地块的杂草。"""
    _guard()
    from app.services import weed_service

    return ok(weed_service.clear_weeds(db, player))
