import uuid

from fastapi import Depends, Header
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.core.errors import AppError
from app.core.security import decode_token
from app.models import Player


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_player(
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
) -> Player:
    if not authorization or not authorization.startswith("Bearer "):
        raise AppError("UNAUTHORIZED", "未登录", http_status=401, code=10002)
    token = authorization.removeprefix("Bearer ").strip()
    user_id = decode_token(token)
    if not user_id:
        raise AppError("UNAUTHORIZED", "登录已过期,请重新登录", http_status=401, code=10003)
    try:
        player = db.query(Player).filter(Player.user_id == uuid.UUID(user_id)).first()
    except ValueError:
        raise AppError("UNAUTHORIZED", "登录已过期,请重新登录", http_status=401, code=10003)
    if not player:
        raise AppError("UNAUTHORIZED", "玩家不存在", http_status=401, code=10002)
    return player
