from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_current_player, get_db
from app.core.errors import ok
from app.models import Player
from app.services import achievement_service

router = APIRouter(prefix="/achievements", tags=["achievements"])


@router.get("")
def achievements(
    player: Player = Depends(get_current_player), db: Session = Depends(get_db)
):
    """成就列表(自动重算进度,达成即置 completed)。"""
    return ok(achievement_service.list_achievements(db, player))


@router.post("/{achievement_id}/claim")
def claim(
    achievement_id: str,
    player: Player = Depends(get_current_player),
    db: Session = Depends(get_db),
):
    """领取成就奖励。"""
    return ok(achievement_service.claim(db, player, achievement_id))
