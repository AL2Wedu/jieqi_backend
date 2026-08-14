from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_current_player, get_db
from app.core.errors import ok
from app.models import Player
from app.schemas import SowRequest
from app.services import farm_service, weed_service

router = APIRouter(prefix="/farm", tags=["farm"])


@router.get("/state")
def state(player: Player = Depends(get_current_player), db: Session = Depends(get_db)):
    return ok(farm_service.get_farm_state(db, player))


@router.post("/plots/{plot_id}/sow")
def sow(
    plot_id: str,
    req: SowRequest,
    player: Player = Depends(get_current_player),
    db: Session = Depends(get_db),
):
    return ok(farm_service.sow(db, player, plot_id, req.crop_id))


@router.post("/plots/{plot_id}/water")
def water(
    plot_id: str,
    player: Player = Depends(get_current_player),
    db: Session = Depends(get_db),
):
    return ok(farm_service.water(db, player, plot_id))


@router.post("/plots/{plot_id}/harvest")
def harvest(
    plot_id: str,
    player: Player = Depends(get_current_player),
    db: Session = Depends(get_db),
):
    return ok(farm_service.harvest(db, player, plot_id))


@router.post("/plots/{plot_id}/clear")
def clear(
    plot_id: str,
    player: Player = Depends(get_current_player),
    db: Session = Depends(get_db),
):
    return ok(farm_service.clear(db, player, plot_id))


@router.post("/plots/{plot_id}/weed-clear")
def weed_clear(
    plot_id: str,
    player: Player = Depends(get_current_player),
    db: Session = Depends(get_db),
):
    """清除单个地块的杂草(只清所选格;原本无杂草幂等返回 cleared=False)。"""
    return ok(weed_service.clear_weed(db, player, plot_id))
