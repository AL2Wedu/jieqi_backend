from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_current_player, get_db
from app.core.errors import ok
from app.models import Player
from app.services import world_service

router = APIRouter(prefix="/calendar", tags=["calendar"])


@router.get("/current")
def current(player: Player = Depends(get_current_player), db: Session = Depends(get_db)):
    """当前节气(每用户独立世界:在线 1× / 离线 offline_factor)。"""
    return ok(world_service.current_calendar(db, player))
