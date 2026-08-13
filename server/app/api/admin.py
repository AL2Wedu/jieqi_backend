import asyncio
import json

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
    AdminStatusRequest,
    AdminTermDuration,
)
from app.services import admin_service, ai_service
from app.ws.terminal import bridge

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


@router.websocket("/terminal")
async def terminal_ws(websocket: WebSocket, token: str = Query(default="")):
    """管理终端:ConPTY PowerShell 桥。token 走查询参数(WS 无法带 Header)。"""
    if not settings.admin_enabled or not is_admin_token(token):
        await websocket.close(code=4401)
        return
    await websocket.accept()
    if not bridge.ensure_started():
        await websocket.send_json({"type": "error", "data": "终端不可用:缺少 pywinpty 支持"})
        await websocket.close()
        return

    loop = asyncio.get_running_loop()
    queue = bridge.subscribe(loop)

    async def sender() -> None:
        while True:
            text = await queue.get()
            await websocket.send_json({"type": "data", "data": text})

    sender_task = asyncio.create_task(sender())
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except Exception:
                msg = {"type": "input", "data": raw}
            t = msg.get("type")
            if t == "input":
                bridge.write(str(msg.get("data", "")))
            elif t == "resize":
                bridge.resize(int(msg.get("rows", 24)), int(msg.get("cols", 110)))
    except WebSocketDisconnect:
        pass
    finally:
        sender_task.cancel()
        bridge.unsubscribe(queue)
