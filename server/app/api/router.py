import asyncio
import logging
import time
import uuid

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.api import (
    achievements,
    admin,
    ai,
    art,
    assets,
    auth,
    calendar,
    debug,
    dev,
    farm,
    pest,
    player,
    quests,
    redeem,
    shop,
    shop_guest,
    social,
)
from app.core.db import SessionLocal
from app.core.security import decode_token
from app.models import Player
from app.services import farm_service, pest_service, world_service
from app.ws import manager

logger = logging.getLogger("jieqi")

api = APIRouter(prefix="/v1")
api.include_router(auth.router)
api.include_router(player.router)
api.include_router(calendar.router)
api.include_router(farm.router)
api.include_router(shop.router)
api.include_router(shop_guest.router)
api.include_router(quests.router)
api.include_router(social.router)
api.include_router(achievements.router)
api.include_router(ai.router)
api.include_router(art.router)
api.include_router(assets.router)
api.include_router(pest.router)
api.include_router(redeem.router)
api.include_router(debug.router)
api.include_router(dev.router)
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


def _player_banned(db, player: Player) -> bool:
    """玩家账号是否已被封禁(与 REST get_current_player 一致)。"""
    from app.models import User

    user = db.query(User).filter(User.id == player.user_id).first()
    return user is not None and user.status != 1


@api.websocket("/ws")
async def ws_endpoint(websocket: WebSocket, token: str = Query(default="")):
    """每用户实时推送:节气(自己的世界)+ 虫害事件(定向)。

    认证走查询参数(WS 无法带 Header);无效 token 关 4401。
    客户端 ping 保活;连接期间视为在线(世界按 1× 推进);
    虫害调度每 ~5 秒检查一次:到点触发(大/小虫害广播),寄生倒计时到点摧毁作物。
    """
    with SessionLocal() as db:
        player = _resolve_player(db, token)
        if player is None:
            await websocket.close(code=4401)
            return
        if _player_banned(db, player):
            await websocket.close(code=4403)
            return
        if not manager.can_connect(str(player.id)):
            # 连接数超限:拒绝(客户端应复用已有连接)
            await websocket.close(code=4429)
            return
        await websocket.accept()
        world_service.sync_world(db, player)
        pest_service.sync_offline(db, player)  # 离线回归:错过排程顺延;冬季/早春清空不排虫
        db.commit()
        cal = world_service.current_calendar(db, player)
    player_id = str(player.id)
    manager.connect(websocket, player_id)  # 同步注册(accept 已由上方完成)
    await websocket.send_json(
        {"type": "solar_term_change", "payload": cal, "ts": int(time.time())}
    )
    try:
        while True:
            with SessionLocal() as db:
                from app.services.calendar_service import get_clock

                remaining = world_service.current_calendar(db, player)["remaining_sec"]
                scale = float(get_clock(db).time_scale)
            # 最多等 5 秒:保证虫害调度/倒计时检查及时(节气到点由剩余秒驱动)
            timeout = max(0.5, min(remaining / scale, 5.0)) if scale > 0 else 1.0
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
            # 每轮:重新取玩家(防 detached 对象写不落库 + 封禁即时生效)→ 同步世界 → 节气推送 → 虫害检查
            with SessionLocal() as db:
                fresh = (
                    db.query(Player).filter(Player.id == player.id).first()
                )
                if fresh is None or _player_banned(db, fresh):
                    # 账号被删/被封:静默关闭(客户端重连时被 4403 拒)
                    break
                world_service.sync_world(db, fresh)
                db.commit()
                cal = world_service.current_calendar(db, fresh)
                # 1) 到点触发虫害(每用户隔离;已有进行中的事件则顺延;非活跃窗/离线回归由 is_due+sync_offline 门控)
                event = None
                try:
                    if pest_service.is_due(db, fresh) and not pest_service.has_active_pest(db, fresh):
                        event = pest_service.fire_pest(db, fresh)
                except Exception:
                    event = None
                # 2) 小虫害倒计时到点摧毁
                destroyed = pest_service.check_expiry(db, fresh)
                # 3) 枯萎判定:玩家季节进入作物枯萎季节 → 标记枯萎(冻死,仍占地块,待玩家铲除/收割)
                withered = farm_service.check_wither(db, fresh)
                # 4) 杂草判定:到点生长(随机地块附杂草)
                from app.services import weed_service

                weeded = weed_service.check_weed(db, fresh)
            if event:
                await manager.send_to_player(player_id, event)
            if destroyed:
                await manager.send_to_player(
                    player_id,
                    {
                        "type": "pest_destroyed",
                        "payload": {"targets": destroyed},
                        "ts": int(time.time()),
                    },
                )
            if withered:
                await manager.send_to_player(
                    player_id,
                    {
                        "type": "crop_withered",
                        "payload": {"targets": withered},
                        "ts": int(time.time()),
                    },
                )
            if weeded:
                await manager.send_to_player(
                    player_id,
                    {
                        "type": "weed_growth",
                        "payload": {"targets": weeded},
                        "ts": int(time.time()),
                    },
                )
            await websocket.send_json(
                {"type": "solar_term_change", "payload": cal, "ts": int(time.time())}
            )
    except WebSocketDisconnect:
        pass
    except Exception as e:
        # 记录异常而非静默吞掉,便于排查;连接随协程退出关闭
        logger.exception("WS 连接异常断开(player=%s): %s", player_id, e)
    finally:
        manager.disconnect(websocket, player_id)
