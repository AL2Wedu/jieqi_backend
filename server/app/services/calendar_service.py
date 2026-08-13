"""节气轮转时钟:节气由公式计算,无日历表。

世界时间(秒):
- 全局参考(elapsed = (now - epoch) × time_scale,暂停时冻结),供管理端/新玩家初始化。
- 每用户独立(world_service):玩家各自维护累计世界秒,在线 1× / 离线 offline_factor。
- term_at(elapsed) 是纯函数:给定世界秒 → 节气三元组,两者共用。
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


def term_at(db: Session, elapsed_sec: float) -> tuple[TermConfig, int, int]:
    """纯函数:给定累计世界秒,返回 (当前节气, 轮次 cycle, 本轮剩余秒)。"""
    terms = _terms(db)
    if not terms:
        raise RuntimeError("term_config 未初始化,请先执行 seed")
    total = sum(t.duration_seconds for t in terms)
    elapsed = max(0.0, float(elapsed_sec))
    cycle = int(elapsed // total)
    rem = elapsed % total
    acc = 0.0
    for t in terms:
        if rem < acc + t.duration_seconds:
            return t, cycle, int(acc + t.duration_seconds - rem)
        acc += t.duration_seconds
    last = terms[-1]
    return last, cycle, 0


def global_elapsed(db: Session, now: datetime | None = None) -> float:
    """全局参考世界时间(秒)。管理端 dashboard / 新玩家初始化用。"""
    clock = get_clock(db)
    now = now or datetime.now(timezone.utc)
    effective = ensure_aware(clock.paused_at) if clock.paused_at is not None else now
    epoch = ensure_aware(clock.epoch)
    return max(0.0, (effective - epoch).total_seconds() * float(clock.time_scale))


def get_current_term(db: Session) -> tuple[TermConfig, int, int]:
    """全局参考节气(供管理端/仪表盘)。"""
    return term_at(db, global_elapsed(db))


def calendar_dict(term: TermConfig, cycle: int, remaining_sec: int) -> dict:
    return {
        "term_index": term.term_index,
        "name": term.name,
        "cycle": cycle,
        "remaining_sec": remaining_sec,
    }


def current_calendar(db: Session) -> dict:
    term, cycle, remaining = get_current_term(db)
    return calendar_dict(term, cycle, remaining)


def next_switch_in(db: Session) -> int:
    _, _, remaining = get_current_term(db)
    return remaining
