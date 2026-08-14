"""虫害系统:每用户隔离调度 + 大虫害(音游对抗) + 小虫害(定时寄生)。

调度:每用户独立维护 next_pest_at,平均每 `window_terms` 个节气触发
`events_per_window` 次(默认 2 节气 3 次),间隔随机化(0.5~1.5×均值)。
- 大虫害:WS 广播含音游时长 → 前端游玩后提交成绩 → 校验实际耗时 ≥ 时长×min_elapsed_factor
  (防作弊:明显快于时长直接拒绝) → 按 pass_ratio 判定:达标发奖励(金币+随机道具),
  不达标按 miss//2 个随机地块寄生小虫害。
- 小虫害:WS 广播 1~5 个随机地块(含坐标/计时)→ 每块独立倒计时(按生长阶段),
  到点摧毁作物;玩家可驱赶(前端完成交互,后端确认即消除)。
所有配置走 game_config(控制台可改):pest.*
"""
import random
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.utils import ensure_aware
from app.models import (
    Crop,
    CropInstance,
    Farm,
    GameConfig,
    Item,
    PestEvent,
    PestTarget,
    Player,
    Plot,
    TermConfig,
)
from app.services.farm_service import crop_view
from app.services.goal_service import grant_reward

_KEYS = (
    "pest.enabled",
    "pest.events_per_window",
    "pest.window_terms",
    "pest.big_ratio",
    "pest.big_duration_seconds",
    "pest.stage_wait",
    "pest.min_elapsed_factor",
    "pest.pass_ratio",
    "pest.reward_coins",
)
_DEFAULTS = {
    "pest.enabled": True,
    "pest.events_per_window": 3,
    "pest.window_terms": 2,
    "pest.big_ratio": 0.3,
    "pest.big_duration_seconds": 30,
    "pest.stage_wait": {1: 120, 2: 90, 3: 60},  # 苗期/生长期/成熟 各自摧毁倒计时(秒)
    "pest.min_elapsed_factor": 0.6,  # 大虫害成绩提交的最短耗时 = 时长 × 该系数
    "pest.pass_ratio": 0.6,  # score/max_score ≥ 该值 → 奖励
    "pest.reward_coins": 20,
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def pest_config(db: Session) -> dict:
    rows = {
        c.key: c.value
        for c in db.query(GameConfig).filter(GameConfig.key.in_(_KEYS)).all()
    }
    cfg = dict(_DEFAULTS)
    for k, v in rows.items():
        if v is not None:
            cfg[k] = v
    # JSON 往返会把数字键变字符串:归一化为 int
    waits = cfg["pest.stage_wait"]
    if isinstance(waits, dict):
        cfg["pest.stage_wait"] = {int(k): int(v) for k, v in waits.items() if str(k).isdigit()}
    return cfg


def save_pest_config(db: Session, data: dict) -> dict:
    for key in _KEYS:
        if key in data and data[key] is not None:
            row = db.query(GameConfig).filter(GameConfig.key == key).first()
            if row:
                row.value = data[key]
            else:
                db.add(GameConfig(key=key, value=data[key]))
    db.commit()
    return pest_config(db)


# ---------- 调度 ----------

def _interval_seconds(db: Session, cfg: dict) -> float:
    terms = db.query(TermConfig).all()
    avg_dur = sum(t.duration_seconds for t in terms) / len(terms) if terms else 300.0
    window = int(cfg["pest.window_terms"]) * avg_dur
    per = max(1, int(cfg["pest.events_per_window"]))
    mean = window / per
    return mean * random.uniform(0.5, 1.5)


def schedule_next(db: Session, player: Player, now: datetime | None = None) -> None:
    now = now or _utcnow()
    cfg = pest_config(db)
    player.next_pest_at = now + timedelta(seconds=_interval_seconds(db, cfg))


def is_due(db: Session, player: Player, now: datetime | None = None) -> bool:
    now = now or _utcnow()
    if player.next_pest_at is None:
        return True  # 首连:立即安排一次(也即初始化)
    return now >= ensure_aware(player.next_pest_at)


def has_active_pest(db: Session, player: Player) -> bool:
    if (
        db.query(PestEvent)
        .filter(PestEvent.player_id == player.id, PestEvent.status == 0)
        .first()
    ):
        return True
    return (
        db.query(PestTarget)
        .filter(PestTarget.player_id == player.id, PestTarget.status == 0)
        .first()
        is not None
    )


# ---------- 触发 ----------

def _active_plots(db: Session, player: Player) -> list[tuple[Plot, CropInstance, Crop]]:
    return (
        db.query(Plot, CropInstance, Crop)
        .join(Farm, Plot.farm_id == Farm.id)
        .filter(Farm.owner_id == player.id)
        .join(CropInstance, CropInstance.plot_id == Plot.id)
        .join(Crop, Crop.id == CropInstance.crop_id)
        .filter(
            CropInstance.harvested_at.is_(None),
            CropInstance.destroyed_at.is_(None),
        )
        .all()
    )


def _spawn_small(db: Session, player: Player, count: int, now: datetime | None = None) -> dict:
    """生成小虫害寄生目标(最多 count 个随机地块),每块独立计时。返回广播 payload。"""
    now = now or _utcnow()
    cfg = pest_config(db)
    plots = _active_plots(db, player)
    if not plots:
        raise AppError("PEST_NO_TARGET", "没有可寄生的作物", code=28004)
    n = min(count, len(plots))
    chosen = random.sample(plots, n)
    ev = PestEvent(player_id=player.id, type="small", status=0, broadcast_at=now)
    db.add(ev)
    db.flush()
    waits = cfg["pest.stage_wait"] or {}
    # 键已归一化为 int;兼容手工直写 DB 的字符串键
    waits = {int(k): v for k, v in waits.items() if str(k).isdigit()}
    targets = []
    for plot, ci, crop in chosen:
        stage = crop_view(ci, crop)["stage"]
        wait = int(waits.get(stage, 60) or 60)
        ready = now + timedelta(seconds=wait)
        db.add(
            PestTarget(
                pest_id=ev.id,
                player_id=player.id,
                plot_id=plot.id,
                crop_instance_id=ci.id,
                ready_at=ready,
                status=0,
            )
        )
        targets.append(
            {
                "pest_id": str(ev.id),
                "plot_id": str(plot.id),
                "idx": plot.idx,
                "crop": crop.name,
                "stage": stage,
                "wait_seconds": wait,
                "ready_at": ready.isoformat(),
            }
        )
    return {"pest_id": str(ev.id), "type": "small", "targets": targets}


def fire_pest(db: Session, player: Player, forced_type: str | None = None) -> dict:
    """触发一次虫害(每用户隔离);返回 WS 广播负载。forced_type: big / small。"""
    cfg = pest_config(db)
    if not cfg["pest.enabled"]:
        raise AppError("PEST_DISABLED", "虫害系统未启用", code=28002)
    if has_active_pest(db, player):
        raise AppError("PEST_BUSY", "已有进行中的虫害", code=28003)
    ptype = forced_type or (
        "big" if random.random() < float(cfg["pest.big_ratio"]) else "small"
    )
    now = _utcnow()
    if ptype == "big":
        ev = PestEvent(
            player_id=player.id,
            type="big",
            status=0,
            broadcast_at=now,
            duration_seconds=int(cfg["pest.big_duration_seconds"]),
        )
        db.add(ev)
        db.flush()
        payload = {
            "pest_id": str(ev.id),
            "type": "big",
            "duration_seconds": ev.duration_seconds,
        }
    else:
        payload = _spawn_small(db, player, count=random.randint(1, 5), now=now)
    schedule_next(db, player, now)
    db.commit()
    return {
        "type": "pest_big" if ptype == "big" else "pest_small",
        "payload": payload,
        "ts": int(now.timestamp()),
    }


# ---------- 大虫害:成绩提交(含防作弊) ----------

def submit_big_result(
    db: Session, player: Player, pest_id: str, score: int, max_score: int, miss_count: int
) -> dict:
    try:
        pid = uuid.UUID(pest_id)
    except ValueError:
        raise AppError("PEST_NOT_FOUND", "虫害事件不存在", code=28005)
    ev = (
        db.query(PestEvent)
        .filter(
            PestEvent.id == pid,
            PestEvent.player_id == player.id,
            PestEvent.type == "big",
            PestEvent.status == 0,
        )
        .first()
    )
    if not ev:
        raise AppError("PEST_NOT_FOUND", "虫害事件不存在", code=28005)
    now = _utcnow()
    cfg = pest_config(db)
    elapsed = (now - ensure_aware(ev.broadcast_at)).total_seconds()
    min_elapsed = int(ev.duration_seconds or 0) * float(cfg["pest.min_elapsed_factor"])
    if elapsed < min_elapsed:
        raise AppError(
            "PEST_RESULT_TOO_FAST",
            f"成绩提交过早(广播后需至少 {int(min_elapsed)} 秒)",
            code=28006,
        )
    ev.score = score
    ev.max_score = max_score
    ev.miss_count = miss_count
    ev.result_at = now
    ratio = (score / max_score) if max_score and max_score > 0 else 0.0
    if ratio >= float(cfg["pest.pass_ratio"]):
        # 奖励:金币 + 1 个随机道具(1~3 个)
        pool = (
            db.query(Item)
            .filter(Item.buy_price.isnot(None), Item.buy_price > 0)
            .all()
        )
        reward = {"coins": int(cfg["pest.reward_coins"]), "exp": 5}
        if pool:
            gift = random.choice(pool)
            reward["items"] = [{"code": gift.code, "quantity": random.randint(1, 3)}]
        granted = grant_reward(
            db, player, reward, reason=f"pest_big:{ev.id.hex[:8]}"
        )
        ev.reward = granted
        ev.status = 1
        db.commit()
        return {
            "pest_id": str(ev.id),
            "passed": True,
            "score": score,
            "max_score": max_score,
            "reward": granted,
        }
    # 惩罚:类似小虫灾,寄生在 miss//2 个随机田块上(至少 1 个)
    payload = None
    try:
        payload = _spawn_small(db, player, count=max(1, miss_count // 2), now=now)
    except AppError:
        payload = None
    ev.penalty = {"targets": len(payload["targets"]) if payload else 0}
    ev.status = 1
    db.commit()
    return {
        "pest_id": str(ev.id),
        "passed": False,
        "score": score,
        "max_score": max_score,
        "miss_count": miss_count,
        "penalty": ev.penalty,
        "pest_small": payload,  # 前端按 pest_small 事件处理惩罚寄生
    }


# ---------- 小虫害:驱赶 / 到点摧毁 ----------

def drive_away(db: Session, player: Player, pest_id: str, plot_id: str) -> dict:
    try:
        pid = uuid.UUID(pest_id)
        plid = uuid.UUID(plot_id)
    except ValueError:
        raise AppError("PEST_TARGET_NOT_FOUND", "寄生目标不存在", code=28007)
    t = (
        db.query(PestTarget)
        .filter(
            PestTarget.pest_id == pid,
            PestTarget.player_id == player.id,
            PestTarget.plot_id == plid,
            PestTarget.status == 0,
        )
        .first()
    )
    if not t:
        raise AppError("PEST_TARGET_NOT_FOUND", "寄生目标不存在", code=28007)
    now = _utcnow()
    if ensure_aware(t.ready_at) <= now:
        # 已到点:直接按摧毁处理(虫已得手)
        destroyed = _destroy_target(db, t, now)
        _close_small_event(db, player, t.pest_id, destroyed=True)
        db.commit()
        return {
            "pest_id": str(t.pest_id),
            "plot_id": str(t.plot_id),
            "status": 2,
            "destroyed": True,
        }
    t.status = 1
    _close_small_event(db, player, t.pest_id, destroyed=False)
    db.commit()
    return {
        "pest_id": str(t.pest_id),
        "plot_id": str(t.plot_id),
        "status": 1,
        "destroyed": False,
    }


def _destroy_target(db: Session, t: PestTarget, now: datetime) -> bool:
    ci = (
        db.query(CropInstance)
        .filter(
            CropInstance.id == t.crop_instance_id,
            CropInstance.harvested_at.is_(None),
            CropInstance.destroyed_at.is_(None),
        )
        .first()
    )
    if ci:
        ci.destroyed_at = now
        return True
    return False


def _close_small_event(db: Session, player: Player, pest_id, destroyed: bool) -> None:
    """该小虫害事件若无其他活动目标 → 事件结束。"""
    if (
        db.query(PestTarget)
        .filter(PestTarget.pest_id == pest_id, PestTarget.status == 0)
        .first()
    ):
        return
    ev = (
        db.query(PestEvent)
        .filter(
            PestEvent.id == pest_id,
            PestEvent.player_id == player.id,
            PestEvent.status == 0,
        )
        .first()
    )
    if ev:
        ev.status = 2 if destroyed else 1


def check_expiry(db: Session, player: Player) -> list[dict]:
    """到点摧毁:虫子在 ready_at 到达后直接摧毁地块作物并消失。返回被摧毁列表(供 WS 推送)。"""
    now = _utcnow()
    overdue = (
        db.query(PestTarget)
        .filter(
            PestTarget.player_id == player.id,
            PestTarget.status == 0,
            PestTarget.ready_at <= now,
        )
        .all()
    )
    destroyed = []
    for t in overdue:
        _destroy_target(db, t, now)
        t.status = 2
        destroyed.append(
            {
                "pest_id": str(t.pest_id),
                "plot_id": str(t.plot_id),
            }
        )
    for ev in (
        db.query(PestEvent)
        .filter(PestEvent.player_id == player.id, PestEvent.status == 0)
        .all()
    ):
        if (
            db.query(PestTarget)
            .filter(PestTarget.pest_id == ev.id, PestTarget.status == 0)
            .first()
            is None
        ):
            ev.status = 2
    if destroyed:
        db.commit()
    return destroyed


# ---------- 状态 / 管理 ----------

def player_state(db: Session, player: Player) -> dict:
    now = _utcnow()
    cfg = pest_config(db)
    big = (
        db.query(PestEvent)
        .filter(
            PestEvent.player_id == player.id,
            PestEvent.type == "big",
            PestEvent.status == 0,
        )
        .first()
    )
    targets = (
        db.query(PestTarget)
        .filter(PestTarget.player_id == player.id, PestTarget.status == 0)
        .all()
    )
    plot_idx = {str(p.id): p.idx for p in db.query(Plot).filter(Plot.id.in_([t.plot_id for t in targets] or [uuid.UUID(int=0)])).all()}
    return {
        "enabled": cfg["pest.enabled"],
        "next_pest_at": player.next_pest_at.isoformat() if player.next_pest_at else None,
        "active_big": {
            "pest_id": str(big.id),
            "duration_seconds": big.duration_seconds,
            "elapsed_seconds": max(0, int((now - ensure_aware(big.broadcast_at)).total_seconds())),
        }
        if big
        else None,
        "active_small": [
            {
                "pest_id": str(t.pest_id),
                "plot_id": str(t.plot_id),
                "idx": plot_idx.get(str(t.plot_id)),
                "ready_at": t.ready_at.isoformat(),
                "remaining_sec": max(0, int((ensure_aware(t.ready_at) - now).total_seconds())),
            }
            for t in targets
        ],
    }


def list_events(db: Session, page: int, page_size: int) -> dict:
    from app.models import User

    total = db.query(PestEvent).count()
    rows = (
        db.query(PestEvent, User.name)
        .join(Player, Player.id == PestEvent.player_id)
        .join(User, User.id == Player.user_id)
        .order_by(PestEvent.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    items = [
        {
            "pest_id": str(ev.id),
            "player": name,
            "type": ev.type,
            "status": ev.status,
            "score": ev.score,
            "max_score": ev.max_score,
            "miss_count": ev.miss_count,
            "reward": ev.reward,
            "penalty": ev.penalty,
            "broadcast_at": ev.broadcast_at.isoformat(),
        }
        for ev, name in rows
    ]
    return {"items": items, "page": page, "page_size": page_size, "total": total}
