"""管理后台业务逻辑:统计 / 用户 / 全局配置 / 作物 / 道具 / 节气与时钟。"""
import os
import time
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import AppError
from app.models import (
    CoinTransaction,
    Crop,
    CropInstance,
    CropStorage,
    Farm,
    GameClock,
    GameConfig,
    Item,
    ItemTransaction,
    Player,
    Plot,
    TermConfig,
    User,
    UserItem,
    UserShop,
    UserShopItem,
)
from app.services import shop_service
from app.services import calendar_service, farm_service, world_service
from app.ws import manager
from scripts.seed import crop_uuid, item_uuid

_SENSITIVE_ENV = ("password", "secret", "token", "auth", "key", "credential")


def _mask_env(name: str, value: str) -> str:
    return "***" if any(s in name.lower() for s in _SENSITIVE_ENV) else value


# ---------- 仪表盘 ----------

def dashboard(db: Session) -> dict:
    clock = calendar_service.get_clock(db)
    url = settings.database_url
    db_size = 0
    if url.startswith("sqlite:///"):
        path = url.removeprefix("sqlite:///")
        if os.path.exists(path):
            db_size = os.path.getsize(path)
    return {
        "server": {
            "pid": os.getpid(),
            "version": "0.1.0",
            "admin_enabled": settings.admin_enabled,
            "debug_enabled": settings.debug_enabled,
            "db_size": db_size,
        },
        "clock": {
            "time_scale": float(clock.time_scale),
            "paused": clock.paused_at is not None,
        },
        "counts": {
            "users": db.query(func.count(User.id)).scalar() or 0,
            "players": db.query(func.count(Player.id)).scalar() or 0,
            "farms": db.query(func.count(Farm.id)).scalar() or 0,
            "coins_total": int(db.query(func.coalesce(func.sum(Player.coins), 0)).scalar()),
            "world_accum_total": int(db.query(func.coalesce(func.sum(Player.world_accum), 0)).scalar()),
            "crops": db.query(func.count(Crop.id)).scalar() or 0,
            "items": db.query(func.count(Item.id)).scalar() or 0,
            "terms": db.query(func.count(TermConfig.term_index)).scalar() or 0,
            "growing": (
                db.query(func.count(CropInstance.id))
                .filter(CropInstance.harvested_at.is_(None))
                .scalar()
                or 0
            ),
        },
    }


def list_env() -> dict:
    """系统环境变量只读展示(敏感值打码)。"""
    items = [
        {"name": k, "value": _mask_env(k, v)}
        for k, v in sorted(os.environ.items())
    ]
    return {"items": items[:100]}


# ---------- 用户 ----------

