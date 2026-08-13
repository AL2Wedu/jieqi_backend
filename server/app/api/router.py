import asyncio
import time
import uuid

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.api import achievements, admin, ai, art, auth, calendar, debug, farm, player, quests, shop, social
from app.core.db import SessionLocal
from app.core.security import decode_token
from app.models import Player
from app.services import world_service

api = APIRouter(prefix="/v1")
api.include_router(auth.router)
api.include_router(player.router)
api.include_router(calendar.router)
api.include_router(farm.router)
api.include_router(shop.router)
api.include_router(quests.router)
api.include_router(social.router)
api.include_router(achievements.router)
api.include_router(ai.router)
api.include_router(art.router)
api.include_router(debug.router)
api.include_router(admin.router)


def _resolve_player(db, token: str) -> Player | None:
    """按玩家 JWT 解析 Player;无效/过期返回 None。"""
    user_id = decode_token(token)
    if not user_id:
        return None
    try:
        return db.query(Player).filter(Player.user_id == uuid.UUID(user_id)).first()
    except ValueError:
        return None


@api.websocket("/ws")
async def ws_endpoint(websocket: WebSocket, token: str = Query(default="")):
    """每用户节气实时推送:连接时发送自己的节气,切换时按在线倍速到点推送。

    认证走查询参数(WS 无法带 Header);无效 token 关 4401。
    客户端 ping 保活;连接期间视为在线(世界按 1× 推进)。
    """
    with SessionLocal() as db:
        player = _resolve_player(db, token)
        if player is None:
            await websocket.close(code=4401)
            return
        await websocket.accept()
        world_service.sync_world(db, player)
        db.commit()
        cal = world_service.current_calendar(db, player)
    await websocket.send_json(
        {"type": "solar_term_change", "payload": cal, "ts": int(time.time())}
    )
    try:
        while True:
            with SessionLocal() as db:
                from app.services.calendar_service import get_clock

                remaining = world_service.current_calendar(db, player)["remaining_sec"]
                scale = float(get_clock(db).time_scale)
            timeout = max(0.5, remaining / scale) if scale > 0 else 1.0
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=timeout)
                if data == "ping":
                    await websocket.send_json({"type": "pong", "ts": int(time.time())})
                    # ping = 心跳:刷新在线状态(下方循环重新计算剩余秒)
                    continue
            except asyncio.TimeoutError:
                pass
            except WebSocketDisconnect:
                break
            # 到点(或收到其他文本):重算并推送当前节气
            with SessionLocal() as db:
                world_service.sync_world(db, player)
                db.commit()
                cal = world_service.current_calendar(db, player)
            await websocket.send_json(
                {"type": "solar_term_change", "payload": cal, "ts": int(time.time())}
            )
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
