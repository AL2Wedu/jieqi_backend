import asyncio
import json
from pathlib import Path

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import get_current_admin, get_db
from app.core.errors import AppError, ok
from app.core.security import create_admin_token, is_admin_token
from app.schemas import (
    AdminAiConfigPayload,
    AdminClockPayload,
    AdminConfigValue,
    AdminCropPayload,
    AdminItemPayload,
    AdminLoginRequest,
    AdminShopSettingsPayload,
    AdminStatusRequest,
    AdminTermDuration,
    AdminUserShopItemPayload,
)
from app.services import admin_service, ai_service

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/login")
def login(req: AdminLoginRequest, db: Session = Depends(get_db)):
    if not settings.admin_enabled:
        raise AppError("ADMIN_DISABLED", "管理后台已关闭", http_status=403, code=30002)
    if (
        req.username != settings.admin_username
        or not settings.admin_password
        or req.password != settings.admin_password
    ):
        raise AppError("ADMIN_BAD_CREDENTIALS", "管理员账号或密码错误", http_status=401, code=30001)
    return ok({"token": create_admin_token()})


@router.get("/dashboard")
def dashboard(admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    return ok(admin_service.dashboard(db))


@router.get("/env")
def env(admin: str = Depends(get_current_admin)):
    return ok(admin_service.list_env())


@router.get("/users")
def users(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    return ok(admin_service.list_users(db, page, page_size))


@router.patch("/users/{user_id}/status")
def user_status(
    user_id: str,
    req: AdminStatusRequest,
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    return ok(admin_service.set_user_status(db, user_id, req.status))


@router.get("/config")
def config(admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    return ok(admin_service.list_config(db))


@router.put("/config/{key}")
def config_put(
    key: str,
    req: AdminConfigValue,
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    return ok(admin_service.set_config(db, key, req.value))


@router.delete("/config/{key}")
def config_delete(
    key: str,
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    return ok(admin_service.delete_config(db, key))


@router.get("/crops")
def crops(admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    return ok(admin_service.list_crops(db))


@router.get("/plantings")
def plantings(
    active: bool = Query(default=True),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    return ok(admin_service.list_plantings(db, page, page_size, active_only=active))


@router.post("/crops")
def crops_create(
    req: AdminCropPayload,
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    return ok(admin_service.create_crop(db, req.model_dump(exclude_none=True), auto_seed=req.auto_seed))


@router.put("/crops/{crop_id}")
def crops_update(
    crop_id: str,
    req: AdminCropPayload,
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    return ok(admin_service.update_crop(db, crop_id, req.model_dump(exclude_none=True)))


@router.delete("/crops/{crop_id}")
def crops_delete(
    crop_id: str,
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    return ok(admin_service.delete_crop(db, crop_id))


@router.get("/items")
def items(admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    return ok(admin_service.list_items(db))


@router.post("/items")
def items_create(
    req: AdminItemPayload,
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    return ok(admin_service.create_item(db, req.model_dump(exclude_none=True)))


@router.put("/items/{item_id}")
def items_update(
    item_id: str,
    req: AdminItemPayload,
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    return ok(admin_service.update_item(db, item_id, req.model_dump(exclude_none=True)))


@router.delete("/items/{item_id}")
def items_delete(
    item_id: str,
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    return ok(admin_service.delete_item(db, item_id))


@router.get("/terms")
def terms(admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    return ok(admin_service.list_terms(db))


@router.put("/terms/{term_index}")
def terms_update(
    term_index: int,
    req: AdminTermDuration,
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    return ok(admin_service.set_term_duration(db, term_index, req.duration_seconds))


@router.put("/clock")
def clock_update(
    req: AdminClockPayload,
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    return ok(
        admin_service.update_clock(
            db,
            time_scale=req.time_scale,
            paused=req.paused,
            reset_epoch=req.reset_epoch,
        )
    )


# ---------- AI 设置与用量 ----------

@router.get("/ai/config")
def ai_config(admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    """AI 配置(api_key 脱敏)。"""
    return ok(ai_service.masked_config(db))


@router.put("/ai/config")
def ai_config_save(
    req: AdminAiConfigPayload,
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """保存 AI 配置(服务器地址 / API Key / 模型 / 开关)。"""
    return ok(ai_service.save_ai_config(db, req.model_dump(exclude_none=True)))


@router.post("/ai/test")
async def ai_test(admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    """测试 AI 连接:拉取上游模型列表。"""
    return ok(await ai_service.list_models(db))


@router.get("/ai/usage")
def ai_usage(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """全服每用户 AI 用量。"""
    return ok(ai_service.admin_usage(db, page, page_size))


# ---------- 商店管理(全局默认 + 每用户商店) ----------

@router.get("/shop/settings")
def shop_settings(admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    """全局商店默认(库存/补货周期/价格系数)。"""
    return ok(admin_service.shop_settings_view(db))


@router.put("/shop/settings")
def shop_settings_save(
    req: AdminShopSettingsPayload,
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """保存全局商店默认。"""
    return ok(admin_service.update_shop_settings(db, req.model_dump(exclude_none=True)))


@router.get("/shop/users")
def shop_users(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """每用户商店摘要(隔离实例)。"""
    return ok(admin_service.list_user_shops(db, page, page_size))


@router.get("/shop/users/{player_id}/items")
def shop_user_items(
    player_id: str,
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """某用户商店的商品明细(库存/价格/覆盖)。"""
    return ok(admin_service.list_user_shop_items(db, player_id))


@router.put("/shop/users/{player_id}/items/{item_id}")
def shop_user_item_update(
    player_id: str,
    item_id: str,
    req: AdminUserShopItemPayload,
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """覆盖某用户某商品:库存 / buy_price / sell_price(显式 null 清除覆盖,恢复公式价)。"""
    return ok(
        admin_service.update_user_shop_item(
            db, player_id, item_id, req.model_dump(exclude_unset=True)
        )
    )


@router.post("/shop/users/{player_id}/restock")
def shop_user_restock(
    player_id: str,
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """手动补货:重置该用户商店全部库存为默认。"""
    return ok(admin_service.restock_user_shop(db, player_id))


@router.post("/shop/users/{player_id}/reset")
def shop_user_reset(
    player_id: str,
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """重置该用户商店:清覆盖、恢复默认库存。"""
    return ok(admin_service.reset_user_shop(db, player_id))


@router.websocket("/logs")
async def logs_ws(websocket: WebSocket, token: str = Query(default="")):
    """后端运行日志实时流(等价 Get-Content -Wait):初始回放最后 200 行,之后增量推送。

    安全:只读日志文件,不暴露任何命令执行能力;token 走查询参数(WS 无法带 Header)。
    客户端 ping 保活;文件被轮转(变小)时自动从头重读。
    """
    if not settings.admin_enabled or not is_admin_token(token):
        await websocket.close(code=4401)
        return
    await websocket.accept()
    log_path = Path(__file__).resolve().parent.parent.parent / "logs" / "server.out.log"

    def tail_lines() -> list[str]:
        if not log_path.exists():
            return []
        return log_path.read_text(encoding="utf-8", errors="replace").splitlines()

    initial = tail_lines()
    for line in initial[-200:]:
        await websocket.send_json({"type": "log", "data": line})
    if not initial:
        await websocket.send_json(
            {
                "type": "error",
                "data": "日志文件不存在(请用 scripts\\run_server.ps1 启动后端以启用日志)",
            }
        )
    last_size = log_path.stat().st_size if log_path.exists() else 0
    try:
        while True:
            try:
                msg = await asyncio.wait_for(websocket.receive_text(), timeout=1.0)
                if msg == "ping":
                    await websocket.send_json({"type": "pong"})
            except asyncio.TimeoutError:
                pass
            except WebSocketDisconnect:
                break
            if not log_path.exists():
                last_size = 0
                continue
            size = log_path.stat().st_size
            if size < last_size:  # 日志轮转/清空
                last_size = 0
                await websocket.send_json({"type": "error", "data": "[日志文件已轮转,从头重读]"})
            if size > last_size:
                with open(log_path, encoding="utf-8", errors="replace") as f:
                    f.seek(last_size)
                    chunk = f.read()
                for line in chunk.splitlines():
                    await websocket.send_json({"type": "log", "data": line})
                last_size = size
    except WebSocketDisconnect:
        pass
