import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.utils import ensure_aware
from app.models import (
    Crop,
    CropInstance,
    CropStorage,
    Farm,
    Item,
    ItemTransaction,
    Plot,
    UserItem,
)
from app.services.calendar_service import current_calendar, get_current_term

_SEASON_TERMS = {1: (1, 6), 2: (7, 12), 3: (13, 18), 4: (19, 24)}  # 春/夏/秋/冬

FARM_COLS = 4  # 田地格子:横 4
FARM_ROWS = 5  # 竖 5
# 格子编号规则:idx 1-20,按行优先 —— idx = (row-1)*4 + col (row∈1..5, col∈1..4)


def _get_farm(db: Session, player) -> Farm:
    farm = db.query(Farm).filter(Farm.owner_id == player.id).first()
    if not farm:
        raise AppError("FARM_NOT_FOUND", "农场不存在", code=21000)
    return farm


def _get_active_crop(db: Session, player, plot_id: str) -> CropInstance:
    try:
        plot_uuid = uuid.UUID(plot_id)
    except ValueError:
        raise AppError("PLOT_NOT_FOUND", "地块不存在", code=21001)
    plot = db.query(Plot).filter(Plot.id == plot_uuid).first()
    if not plot:
        raise AppError("PLOT_NOT_FOUND", "地块不存在", code=21001)
    farm = db.query(Farm).filter(Farm.id == plot.farm_id).first()
    if farm.owner_id != player.id:
        raise AppError("PLOT_NOT_FOUND", "地块不存在", code=21001)
    ci = (
        db.query(CropInstance)
        .filter(CropInstance.plot_id == plot.id, CropInstance.harvested_at.is_(None))
        .first()
    )
    if not ci:
        raise AppError("PLOT_EMPTY", "该地块没有作物", code=21004)
    return ci


def crop_view(ci: CropInstance, crop: Crop | None) -> dict:
    now = datetime.now(timezone.utc)
    grow = crop.grow_seconds if crop else 0
    sowed = ensure_aware(ci.sowed_at)
    base = (now - sowed).total_seconds() / grow * 100 if grow else 0.0
    boost = float((ci.extra or {}).get("boost_pct", 0))
    progress = min(100.0, base + boost)
    stage = 3 if progress >= 100 else (2 if progress >= 50 else 1)
    return {
        "crop_id": str(ci.crop_id),
        "name": crop.name if crop else "?",
        "art": (crop.art if crop else {}) or {},
        "stage": stage,
        "growth_progress": int(progress),
        "water_level": ci.water_level,
        "predicted_harvest_at": (
            ci.predicted_harvest_at.isoformat() if ci.predicted_harvest_at else None
        ),
    }


def get_farm_state(db: Session, player) -> dict:
    farm = _get_farm(db, player)
    plots = db.query(Plot).filter(Plot.farm_id == farm.id).order_by(Plot.idx).all()
    active = (
        db.query(CropInstance)
        .filter(
            CropInstance.plot_id.in_([p.id for p in plots]),
            CropInstance.harvested_at.is_(None),
        )
        .all()
    )
    crops = {ci.plot_id: ci for ci in active}
    crop_defs = {c.id: c for c in db.query(Crop).all()}
    plot_list = []
    for p in plots:
        ci = crops.get(p.id)
        plot_list.append(
            {
                "plot_id": str(p.id),
                "idx": p.idx,
                "soil_quality": p.soil_quality,
                "locked": p.locked,
                "crop": crop_view(ci, crop_defs.get(ci.crop_id)) if ci else None,
            }
        )
    return {
        "farm": {
            "farm_id": str(farm.id),
            "name": farm.name,
            "plot_count": farm.plot_count,
            "grid": {"cols": FARM_COLS, "rows": FARM_ROWS},  # 4×5,idx 行优先
        },
        "current_term": current_calendar(db),
        "plots": plot_list,
    }


def _check_sow_window(crop: Crop, term_index: int) -> bool:
    win = crop.sow_window or {}
    if win.get("type") == "term":
        start = int(win.get("start", 1))
        end = int(win.get("end", 24))
        grace = int(win.get("grace", 0))
        if start <= term_index <= end:
            return True
        return end < term_index <= end + grace
    if win.get("type") == "season":
        seasons = win.get("seasons", [])
        mapping = {"春": 1, "夏": 2, "秋": 3, "冬": 4}
        season = (term_index - 1) // 6 + 1
        return any(mapping.get(s) == season for s in seasons)
    return True  # 未配置窗口视为随时可种


