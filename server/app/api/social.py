from fastapi import APIRouter, Body, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_current_player, get_db
from app.core.errors import ok
from app.models import Player
from app.schemas import FriendRequest
from app.services import social_service

router = APIRouter(prefix="/social", tags=["social"])


@router.get("/friends")
def friends(player: Player = Depends(get_current_player), db: Session = Depends(get_db)):
    return ok(social_service.list_friends(db, player))


@router.get("/requests")
def requests(player: Player = Depends(get_current_player), db: Session = Depends(get_db)):
    """收到的待处理好友申请。"""
    return ok(social_service.list_requests(db, player))


@router.post("/requests")
def send(
    req: FriendRequest = Body(...),
    player: Player = Depends(get_current_player),
    db: Session = Depends(get_db),
):
    """发送好友申请(对方 player_id)。"""
    return ok(social_service.send_request(db, player, req.player_id))


@router.post("/requests/{player_id}/accept")
def accept(
    player_id: str,
    player: Player = Depends(get_current_player),
    db: Session = Depends(get_db),
):
    return ok(social_service.respond(db, player, player_id, accept=True))


@router.post("/requests/{player_id}/reject")
def reject(
    player_id: str,
    player: Player = Depends(get_current_player),
    db: Session = Depends(get_db),
):
    return ok(social_service.respond(db, player, player_id, accept=False))


@router.delete("/friends/{player_id}")
def remove(
    player_id: str,
    player: Player = Depends(get_current_player),
    db: Session = Depends(get_db),
):
    return ok(social_service.remove_friend(db, player, player_id))
