import uuid

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import CropInstance, Item, ItemTransaction, Player, UserItem
from app.services import farm_service


def list_inventory(db: Session, player: Player) -> dict:
    rows = db.query(UserItem).filter(UserItem.player_id == player.id).all()
    item_ids = [r.item_id for r in rows]
    items = {i.id: i for i in db.query(Item).filter(Item.id.in_(item_ids)).all()} if item_ids else {}
    return {
        "items": [
            {
                "item_id": str(r.item_id),
                "code": items[r.item_id].code,
                "name": items[r.item_id].name,
                "category": items[r.item_id].category,
                "quantity": r.quantity,
                "effect": items[r.item_id].effect,
            }
            for r in rows
        ]
    }


def use_item(db: Session, player: Player, item_id: str, target) -> dict:
    try:
        item_uuid = uuid.UUID(item_id)
    except ValueError:
        raise AppError("ITEM_NOT_FOUND", "道具不存在", code=22002)
    ui = (
        db.query(UserItem)
        .filter(UserItem.player_id == player.id, UserItem.item_id == item_uuid)
        .first()
    )
    if not ui or ui.quantity < 1:
        raise AppError("NOT_ENOUGH_ITEM", "道具不足", code=22001)
    item = db.query(Item).filter(Item.id == item_uuid).first()
    eff = item.effect or {}
    etype = eff.get("type")

    if etype == "seed":
        raise AppError("EFFECT_NOT_SUPPORTED", "种子请通过播种接口使用", code=22004)

    if etype in ("water", "boost"):
        plot_id = target.plot_id if target else None
        if not plot_id:
            raise AppError("INVALID_PARAMS", "需要指定目标地块 target.plot_id", code=10001)
        ci = farm_service._get_active_crop(db, player, plot_id)
        if etype == "water":
            ci.water_level = 100
            applied = {"water_level": 100}
        else:
            pct = int(eff.get("growth_pct", 0))
            extra = dict(ci.extra or {})
            extra["boost_pct"] = extra.get("boost_pct", 0) + pct
            ci.extra = extra
            applied = {"growth_pct": pct, "total_boost_pct": extra["boost_pct"]}
        ui.quantity -= 1
        db.add(
            ItemTransaction(player_id=player.id, item_id=item.id, delta=-1, reason="use", ref_id=ci.id)
        )
        db.commit()
        return {"effect_applied": applied}

    if etype == "term_lock":
        raise AppError("EFFECT_NOT_SUPPORTED", "节气卡功能开发中", code=22004)

    raise AppError("EFFECT_NOT_SUPPORTED", "未知道具效果", code=22004)
