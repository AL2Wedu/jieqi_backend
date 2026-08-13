"""商店路由:每用户独立商店(隔离/售空/补货)+ 收成仓出售(季节涨降)。"""
from fastapi import APIRouter, Body, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_current_player, get_db
from app.core.errors import ok
from app.models import Player
from app.schemas import BuyRequest, SellCropRequest
from app.services import shop_service

router = APIRouter(prefix="/shop", tags=["shop"])


@router.get("/state")
def state(player: Player = Depends(get_current_player), db: Session = Depends(get_db)):
    """我的商店:商品(库存/售价)+ 农作物收购价(随季节涨降)。"""
    return ok(shop_service.shop_state(db, player))


@router.get("/items")
def items(player: Player = Depends(get_current_player), db: Session = Depends(get_db)):
    """商品列表(兼容旧接口,返回 items 部分)。"""
    return ok({"items": shop_service.shop_state(db, player)["items"]})


@router.post("/items/{item_id}/buy")
def buy(
    item_id: str,
    req: BuyRequest = Body(...),
    player: Player = Depends(get_current_player),
    db: Session = Depends(get_db),
):
    """购买商品(库存扣减,售空拒绝)。"""
    return ok(shop_service.buy(db, player, item_id, req.quantity))


@router.get("/storage")
def storage(player: Player = Depends(get_current_player), db: Session = Depends(get_db)):
    """收成仓(收获入仓,含当前收购价)。"""
    return ok(shop_service.storage(db, player))


@router.post("/crops/{crop_id}/sell")
def sell_crop(
    crop_id: str,
    req: SellCropRequest = Body(...),
    player: Player = Depends(get_current_player),
    db: Session = Depends(get_db),
):
    """出售收成仓农作物(按当前季节/分类收购价结算)。"""
    return ok(shop_service.sell_crop(db, player, crop_id, req.quantity))
