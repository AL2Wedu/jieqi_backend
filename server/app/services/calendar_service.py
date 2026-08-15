"""节气轮转时钟:节气由公式计算,无日历表。

世界时间(秒):
- 每用户独立(world_service):玩家各自维护累计世界秒,在线 1× / 离线 offline_factor。
- term_at(elapsed) 是纯函数:给定世界秒 → 节气三元组。
"""
from datetime import datetime, timezone

from sqlalchemy.orm import Session

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


def term_start_elapsed(db: Session, term_index: int) -> float:
    """给定节气序号(1-based),返回其开始时刻对应的累计世界秒(该节气之前所有时长之和)。

    用于把"某个节气"映射回世界秒位置(如教学锁定在清明 = term_start_elapsed(db, 5))。
    """
    total = 0.0
    for t in _terms(db):
        if t.term_index < term_index:
            total += t.duration_seconds
    return total


def calendar_dict(term: TermConfig, cycle: int, remaining_sec: int) -> dict:
    return {
        "term_index": term.term_index,
        "name": term.name,
        "cycle": cycle,
        "remaining_sec": remaining_sec,
    }
