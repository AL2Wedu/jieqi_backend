from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_current_player, get_db
from app.core.errors import ok
from app.models import Player
from app.schemas import UseItemRequest
from app.services import inventory_service, player_service

router = APIRouter(prefix="/player", tags=["player"])


@router.get("/me")
def me(player: Player = Depends(get_current_player), db: Session = Depends(get_db)):
    return ok(player_service.get_me(db, player))


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
