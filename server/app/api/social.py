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


@router.get("/search")
def search(
    q: str,
    limit: int = 20,
    player: Player = Depends(get_current_player),
    db: Session = Depends(get_db),
):
    """按名字模糊搜索玩家(排除自己),公开资料列表。"""
    return ok(social_service.search_players(db, player, q, limit))


@router.get("/players/{player_id}")
def player_profile(
    player_id: str,
    player: Player = Depends(get_current_player),
    db: Session = Depends(get_db),
):
    """UUID 查询:任意玩家公开资料 + 与我方关系(none/pending_out/pending_in/friends)。"""
    return ok(social_service.get_player_profile(db, player, player_id))


@router.get("/friends/{player_id}")
def friend_profile(
    player_id: str,
    player: Player = Depends(get_current_player),
    db: Session = Depends(get_db),
):
    """好友资料卡(须已是好友):公开资料 + friends_since。"""
    return ok(social_service.get_friend_profile(db, player, player_id))


@router.get("/friends/{player_id}/farm")
def friend_farm(
    player_id: str,
    player: Player = Depends(get_current_player),
    db: Session = Depends(get_db),
):
    """好友农场参观(只读快照,无副作用)。"""
    return ok(social_service.get_friend_farm(db, player, player_id))


@router.post("/friends/{player_id}/water")
def water_friend(
    player_id: str,
    player: Player = Depends(get_current_player),
    db: Session = Depends(get_db),
):
    """互助浇水(预留接口,功能开发中)。"""
    return ok(social_service.water_friend(db, player, player_id))


@router.post("/friends/{player_id}/plots/{plot_idx}/steal")
def steal_crop(
    player_id: str,
    plot_idx: int,
    player: Player = Depends(get_current_player),
    db: Session = Depends(get_db),
):
    """偷菜(预留接口,功能开发中)。"""
    return ok(social_service.steal_from_friend(db, player, player_id, plot_idx))
