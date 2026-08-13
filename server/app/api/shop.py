from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_current_player, get_db
from app.core.errors import ok
from app.models import Player
from app.schemas import BuyRequest
from app.services import shop_service

router = APIRouter(prefix="/shop", tags=["shop"])


@router.get("/items")
def items(db: Session = Depends(get_db)):
    return ok(shop_service.list_shop(db))


@router.post("/items/{item_id}/buy")
def buy(
    item_id: str,
    req: BuyRequest,
    player: Player = Depends(get_current_player),
    db: Session = Depends(get_db),
):
    return ok(shop_service.buy(db, player, item_id, req.quantity))