def list_users(db: Session, page: int, page_size: int) -> dict:
    total = db.query(func.count(User.id)).scalar() or 0
    rows = (
        db.query(User)
        .order_by(User.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    players = {
        p.user_id: p
        for p in db.query(Player).filter(Player.user_id.in_([u.id for u in rows])).all()
    }
    items = []
    for u in rows:
        p = players.get(u.id)
        items.append(
            {
                "user_id": str(u.id),
                "name": u.name,
                "status": u.status,
                "register_ip": u.register_ip,
                "register_location": u.register_location,
                "last_login_ip": u.last_login_ip,
                "last_login_location": u.last_login_location,
                "created_at": u.created_at.isoformat(),
                "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
                "player": (
                    {
                        "level": p.level,
                        "exp": p.exp,
                        "coins": p.coins,
                        "unlocked_term_index": p.unlocked_term_index,
                    }
                    if p
                    else None
                ),
            }
        )
    return {
        "items": items,
        "page": page,
        "page_size": page_size,
        "total": total,
    }


def set_user_status(db: Session, user_id: str, status: int) -> dict:
    """设置用户状态:1 正常 / 0 封禁 / 2 注销(留档冻结)。"""
    if status not in (0, 1, 2):
        raise AppError("INVALID_PARAMS", "status 只能是 0(封禁)/1(正常)/2(注销)", code=10001)
    try:
        user = db.query(User).filter(User.id == uuid.UUID(user_id)).first()
    except ValueError:
        user = None
    if not user:
        raise AppError("USER_NOT_FOUND", "用户不存在", code=20002)
    user.status = status
    if status == 2 and user.deactivated_at is None:
        user.deactivated_at = datetime.now(timezone.utc)
    elif status == 1:
        user.deactivated_at = None
    db.commit()
    return {"user_id": str(user.id), "name": user.name, "status": user.status}


def rename_user(db: Session, user_id: str, new_name: str) -> dict:
    """管理端改名(无限速):同步 User.name + Player.name。"""
    new_name = (new_name or "").strip()
    if not new_name or len(new_name) > 16:
        raise AppError("INVALID_PARAMS", "名字需 1-16 个字符", code=10001)
    try:
        user = db.query(User).filter(User.id == uuid.UUID(user_id)).first()
    except ValueError:
        user = None
    if not user:
        raise AppError("USER_NOT_FOUND", "用户不存在", code=20002)
    player = db.query(Player).filter(Player.user_id == user.id).first()
    user.name = new_name
    # Player.name 已废弃(展示统一走 User.name),不再双写
    db.commit()
    return {"user_id": str(user.id), "name": new_name}


# ---------- 全局配置 ----------

def list_config(db: Session) -> dict:
    rows = db.query(GameConfig).order_by(GameConfig.key).all()
    return {
        "items": [
            {"key": c.key, "value": c.value, "updated_at": c.updated_at.isoformat()}
            for c in rows
        ]
    }


def set_config(db: Session, key: str, value) -> dict:
    cfg = db.query(GameConfig).filter(GameConfig.key == key).first()
    if cfg:
        cfg.value = value
    else:
        db.add(GameConfig(key=key, value=value))
    db.commit()
    return {"key": key, "value": value}


def delete_config(db: Session, key: str) -> dict:
    cfg = db.query(GameConfig).filter(GameConfig.key == key).first()
    if cfg:
        db.delete(cfg)
        db.commit()
    return {"deleted": key}


# ---------- 作物 ----------

def _crop_view(c: Crop) -> dict:
    return {
        "crop_id": str(c.id),
        "name": c.name,
        "category": c.category,
        "sow_window": c.sow_window,
        "grow_seconds": c.grow_seconds,
        "yield_base": c.yield_base,
        "base_price": c.base_price,
        "unlock_level": c.unlock_level,
        "unlock_exp": c.unlock_exp,
        "settings": c.settings or {},
        "description": c.description,
        "art": c.art or {},
        "sort_order": c.sort_order,
        "active": c.active,
    }


def ensure_crop_art(crop: Crop) -> None:
    """作物没有美术时,生成通用占位 SVG 并写入 art 路径。"""
    if crop.art and crop.art.get("stages"):
        return
    from app.core.svg_art import generate_crop_art

    slug = crop.id.hex[:8]
    crop.art = generate_crop_art(slug, "#7cb342", "#f0c040", "grains")


def list_crops(db: Session) -> dict:
    rows = db.query(Crop).order_by(Crop.sort_order, Crop.name).all()
    return {"items": [_crop_view(c) for c in rows]}


def list_plantings(
    db: Session, page: int, page_size: int, active_only: bool = True
) -> dict:
    """全服每株种植中的植物实时状态(服务器权威)。"""
    q = (
        db.query(CropInstance, Plot, Farm, Player, User, Crop)
        .join(Plot, CropInstance.plot_id == Plot.id)
        .join(Farm, Plot.farm_id == Farm.id)
        .join(Player, Farm.owner_id == Player.id)
        .join(User, Player.user_id == User.id)
        .join(Crop, CropInstance.crop_id == Crop.id)
    )
    if active_only:
        q = q.filter(CropInstance.harvested_at.is_(None))
    total = q.count()
    rows = (
        q.order_by(CropInstance.sowed_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    items = []
    for ci, plot, farm, player, user, crop in rows:
        view = farm_service.crop_view(ci, crop)  # stage/progress/water/predicted(服务器推导)
        items.append(
            {
                "planting_id": str(ci.id),
                "player": user.name,
                "farm": farm.name,
                "plot_idx": plot.idx,
                "crop": crop.name,
                **view,
                "sowed_term_index": ci.sowed_term_index,
                "sowed_at": ci.sowed_at.isoformat(),
            }
        )
    return {"items": items, "page": page, "page_size": page_size, "total": total}


def create_crop(db: Session, data: dict, auto_seed: bool = False) -> dict:
    name = (data.get("name") or "").strip()
    if not name:
        raise AppError("INVALID_PARAMS", "作物名称必填", code=10001)
    if db.query(Crop).filter(Crop.name == name).first():
        raise AppError("CROP_EXISTS", f"作物 {name} 已存在", code=21006)
    crop = Crop(
        id=crop_uuid(name),
        name=name,
        category=data.get("category", "谷物"),
        sow_window=data.get("sow_window", {"type": "term", "start": 1, "end": 24, "grace": 0}),
        grow_seconds=int(data.get("grow_seconds", 600)),
        yield_base=int(data.get("yield_base", 3)),
        base_price=int(data.get("base_price", 10)),
        unlock_level=int(data.get("unlock_level", 1)),
        unlock_exp=int(data.get("unlock_exp", 0)),
        settings=data.get("settings") or {},
        description=data.get("description"),
        sort_order=int(data.get("sort_order", 0)),
    )
    db.add(crop)
    db.flush()
    seed_created = False
    if auto_seed:
        code = f"seed_{crop.id.hex[:8]}"
        seed = Item(
            id=item_uuid(code),
            code=code,
            name=f"{name}种子",
            category="seed",
            effect={"type": "seed", "crop_id": str(crop.id)},
            buy_price=max(1, crop.base_price // 2),
            sell_price=max(1, crop.base_price // 10),
            sort_order=100,
        )
        db.add(seed)
        seed_created = True
    if data.get("art"):
        crop.art = data["art"]
    else:
        ensure_crop_art(crop)  # 生成通用占位 SVG
    db.commit()
    view = _crop_view(crop)
    view["seed_created"] = seed_created
    # 同步写回植物设定文件(data/crops/<slug>.json),保持文件为事实源
    try:
        from scripts.crop_loader import dump_crop_file

        dump_crop_file(
            {
                "slug": crop.id.hex[:8],
                "name": crop.name,
                "category": crop.category,
                "sort_order": crop.sort_order,
                "sow_window": crop.sow_window,
                "grow_seconds": crop.grow_seconds,
                "yield_base": crop.yield_base,
                "base_price": crop.base_price,
                "unlock_level": crop.unlock_level,
                "unlock_exp": crop.unlock_exp,
                "settings": crop.settings or {},
                "note": "管理后台新建(文件为事实源,可直接改)",
            }
        )
    except Exception:
        pass  # 文件写失败不影响后台操作(下次 seed 会从 DB 无法回写,提示团队注意)
    return view


def update_crop(db: Session, crop_id: str, data: dict) -> dict:
    try:
        crop = db.query(Crop).filter(Crop.id == uuid.UUID(crop_id)).first()
    except ValueError:
        crop = None
    if not crop:
        raise AppError("CROP_NOT_FOUND", "作物不存在", code=21005)
    for field in (
        "name",
        "category",
        "sow_window",
        "grow_seconds",
        "yield_base",
        "base_price",
        "unlock_level",
        "unlock_exp",
        "settings",
        "description",
        "art",
        "sort_order",
        "active",
    ):
        if field in data:
            setattr(crop, field, data[field])
    db.commit()
    # 同步写回植物设定文件(保持文件为事实源)
    try:
        from scripts.crop_loader import dump_crop_file

        dump_crop_file(
            {
                "slug": crop.id.hex[:8],
                "name": crop.name,
                "category": crop.category,
                "sort_order": crop.sort_order,
                "sow_window": crop.sow_window,
                "grow_seconds": crop.grow_seconds,
                "yield_base": crop.yield_base,
                "base_price": crop.base_price,
                "unlock_level": crop.unlock_level,
                "unlock_exp": crop.unlock_exp,
                "settings": crop.settings or {},
                "note": "管理后台更新(文件为事实源,可直接改)",
            }
        )
    except Exception:
        pass
    return _crop_view(crop)


def delete_crop(db: Session, crop_id: str) -> dict:
    try:
        crop = db.query(Crop).filter(Crop.id == uuid.UUID(crop_id)).first()
    except ValueError:
        crop = None
    if not crop:
        raise AppError("CROP_NOT_FOUND", "作物不存在", code=21005)
    growing = (
        db.query(CropInstance)
        .filter(CropInstance.crop_id == crop.id, CropInstance.harvested_at.is_(None))
        .first()
    )
    if growing:
        raise AppError("CROP_IN_USE", "该作物正在种植,无法删除", code=21007)
    crop.active = False
    # 同时下架其种子道具(SQLite 不支持 JSON path 查询,Python 侧过滤)
    crop_id_str = str(crop.id)
    for it in db.query(Item).all():
        eff = it.effect or {}
        if eff.get("type") == "seed" and str(eff.get("crop_id", "")) == crop_id_str:
            it.active = False
    db.commit()
    return {"crop_id": str(crop.id), "active": False}


# ---------- 道具 ----------

def _item_view(i: Item) -> dict:
    return {
        "item_id": str(i.id),
        "code": i.code,
        "name": i.name,
        "category": i.category,
        "stackable": i.stackable,
        "max_stack": i.max_stack,
        "effect": i.effect,
        "buy_price": i.buy_price,
        "sell_price": i.sell_price,
        "unlock_level": i.unlock_level,
        "sort_order": i.sort_order,
        "active": i.active,
    }


def list_items(db: Session) -> dict:
    rows = db.query(Item).order_by(Item.sort_order, Item.code).all()
    return {"items": [_item_view(i) for i in rows]}


def create_item(db: Session, data: dict) -> dict:
    code = (data.get("code") or "").strip()
    name = (data.get("name") or "").strip()
    if not code or not name:
        raise AppError("INVALID_PARAMS", "code 与 name 必填", code=10001)
    if db.query(Item).filter(Item.code == code).first():
        raise AppError("ITEM_EXISTS", f"道具 {code} 已存在", code=22005)
    effect = data.get("effect") or {}
    if effect.get("type") == "seed":
        crop = db.query(Crop).filter(Crop.id == uuid.UUID(str(effect["crop_id"]))).first()
        if not crop:
            raise AppError("INVALID_PARAMS", "种子效果的 crop_id 无效", code=10001)
    item = Item(
        code=code,
        name=name,
        category=data.get("category", "tool"),
        effect=effect,
        buy_price=data.get("buy_price"),
        sell_price=data.get("sell_price"),
        unlock_level=int(data.get("unlock_level", 1)),
        sort_order=int(data.get("sort_order", 0)),
    )
    db.add(item)
    db.commit()
    return _item_view(item)


def update_item(db: Session, item_id: str, data: dict) -> dict:
    try:
        item = db.query(Item).filter(Item.id == uuid.UUID(item_id)).first()
    except ValueError:
        item = None
    if not item:
        raise AppError("ITEM_NOT_FOUND", "道具不存在", code=22002)
    for field in (
        "name",
        "category",
        "stackable",
        "max_stack",
        "effect",
        "buy_price",
        "sell_price",
        "unlock_level",
        "sort_order",
        "active",
    ):
        if field in data:
            setattr(item, field, data[field])
    db.commit()
    return _item_view(item)


def delete_item(db: Session, item_id: str) -> dict:
    try:
        item = db.query(Item).filter(Item.id == uuid.UUID(item_id)).first()
    except ValueError:
        item = None
    if not item:
        raise AppError("ITEM_NOT_FOUND", "道具不存在", code=22002)
    item.active = False
    db.commit()
    return {"item_id": str(item.id), "code": item.code, "active": False}


# ---------- 节气与时钟 ----------

def list_terms(db: Session) -> dict:
    rows = db.query(TermConfig).order_by(TermConfig.term_index).all()
    clock = calendar_service.get_clock(db)
    return {
        "items": [
            {"term_index": t.term_index, "name": t.name, "duration_seconds": t.duration_seconds}
            for t in rows
        ],
        "clock": {
            "time_scale": float(clock.time_scale),
            "paused": clock.paused_at is not None,
        },
    }


def set_term_duration(db: Session, term_index: int, duration_seconds: int) -> dict:
    term = db.query(TermConfig).filter(TermConfig.term_index == term_index).first()
    if not term:
        raise AppError("TERM_NOT_FOUND", "节气不存在", code=23002)
    term.duration_seconds = duration_seconds
    db.commit()
    return {"term_index": term.term_index, "name": term.name, "duration_seconds": term.duration_seconds}


def update_clock(
    db: Session,
    time_scale: float | None = None,
    paused: bool | None = None,
) -> dict:
    clock = calendar_service.get_clock(db)
    if time_scale is not None:
        clock.time_scale = time_scale
    if paused is not None:
        clock.paused_at = datetime.now(timezone.utc) if paused else None
    db.commit()
    return {
        "time_scale": float(clock.time_scale),
        "paused": clock.paused_at is not None,
    }


# ---------- 商店管理(全局默认 + 每用户商店) ----------

def shop_settings_view(db) -> dict:
    s = shop_service.get_settings(db)
    return {
        "default_stock": s.default_stock,
        "restock_seconds": s.restock_seconds,
        "sell_factor": s.sell_factor,
        "item_factor": s.item_factor,
        "season_effect": s.season_effect or {},
        "category_factor": s.category_factor or {},
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }


def update_shop_settings(db, data: dict) -> dict:
    s = shop_service.get_settings(db)
    for field in (
        "default_stock",
        "restock_seconds",
        "sell_factor",
        "item_factor",
        "season_effect",
        "category_factor",
    ):
        if field in data and data[field] is not None:
            setattr(s, field, data[field])
    db.commit()
    return shop_settings_view(db)


def list_user_shops(db, page: int, page_size: int) -> dict:
    """全部用户的商店摘要(LEFT JOIN:未触发的用户也展示,counts 为 0)。"""
    total = db.query(func.count(User.id)).scalar() or 0
    rows = (
        db.query(User, Player, UserShop)
        .join(Player, Player.user_id == User.id)
        .outerjoin(UserShop, UserShop.player_id == Player.id)
        .order_by(User.created_at.desc(), User.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    stat = {
        pid: (cnt, stock)
        for pid, cnt, stock in db.query(
            UserShopItem.player_id,
            func.count(UserShopItem.id),
            func.coalesce(func.sum(UserShopItem.stock), 0),
        )
        .group_by(UserShopItem.player_id)
        .all()
    }
    ovr = {
        pid: cnt
        for pid, cnt in db.query(
            UserShopItem.player_id, func.count(UserShopItem.id)
        )
        .filter(
            or_(
                UserShopItem.buy_price.isnot(None),
                UserShopItem.sell_price.isnot(None),
            )
        )
        .group_by(UserShopItem.player_id)
        .all()
    }
    items = []
    for user, player, shop in rows:
        cnt, stock = stat.get(player.id, (0, 0))
        items.append(
            {
                "player_id": str(player.id),
                "name": user.name,
                "status": user.status,
                "item_count": cnt,
                "total_stock": stock,
                "override_count": ovr.get(player.id, 0),
                "restocked_at": shop.restocked_at.isoformat() if shop else None,
                "created_at": shop.created_at.isoformat() if shop else None,
            }
        )
    return {"items": items, "page": page, "page_size": page_size, "total": total}


def list_user_shop_items(db, player_id: str) -> dict:
    try:
        pid = uuid.UUID(player_id)
    except ValueError:
        raise AppError("USER_NOT_FOUND", "用户不存在", code=20002)
    s = shop_service.get_settings(db)
    rows = {
        r.item_id: r
        for r in db.query(UserShopItem).filter(UserShopItem.player_id == pid).all()
    }
    items = []
    for item in db.query(Item).filter(Item.active.is_(True)).order_by(Item.sort_order).all():
        r = rows.get(item.id)
        items.append(
            {
                "item_id": str(item.id),
                "code": item.code,
                "name": item.name,
                "category": item.category,
                "stock": r.stock if r else s.default_stock,
                "formula_price": item.buy_price or 1,
                "buy_price": shop_service._item_price(item, s, r),
                "buy_override": r.buy_price if r else None,
                "sell_override": r.sell_price if r else None,
            }
        )
    return {"items": items}


def update_user_shop_item(db, player_id: str, item_id: str, data: dict) -> dict:
    try:
        pid = uuid.UUID(player_id)
        iid = uuid.UUID(item_id)
    except ValueError:
        raise AppError("USER_NOT_FOUND", "用户或商品不存在", code=20002)
    shop = shop_service.ensure_shop(db, db.query(Player).filter(Player.id == pid).first())
    row = (
        db.query(UserShopItem)
        .filter(UserShopItem.player_id == pid, UserShopItem.item_id == iid)
        .first()
    )
    if not row:
        row = UserShopItem(player_id=pid, item_id=iid, stock=0)
        db.add(row)
    if "stock" in data and data["stock"] is not None:
        row.stock = max(0, int(data["stock"]))
    for field in ("buy_price", "sell_price"):
        if field in data:
            # 显式 null = 清除覆盖,恢复公式价
            row.__setattr__(field, data[field])
    db.commit()
    return {"item_id": item_id, "stock": row.stock, "buy_override": row.buy_price, "sell_override": row.sell_price}


def restock_user_shop(db, player_id: str) -> dict:
    pid = uuid.UUID(player_id)
    s = shop_service.get_settings(db)
    shop = shop_service.ensure_shop(db, db.query(Player).filter(Player.id == pid).first())
    for row in db.query(UserShopItem).filter(UserShopItem.player_id == pid).all():
        row.stock = s.default_stock
    shop.restocked_at = datetime.now(timezone.utc)
    db.commit()
    return {"player_id": player_id, "restocked": True, "default_stock": s.default_stock}


def reset_user_shop(db, player_id: str) -> dict:
    pid = uuid.UUID(player_id)
    s = shop_service.get_settings(db)
    shop_service.ensure_shop(db, db.query(Player).filter(Player.id == pid).first())
    for row in db.query(UserShopItem).filter(UserShopItem.player_id == pid).all():
        row.buy_price = None
        row.sell_price = None
        row.stock = s.default_stock
    shop.restocked_at = datetime.now(timezone.utc)
    db.commit()
    return {"player_id": player_id, "reset": True}


# ---------- 玩家资产 / 农场 / 每用户世界(节气独立) ----------

def _player_by_user(db: Session, user_id: str) -> Player:
    try:
        user = db.query(User).filter(User.id == uuid.UUID(user_id)).first()
    except ValueError:
        user = None
    if not user:
        raise AppError("USER_NOT_FOUND", "用户不存在", code=20002)
    player = db.query(Player).filter(Player.user_id == user.id).first()
    if not player:
        raise AppError("USER_NOT_FOUND", "玩家不存在", code=20002)
    return player


def update_player_assets(db: Session, user_id: str, data: dict) -> dict:
    """玩家资产编辑:金币 / 等级 / 经验 / 解锁节气(全可选)。

    编辑后向该玩家在线 WS 推送 resources_changed,客户端据此强制刷新本地资源。
    金币变动写 coin_transactions 账本,保持"金币走账本"可审计原则。
    """
    player = _player_by_user(db, user_id)
    coin_delta = None
    for field in ("coins", "level", "exp", "unlocked_term_index"):
        if field in data and data[field] is not None:
            if field == "coins":
                coin_delta = int(data[field]) - (player.coins or 0)
            setattr(player, field, data[field])
    if coin_delta is not None and coin_delta != 0:
        db.add(
            CoinTransaction(
                player_id=player.id, amount=coin_delta, reason="admin_edit"
            )
        )
    db.commit()
    assets = get_player_assets(db, user_id)
    manager.push_sync(
        str(player.id),
        {
            "type": "resources_changed",
            "payload": assets,
            "ts": int(time.time()),
        },
    )
    return assets


def get_player_assets(db: Session, user_id: str) -> dict:
    """玩家当前资产(管理端查看/弹窗预填)。"""
    player = _player_by_user(db, user_id)
    user = db.query(User).filter(User.id == player.user_id).first()
    return {
        "player_id": str(player.id),
        "name": user.name,
        "level": player.level,
        "exp": player.exp,
        "coins": player.coins,
        "unlocked_term_index": player.unlocked_term_index,
    }


def list_player_farm(db: Session, user_id: str) -> dict:
    """某用户的农场:地块 + 当前作物 + 玩家当前节气(每用户世界)。"""
    player = _player_by_user(db, user_id)
    farm = db.query(Farm).filter(Farm.owner_id == player.id).first()
    if not farm:
        raise AppError("FARM_NOT_FOUND", "农场不存在", code=21000)
    plots = db.query(Plot).filter(Plot.farm_id == farm.id).order_by(Plot.idx).all()
    active = (
        db.query(CropInstance)
        .filter(
            CropInstance.plot_id.in_([p.id for p in plots]),
            CropInstance.harvested_at.is_(None),
            CropInstance.destroyed_at.is_(None),
        )
        .all()
    )
    crops = {ci.plot_id: ci for ci in active}
    crop_defs = {c.id: c for c in db.query(Crop).all()}
    term, cycle, remaining = world_service.peek_term(db, player)
    user = db.query(User).filter(User.id == player.user_id).first()
    return {
        "player_id": str(player.id),
        "name": user.name,
        "farm": {
            "farm_id": str(farm.id),
            "name": farm.name,
            "plot_count": farm.plot_count,
            "grid": {"cols": farm_service.FARM_COLS, "rows": farm_service.FARM_ROWS},
        },
        "current_term": {
            "term_index": term.term_index,
            "name": term.name,
            "cycle": cycle,
            "remaining_sec": remaining,
        },
        "plots": [
            {
                "plot_id": str(p.id),
                "idx": p.idx,
                "soil_quality": p.soil_quality,
                "locked": p.locked,
                "crop": _plot_crop_view(crops.get(p.id), crop_defs),
            }
            for p in plots
        ],
    }


def _plot_crop_view(ci, crop_defs):
    if ci is None:
        return None
    return farm_service.crop_view(ci, crop_defs.get(ci.crop_id))


def update_player_plot(db: Session, user_id: str, plot_idx: int, data: dict) -> dict:
    """农场地块管理:锁定/解锁、土壤肥力。"""
    player = _player_by_user(db, user_id)
    farm = db.query(Farm).filter(Farm.owner_id == player.id).first()
    if not farm:
        raise AppError("FARM_NOT_FOUND", "农场不存在", code=21000)
    plot = (
        db.query(Plot)
        .filter(Plot.farm_id == farm.id, Plot.idx == plot_idx)
        .first()
    )
    if not plot:
        raise AppError("PLOT_NOT_FOUND", "地块不存在", code=21001)
    if data.get("locked") is not None:
        plot.locked = data["locked"]
    if data.get("soil_quality") is not None:
        plot.soil_quality = data["soil_quality"]
    db.commit()
    return {
        "plot_id": str(plot.id),
        "idx": plot.idx,
        "soil_quality": plot.soil_quality,
        "locked": plot.locked,
    }


# ---------- 地块作物 / 背包 / 收成仓控制(管理端,纯后台直接改库) ----------

def _player_plot(db: Session, user_id: str, plot_idx: int) -> tuple[Player, Farm, Plot]:
    player = _player_by_user(db, user_id)
    farm = db.query(Farm).filter(Farm.owner_id == player.id).first()
    if not farm:
        raise AppError("FARM_NOT_FOUND", "农场不存在", code=21000)
    plot = db.query(Plot).filter(Plot.farm_id == farm.id, Plot.idx == plot_idx).first()
    if not plot:
        raise AppError("PLOT_NOT_FOUND", "地块不存在", code=21001)
    return player, farm, plot


def _clear_active_crop(db: Session, plot_id) -> None:
    """把地块现有活跃作物标记为已收获(yield=0),释放部分唯一索引。"""
    ci = (
        db.query(CropInstance)
        .filter(CropInstance.plot_id == plot_id, CropInstance.harvested_at.is_(None))
        .first()
    )
    if ci:
        ci.harvested_at = datetime.now(timezone.utc)
        ci.yield_actual = 0


def admin_set_plot_crop(db: Session, user_id: str, plot_idx: int, data: dict) -> dict:
    """给地块种植/替换指定作物(管理端:不消耗种子、不校验节气窗)。

    growth_progress 是唯一真源:按进度回拨 sowed_at,stage 由 crop_view 推导。
    """
    player, farm, plot = _player_plot(db, user_id, plot_idx)
    try:
        crop_id = uuid.UUID(data["crop_id"])
    except (ValueError, KeyError):
        raise AppError("CROP_NOT_FOUND", "作物不存在", code=21005)
    crop = db.query(Crop).filter(Crop.id == crop_id, Crop.active.is_(True)).first()
    if not crop:
        raise AppError("CROP_NOT_FOUND", "作物不存在", code=21005)

    now = datetime.now(timezone.utc)
    progress = max(0, min(100, int(data.get("growth_progress", 0))))
    water_level = max(0, min(100, int(data.get("water_level", 100))))

    _clear_active_crop(db, plot.id)
    term, _, _ = world_service.peek_term(db, player, now)
    grow = crop.grow_seconds
    sowed_at = now - timedelta(seconds=grow * progress / 100.0)
    ci = CropInstance(
        plot_id=plot.id,
        crop_id=crop.id,
        sowed_at=sowed_at,
        sowed_term_index=term.term_index,
        water_level=water_level,
        predicted_harvest_at=now + timedelta(seconds=grow * (1 - progress / 100.0)),
        extra={"watered_at": now.isoformat()},  # 水分衰减从管理端设定时刻重新计时
    )
    db.add(ci)
    db.commit()
    view = farm_service.crop_view(ci, crop)
    return {"plot_id": str(plot.id), "idx": plot.idx, **view}


def admin_clear_plot_crop(db: Session, user_id: str, plot_idx: int) -> dict:
    """清除地块作物(管理端,无产量)。"""
    player, farm, plot = _player_plot(db, user_id, plot_idx)
    _clear_active_crop(db, plot.id)
    db.commit()
    return {"plot_id": str(plot.id), "idx": plot.idx, "cleared": True}


def admin_set_plot_growth(db: Session, user_id: str, plot_idx: int, data: dict) -> dict:
    """调整已有作物生长进度% / 浇水(管理端)。"""
    player, farm, plot = _player_plot(db, user_id, plot_idx)
    ci = (
        db.query(CropInstance)
        .filter(CropInstance.plot_id == plot.id, CropInstance.harvested_at.is_(None))
        .first()
    )
    if not ci:
        raise AppError("PLOT_EMPTY", "该地块没有作物", code=21004)
    crop = db.query(Crop).filter(Crop.id == ci.crop_id).first()
    now = datetime.now(timezone.utc)
    if data.get("growth_progress") is not None:
        progress = max(0, min(100, int(data["growth_progress"])))
        grow = crop.grow_seconds if crop else 600
        ci.sowed_at = now - timedelta(seconds=grow * progress / 100.0)
        ci.predicted_harvest_at = now + timedelta(seconds=grow * (1 - progress / 100.0))
    if data.get("water_level") is not None:
        ci.water_level = max(0, min(100, int(data["water_level"])))
        extra = dict(ci.extra or {})
        extra["watered_at"] = now.isoformat()  # 水分衰减从管理端设定时刻重新计时
        ci.extra = extra
    db.commit()
    view = farm_service.crop_view(ci, crop)
    return {"plot_id": str(plot.id), "idx": plot.idx, **view}


def admin_set_inventory(db: Session, user_id: str, item_id: str, quantity: int) -> dict:
    """设定玩家道具数量(绝对值;0=清空)。写 ItemTransaction 账本便于审计。"""
    player = _player_by_user(db, user_id)
    try:
        iid = uuid.UUID(item_id)
    except ValueError:
        raise AppError("ITEM_NOT_FOUND", "道具不存在", code=22002)
    item = db.query(Item).filter(Item.id == iid).first()
    if not item:
        raise AppError("ITEM_NOT_FOUND", "道具不存在", code=22002)
    quantity = max(0, int(quantity))
    row = (
        db.query(UserItem)
        .filter(UserItem.player_id == player.id, UserItem.item_id == iid)
        .first()
    )
    old = row.quantity if row else 0
    if quantity == 0:
        if row:
            db.delete(row)
    elif row:
        row.quantity = quantity
    else:
        db.add(UserItem(player_id=player.id, item_id=iid, quantity=quantity))
    db.add(
        ItemTransaction(
            player_id=player.id,
            item_id=iid,
            delta=quantity - old,
            reason="admin",
        )
    )
    db.commit()
    return {"player_id": str(player.id), "item_id": item_id, "code": item.code, "quantity": quantity}


def list_player_inventory(db: Session, user_id: str) -> dict:
    """玩家背包明细(全部道具,数量 0 也展示),供管理端控制面板。"""
    player = _player_by_user(db, user_id)
    rows = {
        r.item_id: r.quantity
        for r in db.query(UserItem).filter(UserItem.player_id == player.id).all()
    }
    items = [
        {
            "item_id": str(i.id),
            "code": i.code,
            "name": i.name,
            "category": i.category,
            "quantity": rows.get(i.id, 0),
            "active": i.active,
        }
        for i in db.query(Item).order_by(Item.sort_order, Item.code).all()
    ]
    return {"player_id": str(player.id), "items": items}


def admin_set_storage(db: Session, user_id: str, crop_id: str, quantity: int) -> dict:
    """设定收成仓该作物库存(绝对值;0=清空)。"""
    player = _player_by_user(db, user_id)
    try:
        cid = uuid.UUID(crop_id)
    except ValueError:
        raise AppError("CROP_NOT_FOUND", "作物不存在", code=21005)
    crop = db.query(Crop).filter(Crop.id == cid).first()
    if not crop:
        raise AppError("CROP_NOT_FOUND", "作物不存在", code=21005)
    quantity = max(0, int(quantity))
    row = (
        db.query(CropStorage)
        .filter(CropStorage.player_id == player.id, CropStorage.crop_id == cid)
        .first()
    )
    if quantity == 0:
        if row:
            db.delete(row)
    elif row:
        row.quantity = quantity
        row.wilted_quantity = 0  # 管理端设定为正常收成(绝对值),清空枯萎劣质部分
    else:
        db.add(CropStorage(player_id=player.id, crop_id=cid, quantity=quantity))
    db.commit()
    return {"player_id": str(player.id), "crop_id": crop_id, "name": crop.name, "quantity": quantity}


def list_player_storage(db: Session, user_id: str) -> dict:
    """玩家收成仓明细(全部作物,数量 0 也展示),供管理端控制面板。"""
    player = _player_by_user(db, user_id)
    rows = {
        r.crop_id: (r.quantity, r.wilted_quantity)
        for r in db.query(CropStorage).filter(CropStorage.player_id == player.id).all()
    }
    crops = [
        {
            "crop_id": str(c.id),
            "name": c.name,
            "category": c.category,
            "quantity": rows.get(c.id, (0, 0))[0],
            "wilted_quantity": rows.get(c.id, (0, 0))[1],  # 枯萎劣质收成(售价打折)
            "active": c.active,
        }
        for c in db.query(Crop).order_by(Crop.sort_order, Crop.name).all()
    ]
    return {"player_id": str(player.id), "crops": crops}


def list_worlds(db: Session, page: int, page_size: int) -> dict:
    """每用户世界/节气列表(含在线状态与累计世界秒)。"""
    total = db.query(func.count(Player.id)).scalar() or 0
    rows = (
        db.query(Player, User)
        .join(User, User.id == Player.user_id)
        .order_by(Player.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    now = datetime.now(timezone.utc)
    cfg = world_service.world_config(db)
    items = []
    for player, user in rows:
        term, cycle, remaining = world_service.peek_term(db, player, now)
        items.append(
            {
                "player_id": str(player.id),
                "name": user.name,
                "online": world_service.is_online(player, now, cfg["online_threshold"]),
                "last_active_at": (
                    player.last_active_at.isoformat() if player.last_active_at else None
                ),
                "world_accum": float(player.world_accum or 0.0),
                "time_scale_override": player.time_scale_override,
                "world_last_sync": (
                    player.world_last_sync.isoformat() if player.world_last_sync else None
                ),
                "current_term": {
                    "term_index": term.term_index,
                    "name": term.name,
                    "cycle": cycle,
                    "remaining_sec": remaining,
                },
            }
        )
    return {"items": items, "page": page, "page_size": page_size, "total": total}


def update_world(
    db: Session, player_id: str, accum: float | None = None, reset: bool = False,
    time_scale: float | None = None, clear_override: bool = False,
) -> dict:
    """重置/设定某玩家世界:reset 回到立春;accum 设定累计世界秒;time_scale 覆盖速率;clear_override 恢复全局。"""
    try:
        pid = uuid.UUID(player_id)
    except ValueError:
        raise AppError("USER_NOT_FOUND", "用户不存在", code=20002)
    player = db.query(Player).filter(Player.id == pid).first()
    if not player:
        raise AppError("USER_NOT_FOUND", "玩家不存在", code=20002)
    return world_service.set_world(
        db, player, accum=accum, reset=reset,
        time_scale=time_scale, clear_override=clear_override,
    )
