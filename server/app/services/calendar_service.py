"""节气轮转时钟:当前节气由公式计算,无日历表。

elapsed = (now - epoch) × time_scale   (暂停时冻结)
term    = 落在哪个节气时长桶里
cycle   = 完整轮次数
"""
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.utils import ensure_aware
from app.models import GameClock, TermConfig


def get_clock(db: Session) -> GameClock:
    clock = db.query(GameClock).first()
    if clock is None:
        clock = GameClock(id=1, epoch=datetime.now(timezone.utc), time_scale=1.0)
        db.add(clock)
        db.commit()
        db.refresh(clock)
    return clock


def _terms(db: Session) -> list[TermConfig]:
    return db.query(TermConfig).order_by(TermConfig.term_index).all()


def get_current_term(db: Session) -> tuple[TermConfig, int, int]:
    """返回 (当前节气配置, 轮次 cycle, 本轮剩余秒)。"""
    clock = get_clock(db)
    terms = _terms(db)
    if not terms:
        raise RuntimeError("term_config 未初始化,请先执行 seed")
    total = sum(t.duration_seconds for t in terms)
    now = datetime.now(timezone.utc)
    effective = clock.paused_at if clock.paused_at is not None else now
    epoch = ensure_aware(clock.epoch)
    paused = ensure_aware(clock.paused_at)
    if paused is not None:
        effective = paused
    elapsed = max(0.0, (effective - epoch).total_seconds() * float(clock.time_scale))
    cycle = int(elapsed // total)
    rem = elapsed % total
    acc = 0.0
    for t in terms:
        if rem < acc + t.duration_seconds:
            return t, cycle, int(acc + t.duration_seconds - rem)
        acc += t.duration_seconds
    last = terms[-1]
    return last, cycle, 0


def current_calendar(db: Session) -> dict:
    term, cycle, remaining = get_current_term(db)
    return {
        "term_index": term.term_index,
        "name": term.name,
        "cycle": cycle,
        "remaining_sec": remaining,
    }


def next_switch_in(db: Session) -> int:
    _, _, remaining = get_current_term(db)
    return remaining
