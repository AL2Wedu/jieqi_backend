from fastapi import APIRouter, Body, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_current_player, get_db
from app.core.errors import ok
from app.models import Player
from app.services import ai_service

router = APIRouter(prefix="/ai", tags=["ai"])


@router.post("/chat")
async def chat(
    payload: dict = Body(...),
    player: Player = Depends(get_current_player),
    db: Session = Depends(get_db),
):
    """OpenAI 兼容对话转发:请求体直接透传(模型/消息/参数),响应原样返回,自动记录用量。

    请求体示例:{"model":"deepseek-chat","messages":[{"role":"user","content":"谷雨是什么?"}]}
    """
    return ok(await ai_service.chat(db, player, payload))


@router.get("/models")
async def models(player: Player = Depends(get_current_player), db: Session = Depends(get_db)):
    """上游可用模型列表(透传 /models)。"""
    return ok(await ai_service.list_models(db))


@router.get("/usage")
def usage(player: Player = Depends(get_current_player), db: Session = Depends(get_db)):
    """我的 AI 用量(总量 + 按日明细)。"""
    return ok(ai_service.player_usage(db, player))
