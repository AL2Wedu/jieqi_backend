"""任务系统:自动跟踪(无需接取),进度由服务器按通用条件实时计算。"""
import uuid
from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.utils import ensure_aware
from app.models import Player, Quest, UserQuest
from app.services.goal_service import evaluate, grant_reward


def _utcnow():
    return datetime.now(timezone.utc)


def _reset_daily_if_new_day(uq: UserQuest) -> bool:
    """daily 任务跨天重置:若上次完成/领取的日期不是今天 → 回到进行中,可再领。

    用 completed_at/claimed_at 的日期判断,无需额外字段。once/story 任务不受影响。
    """
    if uq.status not in (1, 2):
        return False
    marker = uq.claimed_at or uq.completed_at
    if marker is None or ensure_aware(marker).date().isoformat() != date.today().isoformat():
        uq.status = 0
        uq.completed_at = None
        uq.claimed_at = None
        return True
    return False


def _quest_view(q: Quest, uq: UserQuest) -> dict:
    return {
        "quest_id": str(q.id),
        "code": q.code,
        "name": q.name,
        "description": q.description,
        "category": q.category,
        "objective": q.objective,
        "reward": q.reward or {},
        "status": uq.status,  # 0进行中 1已完成 2已领取
        "progress": uq.progress,
    }


def list_quests(db: Session, player: Player) -> dict:
    quests = (
        db.query(Quest).filter(Quest.active.is_(True)).order_by(Quest.sort_order).all()
    )
    uqs = {
        uq.quest_id: uq
        for uq in db.query(UserQuest).filter(UserQuest.player_id == player.id).all()
    }
    items = []
    for q in quests:
        uq = uqs.get(q.id)
        if not uq:
            uq = UserQuest(player_id=player.id, quest_id=q.id)
            db.add(uq)
            db.flush()
        # daily 任务跨天重置(昨天领过的今天可再领);once/story 不重置
        if q.category == "daily":
            _reset_daily_if_new_day(uq)
        cur, target = evaluate(db, player, q.objective)
        uq.progress = {"current": cur, "target": target}
        if cur >= target and uq.status == 0:
            uq.status = 1
            uq.completed_at = _utcnow()
        items.append(_quest_view(q, uq))
    db.commit()
    return {"items": items}


def claim(db: Session, player: Player, quest_id: str) -> dict:
    try:
        qid = uuid.UUID(quest_id)
    except ValueError:
        raise AppError("QUEST_NOT_FOUND", "任务不存在", code=25001)
    uq = (
        db.query(UserQuest)
        .filter(UserQuest.player_id == player.id, UserQuest.quest_id == qid)
        .first()
    )
    if not uq:
        raise AppError("QUEST_NOT_FOUND", "任务不存在", code=25001)
    if uq.status == 0:
        # 领奖前重新计算一次进度
        quest = db.query(Quest).filter(Quest.id == qid).first()
        cur, target = evaluate(db, player, quest.objective)
        if cur < target:
            raise AppError("QUEST_NOT_COMPLETE", "任务尚未完成", code=25002)
        uq.status = 1
        uq.completed_at = _utcnow()
    if uq.status == 2:
        raise AppError("QUEST_ALREADY_CLAIMED", "奖励已领取", code=25003)
    # 幂等抢占:条件更新把任务从"已完成"置为"已领取",仅当仍为 status=1。
    # 并发双领时只有一个 UPDATE 命中(rowcount=1),另一个 rowcount=0 → 拒绝,
    # 杜绝重复刷金币/经验/道具。
    now = _utcnow()
    claimed = (
        db.query(UserQuest)
        .filter(
            UserQuest.player_id == player.id,
            UserQuest.quest_id == qid,
            UserQuest.status == 1,
        )
        .update({UserQuest.status: 2, UserQuest.claimed_at: now})
    )
    if claimed != 1:
        # 已被并发请求领取或状态异常
        db.commit()
        raise AppError("QUEST_ALREADY_CLAIMED", "奖励已领取", code=25003)
    quest = db.query(Quest).filter(Quest.id == qid).first()
    reward = grant_reward(db, player, quest.reward, reason=f"quest:{quest.code}")
    uq.status = 2
    uq.claimed_at = now
    db.commit()
    return {
        "quest_id": quest_id,
        "code": quest.code,
        "reward": reward,
        "coins_balance": player.coins,
    }
