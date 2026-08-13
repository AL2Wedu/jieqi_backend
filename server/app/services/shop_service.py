import uuid

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import CoinTransaction, Item, ItemTransaction, Player, UserItem


def _item_view(item: Item) -> dict:
    return {
        "item_id": str(item.id),
        "code": item.code,
        "name": item.name,
        "category": item.category,
        "buy_price": item.buy_price,
        "sell_price": item.sell_price,
        "unlock_level": item.unlock_level,
        "effect": item.effect,
    }


def list_shop(db: Session) -> dict:
    items = (
        db.query(Item)
        .filter(Item.active.is_(True), Item.buy_price.isnot(None))
        .order_by(Item.sort_order)
        .all()
    )
    return {"items": [_item_view(i) for i in items]}


def buy(db: Session, player: Player, item_id: str, quantity: int) -> dict:
    try:
        item_uuid = uuid.UUID(item_id)
    except ValueError:
        raise AppError("ITEM_NOT_FOUND", "商品不存在", code=22002)
    item = (
        db.query(Item)
        .filter(Item.id == item_uuid, Item.active.is_(True), Item.buy_price.isnot(None))
        .first()
    )
    if not item:
        raise AppError("ITEM_NOT_FOUND", "商品不存在", code=22002)
    cost = item.buy_price * quantity
    if player.coins < cost:
        raise AppError("NOT_ENOUGH_COINS", "钱财不足", code=22003)
    player.coins -= cost
    ui = (
        db.query(UserItem)
        .filter(UserItem.player_id == player.id, UserItem.item_id == item.id)
        .first()
    )
    if ui:
        ui.quantity += quantity
    else:
        db.add(UserItem(player_id=player.id, item_id=item.id, quantity=quantity))
    db.add(CoinTransaction(player_id=player.id, amount=-cost, reason="buy", ref_id=item.id))
    db.add(ItemTransaction(player_id=player.id, item_id=item.id, delta=quantity, reason="buy", ref_id=item.id))
    db.commit()
    return {
        "item_id": str(item.id),
        "code": item.code,
        "quantity": quantity,
        "cost": cost,
        "coins_balance": player.coins,
    }
