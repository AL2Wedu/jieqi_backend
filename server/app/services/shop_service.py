"""商店系统:每用户独立商店(库存隔离/可售空/周期补货)+ 季节涨降收购 + 收成仓出售。

- 隔离:每个玩家一个 UserShop 实例 + UserShopItem 行,互不影响
- 补货:restocked_at + restock_seconds 到点后全量重置库存为默认值(读取时惰性补货)
- 定价公式(管理端全可调):
    道具/种子售价 = item.buy_price × item_factor
    作物收购价  = crop.base_price × sell_factor × season_effect[当前季节] × category_factor[分类]
  UserShopItem.buy_price / sell_price 非空 = 管理端逐用户覆盖,优先于公式
- 收成仓:harvest 入仓,玩家择机出售(吃季节涨降)
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.utils import ensure_aware
from app.models import (
    CoinTransaction,
    Crop,
    CropStorage,
    Item,
    ItemTransaction,
    Player,
    ShopSettings,
    UserItem,
    UserShop,
    UserShopItem,
)
from app.services import world_service

SEASONS = {"spring": (1, 6), "summer": (7, 12), "autumn": (13, 18), "winter": (19, 24)}
SEASON_NAMES = {"spring": "春", "summer": "夏", "autumn": "秋", "winter": "冬"}

_WILTED_SELL_FACTOR = 0.3  # 枯萎劣质收成收购价系数(售价大打折扣)


def _utcnow():
    return datetime.now(timezone.utc)


def get_settings(db: Session) -> ShopSettings:
    s = db.get(ShopSettings, 1)
    if not s:
        s = ShopSettings(id=1)
        db.add(s)
        db.commit()
        db.refresh(s)
    return s


def current_season(db: Session, player: Player) -> str:
    """季节涨降跟随玩家自己的世界节气(每用户独立)。"""
    term = world_service.current_calendar(db, player)["term_index"]
    for name, (a, b) in SEASONS.items():
        if a <= term <= b:
            return name
    return "spring"


def _item_price(item: Item, settings: ShopSettings, row: UserShopItem | None) -> int:
    if row and row.buy_price is not None:
        return row.buy_price
    base = item.buy_price or 1
    return max(1, round(base * settings.item_factor))


def _crop_price(crop: Crop, settings: ShopSettings, season: str) -> int:
    se = settings.season_effect or {}
    ce = settings.category_factor or {}
    price = max(
        1,
        round(
            crop.base_price
            * settings.sell_factor
            * se.get(season, 1.0)
            * ce.get(crop.category, 1.0)
        ),
    )
    # 单株价值上限:作物设定 settings.max_value(0 = 不封顶)
    maxv = int((crop.settings or {}).get("max_value", 0) or 0)
    if maxv > 0:
        price = min(price, maxv)
    return price


def _wilted_price(crop: Crop, settings: ShopSettings, season: str) -> int:
    """枯萎劣质收成单株收购价 = 正常价 × 折扣系数(至少 1)。"""
    return max(1, int(round(_crop_price(crop, settings, season) * _WILTED_SELL_FACTOR)))


def ensure_shop(db: Session, player: Player) -> UserShop:
    shop = db.query(UserShop).filter(UserShop.player_id == player.id).first()
    if shop:
        return shop
    settings = get_settings(db)
    shop = UserShop(player_id=player.id)
    db.add(shop)
    db.flush()
    for item in db.query(Item).filter(Item.active.is_(True)).all():
        db.add(
            UserShopItem(
                player_id=player.id, item_id=item.id, stock=settings.default_stock
            )
        )
    db.commit()
    db.refresh(shop)
    return shop


def _maybe_restock(db: Session, shop: UserShop, settings: ShopSettings) -> bool:
    """到点补货:所有商品库存重置为默认。返回是否执行了补货。"""
    if (
        _utcnow() - ensure_aware(shop.restocked_at)
    ).total_seconds() < settings.restock_seconds:
        return False
    for row in (
        db.query(UserShopItem).filter(UserShopItem.player_id == shop.player_id).all()
    ):
        row.stock = settings.default_stock
    shop.restocked_at = _utcnow()
    db.commit()
    return True


def shop_state(db: Session, player: Player) -> dict:
    settings = get_settings(db)
    shop = ensure_shop(db, player)
    restocked = _maybe_restock(db, shop, settings)
    season = current_season(db, player)
    rows = {
        r.item_id: r
        for r in db.query(UserShopItem).filter(UserShopItem.player_id == player.id).all()
    }
    items = []
    for item in db.query(Item).filter(Item.active.is_(True)).order_by(Item.sort_order).all():
        row = rows.get(item.id)
        if not row:
            row = UserShopItem(
                player_id=player.id, item_id=item.id, stock=settings.default_stock
            )
            db.add(row)
            db.flush()
        items.append(
            {
                "item_id": str(item.id),
                "code": item.code,
                "name": item.name,
                "category": item.category,
                "effect": item.effect,
                "stock": row.stock,
                "buy_price": _item_price(item, settings, row),
                "sell_price": row.sell_price,
            }
        )
    crops = []
    for crop in db.query(Crop).filter(Crop.active.is_(True)).order_by(Crop.sort_order).all():
        crops.append(
            {
                "crop_id": str(crop.id),
                "name": crop.name,
                "category": crop.category,
                "base_price": crop.base_price,
                "sell_price": _crop_price(crop, settings, season),
                "season": SEASON_NAMES.get(season, season),
                "season_factor": (settings.season_effect or {}).get(season, 1.0),
                # 客户端展示宜种/解锁徽标与种子图标所需（纯增量，向后兼容）
                "art": crop.art or {},
                "sow_window": crop.sow_window or {},
                "unlock_level": crop.unlock_level or 0,
                "unlock_exp": crop.unlock_exp or 0,
            }
        )
    db.commit()
    return {
        "season": SEASON_NAMES.get(season, season),
        "restocked": restocked,
        "restock_seconds": settings.restock_seconds,
        "items": items,
        "crop_quotes": crops,
    }


def buy(db: Session, player: Player, item_id: str, quantity: int) -> dict:
    if quantity < 1:
        raise AppError("INVALID_PARAMS", "购买数量至少为 1", code=10001)
    try:
        iid = uuid.UUID(item_id)
    except ValueError:
        raise AppError("ITEM_NOT_FOUND", "商品不存在", code=22002)
    item = db.get(Item, iid)
    if not item or not item.active:
        raise AppError("ITEM_NOT_FOUND", "商品不存在", code=22002)
    settings = get_settings(db)
    shop = ensure_shop(db, player)
    _maybe_restock(db, shop, settings)
    row = (
        db.query(UserShopItem)
        .filter(UserShopItem.player_id == player.id, UserShopItem.item_id == iid)
        .first()
    )
    if not row:
        row = UserShopItem(player_id=player.id, item_id=iid, stock=0)
        db.add(row)
    if row.stock < quantity:
        raise AppError(
            "NOT_ENOUGH_STOCK", f"库存不足(剩余 {row.stock})", code=22006
        )
    price = _item_price(item, settings, row) * quantity
    if player.coins < price:
        raise AppError("NOT_ENOUGH_COINS", "金币不足", code=22003)
    player.coins -= price
    row.stock -= quantity
    ui = (
        db.query(UserItem)
        .filter(UserItem.player_id == player.id, UserItem.item_id == iid)
        .first()
    )
    if ui:
        ui.quantity += quantity
    else:
        db.add(UserItem(player_id=player.id, item_id=iid, quantity=quantity))
    db.add(
        CoinTransaction(player_id=player.id, amount=-price, reason=f"shop_buy:{item.code}")
    )
    db.add(
        ItemTransaction(
            player_id=player.id, item_id=iid, delta=quantity, reason=f"shop_buy:{item.code}"
        )
    )
    db.commit()
    return {
        "item_id": item_id,
        "code": item.code,
        "name": item.name,
        "quantity": quantity,
        "price": price,
        "stock_after": row.stock,
        "coins_balance": player.coins,
    }


def _settle_sale(
    db: Session,
    player: Player,
    crop: Crop,
    quantity: int,
    unit_price: int,
    wilted_unit_price: int,
    reason: str,
) -> dict:
    """公共结算:扣收成仓(先正常后枯萎)→ 加金币 → 账本。

    - 市场快速卖出与 AI 客人议价共用;unit_price 为正常收成单价,wilted_unit_price 为枯萎劣质单价
    - 返回与 sell_crop 一致的结算详情
    """
    row = (
        db.query(CropStorage)
        .filter(CropStorage.player_id == player.id, CropStorage.crop_id == crop.id)
        .first()
    )
    have = (row.quantity if row else 0) + (row.wilted_quantity if row else 0)
    if have < quantity:
        raise AppError("NOT_ENOUGH_CROP", f"收成仓不足(剩余 {have})", code=22007)
    normal = min(row.quantity, quantity)
    wilted = quantity - normal
    row.quantity -= normal
    row.wilted_quantity -= wilted
    price = normal * unit_price + wilted * wilted_unit_price
    player.coins += price
    db.add(CoinTransaction(player_id=player.id, amount=price, reason=reason))
    db.commit()
    return {
        "crop_id": str(crop.id),
        "name": crop.name,
        "quantity": quantity,
        "wilted": wilted,
        "price": price,
        "unit_price": price // quantity,  # 混合单价(正常与枯萎均价)
        "storage_after": (row.quantity if row else 0) + (row.wilted_quantity if row else 0),
        "coins_balance": player.coins,
    }


def sell_crop(db: Session, player: Player, crop_id: str, quantity: int) -> dict:
    if quantity < 1:
        raise AppError("INVALID_PARAMS", "出售数量至少为 1", code=10001)
    try:
        cid = uuid.UUID(crop_id)
    except ValueError:
        raise AppError("CROP_NOT_FOUND", "作物不存在", code=21005)
    crop = db.get(Crop, cid)
    if not crop:
        raise AppError("CROP_NOT_FOUND", "作物不存在", code=21005)
    settings = get_settings(db)
    season = current_season(db, player)
    unit = _crop_price(crop, settings, season)
    wilted_unit = _wilted_price(crop, settings, season)
    return _settle_sale(
        db, player, crop, quantity, unit, wilted_unit, f"shop_sell:{crop.name}"
    )


def storage(db: Session, player: Player) -> dict:
    settings = get_settings(db)
    season = current_season(db, player)
    rows = db.query(CropStorage).filter(CropStorage.player_id == player.id).all()
    crops = {
        c.id: c
        for c in db.query(Crop)
        .filter(Crop.id.in_([r.crop_id for r in rows]))
        .all()
    }
    items = [
        {
            "crop_id": str(r.crop_id),
            "name": crops[r.crop_id].name if r.crop_id in crops else "?",
            "quantity": r.quantity + r.wilted_quantity,  # 总数量(正常 + 枯萎劣质)
            "wilted_quantity": r.wilted_quantity,  # 其中枯萎劣质收成的数量
            "sell_price": _crop_price(crops[r.crop_id], settings, season)
            if r.crop_id in crops
            else 0,
            "wilted_sell_price": _wilted_price(crops[r.crop_id], settings, season)
            if r.crop_id in crops
            else 0,
            "season": SEASON_NAMES.get(season, season),
        }
        for r in rows
        if r.quantity > 0 or r.wilted_quantity > 0
    ]
    return {"season": SEASON_NAMES.get(season, season), "items": items}
