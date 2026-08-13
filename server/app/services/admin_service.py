"""管理后台业务逻辑:统计 / 用户 / 全局配置 / 作物 / 道具 / 节气与时钟。"""
import os
import uuid
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import AppError
from app.models import (
    Crop,
    CropInstance,
    Farm,
    GameClock,
    GameConfig,
    Item,
    Player,
    TermConfig,
    User,
)
from app.services import calendar_service
from scripts.seed import crop_uuid, item_uuid

_SENSITIVE_ENV = ("password", "secret", "token", "auth", "key", "credential")


def _mask_env(name: str, value: str) -> str:
    return "***" if any(s in name.lower() for s in _SENSITIVE_ENV) else value


# ---------- 仪表盘 ----------

def dashboard(db: Session) -> dict:
    cal = calendar_service.current_calendar(db)
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
        "calendar": cal,
        "counts": {
            "users": db.query(func.count(User.id)).scalar() or 0,
            "players": db.query(func.count(Player.id)).scalar() or 0,
            "farms": db.query(func.count(Farm.id)).scalar() or 0,
            "coins_total": int(db.query(func.coalesce(func.sum(Player.coins), 0)).scalar()),
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
                "last_login_ip": u.last_login_ip,
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
    try:
        user = db.query(User).filter(User.id == uuid.UUID(user_id)).first()
    except ValueError:
        user = None
    if not user:
        raise AppError("USER_NOT_FOUND", "用户不存在", code=20002)
    user.status = status
    db.commit()
    return {"user_id": str(user.id), "name": user.name, "status": user.status}


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
        "description": c.description,
        "sort_order": c.sort_order,
        "active": c.active,
    }


def list_crops(db: Session) -> dict:
    rows = db.query(Crop).order_by(Crop.sort_order, Crop.name).all()
    return {"items": [_crop_view(c) for c in rows]}


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
    db.commit()
    view = _crop_view(crop)
    view["seed_created"] = seed_created
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
        "description",
        "sort_order",
        "active",
    ):
        if field in data:
            setattr(crop, field, data[field])
    db.commit()
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
            "epoch": clock.epoch.isoformat(),
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
    reset_epoch: bool = False,
) -> dict:
    clock = calendar_service.get_clock(db)
    if time_scale is not None:
        clock.time_scale = time_scale
    if paused is not None:
        clock.paused_at = datetime.now(timezone.utc) if paused else None
    if reset_epoch:
        clock.epoch = datetime.now(timezone.utc)
    db.commit()
    return {
        "epoch": clock.epoch.isoformat(),
        "time_scale": float(clock.time_scale),
        "paused": clock.paused_at is not None,
    }
