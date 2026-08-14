"""AI 客人议价出售端点(全部 🔐)。"""
import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.core.deps import get_current_player, get_db
from app.core.errors import ok
from app.models import Player
from app.services import guest_service

router = APIRouter(prefix="/shop/guest", tags=["shop-guest"])


class StartPayload(BaseModel):
    crop_id: str


class ChatPayload(BaseModel):
    message: str


@router.post("/start")
def guest_start(
    req: StartPayload,
    player: Player = Depends(get_current_player),
    db: Session = Depends(get_db),
):
    """开一单 AI 客人议价(1 份收成,多轮讨价还价)。"""
    return ok(guest_service.start_guest(db, player, req.crop_id))


@router.post("/{session_id}/chat")
async def guest_chat(
    session_id: str,
    req: ChatPayload,
    player: Player = Depends(get_current_player),
    db: Session = Depends(get_db),
):
    """跟客人对话一轮;deal=true 当场成交结算。"""
    return ok(await guest_service.chat_guest(db, player, session_id, req.message))


@router.post("/{session_id}/accept")
def guest_accept(
    session_id: str,
    player: Player = Depends(get_current_player),
    db: Session = Depends(get_db),
):
    """接受客人当前报价 → 成交结算。"""
    return ok(guest_service.accept_guest(db, player, session_id))


@router.post("/{session_id}/cancel")
def guest_cancel(
    session_id: str,
    player: Player = Depends(get_current_player),
    db: Session = Depends(get_db),
):
    """赶客放弃 → 不成交,结束会话。"""
    return ok(guest_service.cancel_guest(db, player, session_id))


@router.get("/{session_id}")
def guest_snapshot(
    session_id: str,
    player: Player = Depends(get_current_player),
    db: Session = Depends(get_db),
):
    """会话快照(含全部消息历史),断线重进用。"""
    return ok(guest_service.get_guest(db, player, session_id))
