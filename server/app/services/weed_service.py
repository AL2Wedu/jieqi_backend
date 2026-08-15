"""杂草系统:每用户隔离,每个节气内的随机时刻生长一次。

- 调度:每个节气内随机一个世界秒时刻(weed_scheduled_accum,玩家世界时间)
  - 到点触发:在未覆盖地块中新增若干"附有杂草"标记(优先有作物的地块)
  - 杂草**累积**:新一次生长不清除旧杂草(田野里草不除会一直在),直到玩家
    主动清除或重新播种(翻地)才消失;全农场有总量上限 weed.max_total 防止荒芜
- 效果:杂草地块上的植物生长速度 × weed.slow_factor(默认 0.5,慢一半)
- 生态:冬天杂草照常生长(越冬杂草真实存在,如麦田冬前除草),与"冬季无虫害"互补
- 配置走 game_config(管理后台可改):weed.enabled / weed.slow_factor / weed.max_plots / weed.max_total
"""
import random
import uuid

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import CropInstance, Farm, GameConfig, Plot, Player, TermConfig
from app.services import world_service

# 密码学安全随机源(调度时刻/地块选择统一使用,防预测)
_rng = random.SystemRandom()

_KEYS = ("weed.enabled", "weed.slow_factor", "weed.max_plots", "weed.max_total")
_DEFAULTS = {
    "weed.enabled": True,
    "weed.slow_factor": 0.5,  # 杂草地块生长速度倍率
    "weed.max_plots": 3,  # 每次生长新增覆盖的地块数(最多)
    "weed.max_total": 12,  # 全农场杂草总量上限(20 格的 60%,防整田荒芜)
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
    cfg["weed.max_total"] = max(1, min(20, int(cfg["weed.max_total"])))  # 上限不超 20 格
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
        target = end + _rng.uniform(0.0, end - start)
    else:
        target = accum + _rng.uniform(0.0, (end - accum))
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
    """候选新增地块:未覆盖杂草的格子(优先有作物的),且受总量上限约束。"""
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
    # 杂草累积:已达总量上限则不再新增;只在未覆盖地块中选
    quota = max(0, int(cfg["weed.max_total"]) - sum(1 for p in plots if p.weeded))
    if quota <= 0:
        return []
    with_crop = [p for p in plots if p.id in active_ids and not p.weeded]
    empty = [p for p in plots if p.id not in active_ids and not p.weeded]
    _rng.shuffle(with_crop)
    _rng.shuffle(empty)
    n = min(int(cfg["weed.max_plots"]), quota, len(plots))
    return (with_crop + empty)[:n]


def fire_weed(db: Session, player: Player, cfg: dict | None = None) -> list[dict]:
    """杂草生长:新增覆盖若干未长草地块(不清除旧杂草,杂草累积)。返回 targets。"""
    cfg = cfg or weed_config(db)
    farm = db.query(Farm).filter(Farm.owner_id == player.id).first()
    if not farm:
        return []
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


def clear_weed(db: Session, player: Player, plot_id: str) -> dict:
    """清除单个地块的杂草(玩家操作,只清所选格)。

    - 地块不存在 / 不属于我 → 21001 PLOT_NOT_FOUND
    - 该格原本无杂草 → 幂等返回 cleared=False(不报错)
    """
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
    was_weeded = bool(plot.weeded)
    if was_weeded:
        plot.weeded = False
        db.commit()
    return {"plot_id": plot_id, "idx": plot.idx, "cleared": was_weeded}


def weeded_plots(db: Session, player: Player) -> list[Plot]:
    farm = db.query(Farm).filter(Farm.owner_id == player.id).first()
    if not farm:
        return []
    return db.query(Plot).filter(Plot.farm_id == farm.id, Plot.weeded.is_(True)).all()
