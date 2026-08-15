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
from app.services import world_service

_SEASON_TERMS = {1: (1, 6), 2: (7, 12), 3: (13, 18), 4: (19, 24)}  # 春/夏/秋/冬
_SEASON_NAMES = {1: "spring", 2: "summer", 3: "autumn", 4: "winter"}

FARM_COLS = 4  # 田地格子:横 4
FARM_ROWS = 5  # 竖 5
# 格子编号规则:idx 1-20,按行优先 —— idx = (row-1)*4 + col (row∈1..5, col∈1..4)

_WATER_DECAY_PER_TERM = 10  # 水分随世界时间衰减:每节气 -10
_WILTED_YIELD_FACTOR = 0.5  # 枯萎作物收割产量系数(冻死后减产一半)


def season_name(term_index: int) -> str:
    """节气序号 → 季节名(spring/summer/autumn/winter)。"""
    return _SEASON_NAMES.get((term_index - 1) // 6 + 1, "spring")


def _avg_term_duration(db: Session) -> float:
    from app.models import TermConfig

    rows = db.query(TermConfig).all()
    if not rows:
        return 300.0
    return sum(t.duration_seconds for t in rows) / len(rows)


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


def crop_view(
    ci: CropInstance,
    crop: Crop | None,
    weeded: bool = False,
    slow_factor: float = 1.0,
) -> dict:
    now = datetime.now(timezone.utc)
    settings = (crop.settings if crop else {}) or {}
    grow_base = crop.grow_seconds if crop else 0
    # 有效生长时长:加速季节播种时已按倍率缩短(播种时快照)
    grow = float((ci.extra or {}).get("grow_seconds_eff") or grow_base) or 1.0
    # 杂草减速:该地块附有杂草 → 生长速度 × slow_factor(默认 0.5,慢一半)
    rate = slow_factor if weeded else 1.0
    sowed = ensure_aware(ci.sowed_at)
    base = (now - sowed).total_seconds() * rate / grow * 100 if grow else 0.0
    boost = float((ci.extra or {}).get("boost_pct", 0))
    progress = min(100.0, base + boost)

    # 水分衰减(基准 = 存储 water_level,自上次浇水/播种起每节气 -10)+ 生长停滞(跌破需水红线冻结)
    term_dur = float((ci.extra or {}).get("term_dur") or 300.0)
    watered_raw = (ci.extra or {}).get("watered_at")
    water_start = (
        ensure_aware(datetime.fromisoformat(watered_raw)) if watered_raw else sowed
    )
    base_water = max(0, ci.water_level or 0)
    elapsed_terms = max(0.0, (now - water_start).total_seconds()) / term_dur
    water_eff = int(max(0, round(base_water - elapsed_terms * _WATER_DECAY_PER_TERM)))
    wmin = int(((settings.get("water_need") or {}).get("min", 0)) or 0)
    wmin = min(wmin, 100)
    if wmin > 0 and base_water > wmin:
        # 红线时刻 = 水分从基准衰减到 min 的时刻;此后进度冻结在那一刻
        stall_at = water_start + timedelta(
            seconds=term_dur * ((base_water - wmin) / _WATER_DECAY_PER_TERM)
        )
        if now > stall_at:
            stalled = (stall_at - sowed).total_seconds() * rate / grow * 100
            progress = min(progress, stalled)

    # 枯萎/冻死:进度冻结在枯萎时刻,不再生长(覆盖水分停滞,前端据此显示"冻死"而非移除)
    wilted = ci.wilted_at is not None
    if wilted:
        frozen = (ci.extra or {}).get("wilted_progress")
        if isinstance(frozen, (int, float)):
            progress = min(100.0, float(frozen))

    stage = 3 if progress >= 100 else (2 if progress >= 50 else 1)
    status = "wilted" if wilted else ("mature" if stage >= 3 else "growing")
    return {
        "crop_id": str(ci.crop_id),
        "name": crop.name if crop else "?",
        "art": (crop.art if crop else {}) or {},
        "settings": settings,  # 植物高级设定(客户端展示需水/枯萎季节等)
        "stage": stage,
        "status": status,  # growing 生长中 / mature 成熟 / wilted 枯萎冻死(待铲除或收割)
        "growth_progress": int(progress),
        "water_level": water_eff,
        "water_need": wmin,
        "predicted_harvest_at": (
            ci.predicted_harvest_at.isoformat() if ci.predicted_harvest_at else None
        ),
    }


def check_wither(db: Session, player, now: datetime | None = None) -> list[dict]:
    """枯萎判定:玩家当前季节进入作物的枯萎季节 → 未收获作物标记为"枯萎/冻死"(幂等落库)。

    **不再直接销毁**:枯萎作物仍占用地块,前端通过 crop.status="wilted" 展示"植物冻死了",
    玩家可 `clear` 铲除或 `harvest` 收割(产量减半,入仓为劣质收成,售价大打折扣)。

    返回本次新枯萎的事件列表(供 WS 推送 / 状态响应提示)。
    """
    now = now or datetime.now(timezone.utc)
    farm = _get_farm(db, player)
    plot_ids = [p.id for p in db.query(Plot).filter(Plot.farm_id == farm.id).all()]
    if not plot_ids:
        return []
    season = season_name(world_service.current_term(db, player)[0].term_index)
    rows = (
        db.query(CropInstance, Crop)
        .join(Crop, Crop.id == CropInstance.crop_id)
        .filter(
            CropInstance.plot_id.in_(plot_ids),
            CropInstance.harvested_at.is_(None),
            CropInstance.destroyed_at.is_(None),
        )
        .all()
    )
    events = []
    for ci, crop in rows:
        settings = (crop.settings or {}) or {}
        if season in (settings.get("wither_seasons") or []):
            if ci.wilted_at is None:  # 幂等:只标记一次
                # 冻结当前生长进度(枯萎作物不再生长)
                view = crop_view(ci, crop)
                extra = dict(ci.extra or {})
                extra["wilted_progress"] = view["growth_progress"]
                ci.extra = extra
                ci.wilted_at = now
                plot = db.query(Plot).filter(Plot.id == ci.plot_id).first()
                events.append(
                    {
                        "plot_id": str(ci.plot_id),
                        "idx": plot.idx if plot else None,
                        "crop_name": crop.name,
                        "status": "wilted",
                    }
                )
    if events:
        db.commit()
    return events


def get_farm_state(db: Session, player) -> dict:
    from app.services import weed_service

    farm = _get_farm(db, player)
    plots = db.query(Plot).filter(Plot.farm_id == farm.id).order_by(Plot.idx).all()
    # 枯萎判定(当前季节 ∈ 作物枯萎季节 → 销毁),再取活动作物
    wither_events = check_wither(db, player)
    # 杂草判定:到点生长(随机地块附杂草)
    weed_events = weed_service.check_weed(db, player)
    wcfg = weed_service.weed_config(db)
    slow_factor = float(wcfg["weed.slow_factor"])
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
    plot_list = []
    for p in plots:
        ci = crops.get(p.id)
        plot_list.append(
            {
                "plot_id": str(p.id),
                "idx": p.idx,
                "soil_quality": p.soil_quality,
                "locked": p.locked,
                "weeded": bool(p.weeded),  # 附有杂草 → 该地块作物生长减速
                "crop": crop_view(
                    ci,
                    crop_defs.get(ci.crop_id) if ci else None,
                    weeded=bool(p.weeded),
                    slow_factor=slow_factor,
                )
                if ci
                else None,
            }
        )
    return {
        "farm": {
            "farm_id": str(farm.id),
            "name": farm.name,
            "plot_count": farm.plot_count,
            "grid": {"cols": FARM_COLS, "rows": FARM_ROWS},  # 4×5,idx 行优先
        },
        "current_term": world_service.current_calendar(db, player),
        "wither_events": wither_events,  # 本次读取时枯萎的作物(客户端弹提示)
        "weed_events": weed_events,  # 本次读取时新长的杂草地块(客户端播动画/提示)
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

    term, _, _ = world_service.current_term(db, player)
    if not _check_sow_window(crop, term.term_index):
        raise AppError(
            "CROP_NOT_AVAILABLE", f"当前节气({term.name})不适合种植{crop.name}", code=21003
        )
    # 解锁校验:经验或等级达到其一即可(两者均为 0 = 无门槛)
    exp_ok = crop.unlock_exp <= 0 or player.exp >= crop.unlock_exp
    lvl_ok = crop.unlock_level <= 0 or player.level >= crop.unlock_level
    if not (exp_ok or lvl_ok):
        raise AppError(
            "CROP_LOCKED",
            f"{crop.name}需等级 {crop.unlock_level} 或经验 {crop.unlock_exp} 解锁",
            code=21008,
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
    # 播种 = 翻地整地:清除该地块的杂草(田里草不除会累积,播种时一并处理)
    plot.weeded = False
    # 加速季节:在该季节播种 → 生长速度 × 倍率(有效生长时长 = 基础 / 倍率)
    settings = (crop.settings or {}) or {}
    fgs = settings.get("fast_growth_seasons") or {}
    season = season_name(term.term_index)
    factor = float(fgs.get(season, 1.0) or 1.0)
    grow_eff = crop.grow_seconds
    extra = {"term_dur": _avg_term_duration(db)}
    if factor > 1.0:
        grow_eff = max(60, int(crop.grow_seconds / factor))
        extra["grow_seconds_eff"] = grow_eff
        extra["boost_reason"] = f"fast_season:{season}:x{factor}"
    ci = CropInstance(
        plot_id=plot.id,
        crop_id=crop.id,
        sowed_at=now,
        sowed_term_index=term.term_index,
        predicted_harvest_at=now + timedelta(seconds=grow_eff),
        extra=extra,
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
        "grow_seconds_eff": grow_eff,
        "season_boost": factor if factor > 1.0 else None,
    }


def water(db: Session, player, plot_id: str) -> dict:
    ci = _get_active_crop(db, player, plot_id)
    if ci.wilted_at is not None:
        raise AppError("CROP_WILTED", "作物已枯萎冻死,无法浇水,请铲除或收割", code=21009)
    ci.water_level = 100
    extra = dict(ci.extra or {})
    extra["watered_at"] = datetime.now(timezone.utc).isoformat()  # 水分衰减从此刻重新计时
    ci.extra = extra
    db.commit()
    return {"plot_id": plot_id, "water_level": 100}


def harvest(db: Session, player, plot_id: str) -> dict:
    ci = _get_active_crop(db, player, plot_id)
    crop = db.query(Crop).filter(Crop.id == ci.crop_id).first()
    plot = db.query(Plot).filter(Plot.id == ci.plot_id).first()
    view = crop_view(ci, crop)
    is_wilted = ci.wilted_at is not None
    # 枯萎/冻死作物任何时候都能收割(抢救性收割);正常作物须成熟
    if not is_wilted and view["stage"] < 3:
        raise AppError("CROP_NOT_MATURE", "作物尚未成熟", code=23001)
    settings = (crop.settings or {}) or {}
    # 产量 = 基础 × (1 + 0.1×(肥力-1));土壤肥力低于需肥力 → 减产 ×(soil/need)
    y = crop.yield_base * (1 + 0.1 * (plot.soil_quality - 1))
    fert_need = max(1, int(settings.get("fertility_need") or 1))
    if plot.soil_quality < fert_need:
        y *= plot.soil_quality / fert_need
    if is_wilted:
        # 枯萎/冻死作物收割:产量减半,入仓为劣质收成(商店售价大打折扣)
        y *= _WILTED_YIELD_FACTOR
    yield_actual = int(round(max(1.0, y)))
    now = datetime.now(timezone.utc)
    ci.harvested_at = now
    ci.yield_actual = yield_actual
    ci.term_bonus_applied = {
        "sowed_term": ci.sowed_term_index,
        "soil_quality": plot.soil_quality,
        "fertility_need": fert_need,
        "yield": yield_actual,
        "wilted": is_wilted,
    }
    # 收成入仓(不直接结算金币):正常/枯萎分别入仓,枯萎劣质收成售价打折
    st = (
        db.query(CropStorage)
        .filter(CropStorage.player_id == player.id, CropStorage.crop_id == crop.id)
        .first()
    )
    if st:
        if is_wilted:
            st.wilted_quantity += yield_actual
        else:
            st.quantity += yield_actual
        storage_after = st.quantity + st.wilted_quantity
    else:
        st = CropStorage(
            player_id=player.id,
            crop_id=crop.id,
            quantity=0 if is_wilted else yield_actual,
            wilted_quantity=yield_actual if is_wilted else 0,
        )
        db.add(st)
        storage_after = yield_actual
    db.commit()
    # 收获给经验(每株 +2):核心循环正反馈,附带自动升级
    from app.services.goal_service import apply_exp

    exp_info = apply_exp(db, player, yield_actual * 2)
    db.commit()
    note = (
        "已入收成仓(枯萎劣质收成,售价大打折扣),可在商店出售"
        if is_wilted
        else "已入收成仓,可在商店按当前季节价出售"
    )
    return {
        "plot_id": plot_id,
        "crop_id": str(crop.id),
        "crop_name": crop.name,
        "wilted": is_wilted,
        "yield": yield_actual,
        "storage_after": storage_after,
        "exp_gained": exp_info["exp_gained"],
        "level": exp_info["level_after"],
        "leveled_up": exp_info["level_after"] > exp_info["level_before"],
        "note": note,
    }


def clear(db: Session, player, plot_id: str) -> dict:
    ci = _get_active_crop(db, player, plot_id)
    was_wilted = ci.wilted_at is not None
    ci.harvested_at = datetime.now(timezone.utc)
    ci.yield_actual = 0
    db.commit()
    return {"plot_id": plot_id, "cleared": True, "wilted": was_wilted}
