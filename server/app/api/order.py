"""AI 客人点菜购买端点(全部 🔐)。与议价 /v1/shop/guest 并存。"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.deps import get_current_player, get_db
from app.core.errors import ok
from app.models import Player
from app.services import order_service

router = APIRouter(prefix="/shop/order", tags=["shop-order"])


class ChatPayload(BaseModel):
    message: str
    session_id: str | None = None  # 首次调用省略 → 自动创建会话+AI 点单;后续带 session_id → 多轮对话


class OrderItem(BaseModel):
    crop_id: str
    quantity: int = 1


class ConfirmPayload(BaseModel):
    items: list[OrderItem]
    total_price: int


@router.post("/start")
async def order_start(
    player: Player = Depends(get_current_player),
    db: Session = Depends(get_db),
):
    """开始点菜会话:AI 收到菜种类+价格+提示词+客人名/年龄 → 输出点单 → 回传前端。"""
    return ok(await order_service.start_order(db, player))


@router.post("/chat")
async def order_chat_or_start(
    req: ChatPayload,
    player: Player = Depends(get_current_player),
    db: Session = Depends(get_db),
):
    """融合接口:首次调用(无 session_id)自动创建会话+AI 点单;后续(带 session_id)多轮对话。"""
    return ok(await order_service.chat_or_start_order(db, player, req.session_id, req.message))


@router.post("/{session_id}/chat")
async def order_chat(
    session_id: str,
    req: ChatPayload,
    player: Player = Depends(get_current_player),
    db: Session = Depends(get_db),
):
    """多轮对话(保持上下文)→ AI 返回 {raw_text, emotion, is_complete}。"""
    return ok(await order_service.chat_order(db, player, session_id, req.message))


@router.post("/{session_id}/confirm")
def order_confirm(
    session_id: str,
    req: ConfirmPayload,
    player: Player = Depends(get_current_player),
    db: Session = Depends(get_db),
):
    """玩家确认成交:服务端权威校验 items/price → 扣菜+加金币。"""
    items = [{"crop_id": it.crop_id, "quantity": it.quantity} for it in req.items]
    return ok(order_service.confirm_order(db, player, session_id, items, req.total_price))


@router.post("/{session_id}/cancel")
def order_cancel(
    session_id: str,
    player: Player = Depends(get_current_player),
    db: Session = Depends(get_db),
):
    """取消点菜会话。"""
    return ok(order_service.cancel_order(db, player, session_id))


@router.get("/{session_id}")
def order_snapshot(
    session_id: str,
    player: Player = Depends(get_current_player),
    db: Session = Depends(get_db),
):
    """会话快照(含消息历史),断线重进用。"""
    return ok(order_service.get_order(db, player, session_id))
