import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.api import achievements, admin, ai, art, auth, calendar, debug, farm, player, quests, shop, social
from app.core.db import SessionLocal
from app.services import calendar_service
from app.ws import manager

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


@api.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        with SessionLocal() as db:
            cal = calendar_service.current_calendar(db)
        await websocket.send_json(
            {"type": "solar_term_change", "payload": cal, "ts": int(time.time())}
        )
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_json({"type": "pong", "ts": int(time.time())})
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)
