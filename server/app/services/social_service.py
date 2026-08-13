"""社交系统:好友申请 / 接受 / 拒绝 / 列表 / 删除。"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import Friendship, Player, User


def _utcnow():
    return datetime.now(timezone.utc)


def _pair(a: uuid.UUID, b: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    return (a, b) if a < b else (b, a)


def _player_name(db: Session, player_id) -> str:
    p = db.query(Player).filter(Player.id == player_id).first()
    u = db.query(User).filter(User.id == p.user_id).first() if p else None
    return u.name if u else "?"


def send_request(db: Session, player: Player, target_id: str) -> dict:
    try:
        target_uuid = uuid.UUID(target_id)
    except ValueError:
        raise AppError("USER_NOT_FOUND", "用户不存在", code=20002)
    if target_uuid == player.id:
        raise AppError("INVALID_PARAMS", "不能添加自己为好友", code=10001)
    target = db.query(Player).filter(Player.id == target_uuid).first()
    if not target:
        raise AppError("USER_NOT_FOUND", "用户不存在", code=20002)
    a, b = _pair(player.id, target_uuid)
    fs = (
        db.query(Friendship)
        .filter(Friendship.player_a == a, Friendship.player_b == b)
        .first()
    )
    if fs:
        if fs.status == 1:
            raise AppError("ALREADY_FRIENDS", "你们已经是好友", code=27001)
        if fs.status == 0:
            raise AppError("REQUEST_EXISTS", "申请已发送,等待对方处理", code=27002)
        # 曾被拒绝:允许重新申请
        fs.status = 0
        fs.responded_at = None
        fs.created_at = _utcnow()
    else:
        db.add(
            Friendship(
                player_a=a,
                player_b=b,
                requester=player.id,
                status=0,
            )
        )
    db.commit()
    return {"status": 0, "target_player_id": str(target_uuid)}


def list_friends(db: Session, player: Player) -> dict:
    rows = (
        db.query(Friendship)
        .filter(
            or_(Friendship.player_a == player.id, Friendship.player_b == player.id),
            Friendship.status == 1,
        )
        .all()
    )
    ids = [r.player_b if r.player_a == player.id else r.player_a for r in rows]
    return {
        "items": [
            {"player_id": str(pid), "name": _player_name(db, pid)} for pid in ids
        ]
    }


def list_requests(db: Session, player: Player) -> dict:
    """发给我的待处理申请(requester 不是我)。"""
    rows = (
        db.query(Friendship)
        .filter(
            or_(Friendship.player_a == player.id, Friendship.player_b == player.id),
            Friendship.status == 0,
            Friendship.requester != player.id,
        )
        .order_by(Friendship.created_at.desc())
        .all()
    )
    requester_ids = {r.requester for r in rows}
    return {
        "items": [
            {
                "player_id": str(rid),
                "name": _player_name(db, rid),
                "created_at": next(r.created_at.isoformat() for r in rows if r.requester == rid),
            }
            for rid in requester_ids
        ]
    }


def respond(db: Session, player: Player, requester_id: str, accept: bool) -> dict:
    try:
        requester_uuid = uuid.UUID(requester_id)
    except ValueError:
        raise AppError("REQUEST_NOT_FOUND", "申请不存在", code=27003)
    a, b = _pair(player.id, requester_uuid)
    fs = (
        db.query(Friendship)
        .filter(Friendship.player_a == a, Friendship.player_b == b)
        .first()
    )
    if not fs or fs.status != 0:
        raise AppError("REQUEST_NOT_FOUND", "申请不存在", code=27003)
    if fs.requester != requester_uuid:
        raise AppError("NOT_YOUR_REQUEST", "该申请不是发给你的", code=27004)
    fs.status = 1 if accept else 2
    fs.responded_at = _utcnow()
    db.commit()
    return {"status": fs.status, "target_player_id": str(requester_uuid)}


def remove_friend(db: Session, player: Player, other_id: str) -> dict:
    try:
        other_uuid = uuid.UUID(other_id)
    except ValueError:
        raise AppError("FRIEND_NOT_FOUND", "好友不存在", code=27005)
    a, b = _pair(player.id, other_uuid)
    fs = (
        db.query(Friendship)
        .filter(Friendship.player_a == a, Friendship.player_b == b, Friendship.status == 1)
        .first()
    )
    if not fs:
        raise AppError("FRIEND_NOT_FOUND", "好友不存在", code=27005)
    db.delete(fs)
    db.commit()
    return {"removed_player_id": str(other_uuid)}
