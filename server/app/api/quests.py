from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_current_player, get_db
from app.core.errors import ok
from app.models import Player
from app.services import quest_service

router = APIRouter(prefix="/quests", tags=["quests"])


@router.get("")
def quests(player: Player = Depends(get_current_player), db: Session = Depends(get_db)):
    """任务列表(自动跟踪,含实时进度)。"""
    return ok(quest_service.list_quests(db, player))


@router.post("/{quest_id}/claim")
def claim(
    quest_id: str,
    player: Player = Depends(get_current_player),
    db: Session = Depends(get_db),
):
    """领取任务奖励(任务完成自动判定)。"""
    return ok(quest_service.claim(db, player, quest_id))
