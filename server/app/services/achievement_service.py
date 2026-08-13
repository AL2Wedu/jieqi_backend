"""成就系统(通用版):进度由服务器实时计算,自动达成,可领取奖励。

成就配置 achievements.target 使用与任务相同的通用条件格式(见 goal_service)。
广泛适配:新增成就只需在配置表加一行,不改代码;后续可逐条细化。
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import Achievement, Player, UserAchievement
from app.services.goal_service import evaluate, grant_reward


def _utcnow():
    return datetime.now(timezone.utc)


def _view(a: Achievement, ua: UserAchievement) -> dict:
    return {
        "achievement_id": str(a.id),
        "code": a.code,
        "name": a.name,
        "description": a.description,
        "category": a.category,
        "target": a.target or {},
        "reward": a.reward or {},
        "completed": ua.completed,
        "claimed": ua.claimed_at is not None,
        "progress": ua.progress,
        "completed_at": ua.completed_at.isoformat() if ua.completed_at else None,
    }


def list_achievements(db: Session, player: Player) -> dict:
    """列出全部成就并实时重算进度(自动达成)。"""
    achievements = (
        db.query(Achievement)
        .filter(Achievement.active.is_(True))
        .order_by(Achievement.category, Achievement.sort_order)
        .all()
    )
    uas = {
        ua.achievement_id: ua
        for ua in db.query(UserAchievement)
        .filter(UserAchievement.player_id == player.id)
        .all()
    }
    items = []
    for a in achievements:
        ua = uas.get(a.id)
        if not ua:
            ua = UserAchievement(player_id=player.id, achievement_id=a.id)
            db.add(ua)
            db.flush()
        cur, target = evaluate(db, player, a.target or {"type": "any"})
        ua.progress = {"current": cur, "target": target}
        if cur >= target and not ua.completed:
            ua.completed = True
            ua.completed_at = _utcnow()
        items.append(_view(a, ua))
    db.commit()
    return {"items": items}


def claim(db: Session, player: Player, achievement_id: str) -> dict:
    try:
        aid = uuid.UUID(achievement_id)
    except ValueError:
        raise AppError("ACHIEVEMENT_NOT_FOUND", "成就不存在", code=26001)
    ua = (
        db.query(UserAchievement)
        .filter(UserAchievement.player_id == player.id, UserAchievement.achievement_id == aid)
        .first()
    )
    if not ua:
        raise AppError("ACHIEVEMENT_NOT_FOUND", "成就不存在", code=26001)
    if not ua.completed:
        # 领奖前重算一次
        a = db.query(Achievement).filter(Achievement.id == aid).first()
        cur, target = evaluate(db, player, a.target or {"type": "any"})
        if cur < target:
            raise AppError("ACHIEVEMENT_NOT_COMPLETE", "成就尚未达成", code=26002)
        ua.completed = True
        ua.completed_at = _utcnow()
    if ua.claimed_at is not None:
        raise AppError("ACHIEVEMENT_ALREADY_CLAIMED", "奖励已领取", code=26003)
    a = db.query(Achievement).filter(Achievement.id == aid).first()
    reward = grant_reward(db, player, a.reward, reason=f"achievement:{a.code}")
    ua.claimed_at = _utcnow()
    db.commit()
    return {
        "achievement_id": achievement_id,
        "code": a.code,
        "reward": reward,
        "coins_balance": player.coins,
    }
