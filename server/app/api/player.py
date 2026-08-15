from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_current_player, get_db
from app.core.errors import ok
from app.models import Player
from app.schemas import RenameRequest, UseItemRequest
from app.services import inventory_service, player_service

router = APIRouter(prefix="/player", tags=["player"])


@router.get("/me")
def me(player: Player = Depends(get_current_player), db: Session = Depends(get_db)):
    return ok(player_service.get_me(db, player))


@router.get("/uid/{uid_num}")
def by_uid(
    uid_num: int,
    player: Player = Depends(get_current_player),
    db: Session = Depends(get_db),
):
    """按对外纯数字 ID 查询任意玩家公开资料(与 /v1/social/players/{id} 同构)。"""
    return ok(player_service.get_by_uid(db, player, uid_num))


@router.post("/rename")
def rename(
    req: RenameRequest,
    player: Player = Depends(get_current_player),
    db: Session = Depends(get_db),
):
    """玩家改名:1-16 字符,限速 rename.cooldown_seconds(默认 7 天,后台可调)。"""
    return ok(player_service.rename_player(db, player, req.new_name))


@router.post("/tutorial/complete")
def complete_tutorial(
    player: Player = Depends(get_current_player),
    db: Session = Depends(get_db),
):
    """结束新手教学:恢复正常世界时钟与虫害调度(教学期间世界恒为立春、无虫害)。"""
    return ok(player_service.complete_tutorial(db, player))


@router.get("/inventory")
def inventory(player: Player = Depends(get_current_player), db: Session = Depends(get_db)):
    return ok(inventory_service.list_inventory(db, player))


@router.post("/inventory/{item_id}/use")
def use_item(
    item_id: str,
    req: UseItemRequest,
    player: Player = Depends(get_current_player),
    db: Session = Depends(get_db),
):
    return ok(inventory_service.use_item(db, player, item_id, req.target))
