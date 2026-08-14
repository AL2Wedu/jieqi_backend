"""杂草系统:每用户隔离,每个节气内的随机时刻生长一次。

- 调度:每个节气内随机一个世界秒时刻(weed_scheduled_accum,玩家世界时间)
  - 到点触发:随机把若干地块标记为"附有杂草"(优先有作物的地块)
  - 新一次生长会先清除旧杂草(重新随机,杂草存活不超过一个节气)
- 效果:杂草地块上的植物生长速度 × weed.slow_factor(默认 0.5,慢一半)
- 配置走 game_config(管理后台可改):weed.enabled / weed.slow_factor / weed.max_plots
"""
import random

from sqlalchemy.orm import Session

from app.models import CropInstance, Farm, GameConfig, Plot, Player, TermConfig
from app.services import world_service

_KEYS = ("weed.enabled", "weed.slow_factor", "weed.max_plots")
_DEFAULTS = {
    "weed.enabled": True,
    "weed.slow_factor": 0.5,  # 杂草地块生长速度倍率
    "weed.max_plots": 3,  # 每次生长最多覆盖的地块数
}


def weed_config(db: Session) -> dict:
    rows = {
        c.key: c.value
        for c in db.query(GameConfig).filter(GameConfig.key.in_(_KEYS)).all()
    }
    cfg = dict(_DEFAULTS)
    for k, v in rows.items():
        if v is not None:
            cfg[k] = v
    cfg["weed.slow_factor"] = max(0.1, min(0.9, float(cfg["weed.slow_factor"])))
    cfg["weed.max_plots"] = max(1, int(cfg["weed.max_plots"]))
    return cfg


def save_weed_config(db: Session, data: dict) -> dict:
    for key in _KEYS:
        if key in data and data[key] is not None:
            row = db.query(GameConfig).filter(GameConfig.key == key).first()
            if row:
                row.value = data[key]
            else:
                db.add(GameConfig(key=key, value=data[key]))
    db.commit()
    return weed_config(db)


# ---------- 调度 ----------

def _term_span(db: Session, player: Player) -> tuple[float, float]:
    """玩家当前节气在世界时间上的 [起点, 终点)。"""
    term, cycle, _ = world_service.current_term(db, player)
    terms = (
        db.query(TermConfig).order_by(TermConfig.term_index).all()
    )
    total = sum(t.duration_seconds for t in terms)
    cycle_accum = cycle * total
    start = cycle_accum + sum(
        t.duration_seconds for t in terms if t.term_index < term.term_index
    )
    return start, start + term.duration_seconds


def schedule_next(db: Session, player: Player) -> None:
    """为玩家安排下一次杂草生长时刻(当前或下一节气内的随机世界秒)。"""
    accum = float(player.world_accum or 0.0)
    start, end = _term_span(db, player)
    # 本节气剩余世界秒不足 1/3 → 排到下一节气
    if end - accum < (end - start) / 3:
        target = end + random.uniform(0.0, end - start)
    else:
        target = accum + random.uniform(0.0, (end - accum))
    player.weed_scheduled_accum = target


def check_weed(db: Session, player: Player) -> list[dict]:
    """到点触发杂草生长;返回本次被杂草覆盖的地块列表(供 WS 推送)。"""
    cfg = weed_config(db)
    if not cfg["weed.enabled"]:
        return []
    accum = float(player.world_accum or 0.0)
    if player.weed_scheduled_accum is None:
        schedule_next(db, player)
        db.commit()
        return []
    if accum < float(player.weed_scheduled_accum):
        return []
    targets = fire_weed(db, player, cfg)
    schedule_next(db, player)
    db.commit()
    return targets


# ---------- 触发 ----------

def _candidate_plots(db: Session, player: Player, cfg: dict) -> list[Plot]:
    farm = db.query(Farm).filter(Farm.owner_id == player.id).first()
    if not farm:
        return []
    plots = db.query(Plot).filter(Plot.farm_id == farm.id, Plot.locked.is_(False)).all()
    if not plots:
        return []
    active_ids = {
        ci.plot_id
        for ci in db.query(CropInstance)
        .filter(
            CropInstance.plot_id.in_([p.id for p in plots]),
            CropInstance.harvested_at.is_(None),
            CropInstance.destroyed_at.is_(None),
        )
        .all()
    }
    with_crop = [p for p in plots if p.id in active_ids]
    empty = [p for p in plots if p.id not in active_ids]
    random.shuffle(with_crop)
    random.shuffle(empty)
    n = min(int(cfg["weed.max_plots"]), len(plots))
    return (with_crop + empty)[:n]


def fire_weed(db: Session, player: Player, cfg: dict | None = None) -> list[dict]:
    """杂草生长:清除旧杂草 → 随机覆盖若干地块(优先有作物的)。返回 targets。"""
    cfg = cfg or weed_config(db)
    farm = db.query(Farm).filter(Farm.owner_id == player.id).first()
    if not farm:
        return []
    # 清除旧杂草(新一次生长重新随机,杂草存活不超过一个节气)
    db.query(Plot).filter(Plot.farm_id == farm.id).update({Plot.weeded: False})
    chosen = _candidate_plots(db, player, cfg)
    targets = []
    for p in chosen:
        p.weeded = True
        targets.append({"plot_id": str(p.id), "idx": p.idx})
    db.flush()
    return targets


def clear_weeds(db: Session, player: Player) -> dict:
    """调试/管理:清除该玩家全部杂草。"""
    farm = db.query(Farm).filter(Farm.owner_id == player.id).first()
    n = 0
    if farm:
        n = (
            db.query(Plot)
            .filter(Plot.farm_id == farm.id, Plot.weeded.is_(True))
            .update({Plot.weeded: False})
        )
        db.commit()
    return {"cleared": n}


def weeded_plots(db: Session, player: Player) -> list[Plot]:
    farm = db.query(Farm).filter(Farm.owner_id == player.id).first()
    if not farm:
        return []
    return db.query(Plot).filter(Plot.farm_id == farm.id, Plot.weeded.is_(True)).all()
