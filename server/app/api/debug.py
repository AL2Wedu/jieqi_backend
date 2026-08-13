"""调试接口(demo 专用):改配置 / 推进节气 / 催熟作物。上线由 DEBUG_ENABLED 关闭。"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import get_current_player, get_db
from app.core.errors import AppError, ok
from app.models import Crop, GameConfig, Player
from app.schemas import DebugConfigRequest, DebugGrowRequest
from app.services import calendar_service, farm_service

router = APIRouter(prefix="/debug", tags=["debug"])


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
    clock = calendar_service.get_clock(db)
    term, _, _ = calendar_service.get_current_term(db)
    # 把纪元往前拨一个节气的游戏时长,等效于推进一轮
    clock.epoch = clock.epoch - timedelta(
        seconds=term.duration_seconds / float(clock.time_scale)
    )
    db.commit()
    return ok(calendar_service.current_calendar(db))


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