def sow(db: Session, player, plot_id: str, crop_id: str) -> dict:
    try:
        crop_uuid = uuid.UUID(crop_id)
    except ValueError:
        raise AppError("CROP_NOT_FOUND", "作物不存在", code=21005)
    crop = db.query(Crop).filter(Crop.id == crop_uuid, Crop.active.is_(True)).first()
    if not crop:
        raise AppError("CROP_NOT_FOUND", "作物不存在", code=21005)
    plot = db.query(Plot).filter(Plot.id == uuid.UUID(plot_id)).first()
    if not plot or plot.locked:
        raise AppError("PLOT_NOT_FOUND", "地块不存在或未解锁", code=21001)
    farm = db.query(Farm).filter(Farm.id == plot.farm_id).first()
    if farm.owner_id != player.id:
        raise AppError("PLOT_NOT_FOUND", "地块不存在", code=21001)
    existing = (
        db.query(CropInstance)
        .filter(CropInstance.plot_id == plot.id, CropInstance.harvested_at.is_(None))
        .first()
    )
    if existing:
        raise AppError("PLOT_OCCUPIED", "该地块已有作物", code=21002)

    term, _, _ = get_current_term(db)
    if not _check_sow_window(crop, term.term_index):
        raise AppError(
            "CROP_NOT_AVAILABLE", f"当前节气({term.name})不适合种植{crop.name}", code=21003
        )

    # 消耗种子:effect.type=seed 且 crop_id 匹配
    seed = None
    for it in db.query(Item).filter(Item.active.is_(True)).all():
        eff = it.effect or {}
        if eff.get("type") == "seed" and str(eff.get("crop_id", "")) == str(crop.id):
            seed = it
            break
    if seed is None:
        raise AppError("SEED_NOT_FOUND", f"{crop.name}没有对应的种子道具", code=21005)
    ui = (
        db.query(UserItem)
        .filter(UserItem.player_id == player.id, UserItem.item_id == seed.id)
        .first()
    )
    if not ui or ui.quantity < 1:
        raise AppError("NOT_ENOUGH_ITEM", "种子不足,请先到商店购买", code=21006)

    now = datetime.now(timezone.utc)
    ui.quantity -= 1
    ci = CropInstance(
        plot_id=plot.id,
        crop_id=crop.id,
        sowed_at=now,
        sowed_term_index=term.term_index,
        predicted_harvest_at=now + timedelta(seconds=crop.grow_seconds),
    )
    db.add(ci)
    db.add(ItemTransaction(player_id=player.id, item_id=seed.id, delta=-1, reason="sow", ref_id=ci.id))
    db.commit()
    return {
        "plot_id": str(plot.id),
        "crop_id": str(crop.id),
        "crop_name": crop.name,
        "sowed_term_index": term.term_index,
        "predicted_harvest_at": ci.predicted_harvest_at.isoformat(),
    }


def water(db: Session, player, plot_id: str) -> dict:
    ci = _get_active_crop(db, player, plot_id)
    ci.water_level = 100
    db.commit()
    return {"plot_id": plot_id, "water_level": 100}


def harvest(db: Session, player, plot_id: str) -> dict:
    ci = _get_active_crop(db, player, plot_id)
    crop = db.query(Crop).filter(Crop.id == ci.crop_id).first()
    plot = db.query(Plot).filter(Plot.id == ci.plot_id).first()
    view = crop_view(ci, crop)
    if view["stage"] < 3:
        raise AppError("CROP_NOT_MATURE", "作物尚未成熟", code=23001)
    yield_actual = int(round(crop.yield_base * (1 + 0.1 * (plot.soil_quality - 1))))
    now = datetime.now(timezone.utc)
    ci.harvested_at = now
    ci.yield_actual = yield_actual
    ci.term_bonus_applied = {
        "sowed_term": ci.sowed_term_index,
        "soil_quality": plot.soil_quality,
        "yield": yield_actual,
    }
    # 收成入仓(不直接结算金币):玩家到商店按当前季节价择机出售
    st = (
        db.query(CropStorage)
        .filter(CropStorage.player_id == player.id, CropStorage.crop_id == crop.id)
        .first()
    )
    if st:
        st.quantity += yield_actual
    else:
        db.add(
            CropStorage(
                player_id=player.id, crop_id=crop.id, quantity=yield_actual
            )
        )
    db.commit()
    return {
        "plot_id": plot_id,
        "crop_id": str(crop.id),
        "crop_name": crop.name,
        "yield": yield_actual,
        "storage_after": (st.quantity if st else yield_actual),
        "note": "已入收成仓,可在商店按当前季节价出售",
    }


def clear(db: Session, player, plot_id: str) -> dict:
    ci = _get_active_crop(db, player, plot_id)
    ci.harvested_at = datetime.now(timezone.utc)
    ci.yield_actual = 0
    db.commit()
    return {"plot_id": plot_id, "cleared": True}
