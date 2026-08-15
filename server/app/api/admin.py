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
    AdminPlayerAssetsPayload,
    AdminPlotCropPayload,
    AdminPlotGrowthPayload,
    AdminPlotPayload,
    AdminQuantityPayload,
    AdminRedeemCreatePayload,
    AdminRedeemUpdatePayload,
    AdminRenamePayload,
    AdminShopSettingsPayload,
    AdminStatusRequest,
    AdminTermDuration,
    AdminUserShopItemPayload,
    AdminWorldPayload,
)
from app.services import admin_service, ai_service, pest_service, redeem_service

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


@router.patch("/users/{user_id}/assets")
def user_assets(
    user_id: str,
    req: AdminPlayerAssetsPayload,
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """编辑玩家资产:金币 / 等级 / 经验 / 解锁节气(全可选)。"""
    return ok(admin_service.update_player_assets(db, user_id, req.model_dump(exclude_none=True)))


@router.get("/users/{user_id}/assets")
def user_assets_get(
    user_id: str,
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """玩家当前资产(弹窗预填用)。"""
    return ok(admin_service.get_player_assets(db, user_id))


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
        )
    )


# ---------- 玩家资产 / 农场 / 每用户世界(节气独立) ----------

@router.get("/users/{user_id}/farm")
def user_farm(
    user_id: str,
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """某用户农场:地块 + 当前作物 + 玩家当前节气(每用户世界)。"""
    return ok(admin_service.list_player_farm(db, user_id))


@router.put("/users/{user_id}/plots/{plot_idx}")
def user_plot(
    user_id: str,
    plot_idx: int,
    req: AdminPlotPayload,
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """地块管理:锁定/解锁、土壤肥力。"""
    return ok(
        admin_service.update_player_plot(db, user_id, plot_idx, req.model_dump(exclude_none=True))
    )


@router.put("/users/{user_id}/plots/{plot_idx}/crop")
def user_plot_crop(
    user_id: str,
    plot_idx: int,
    req: AdminPlotCropPayload,
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """地块作物:种植/替换指定作物(不消耗种子、不校验节气窗;growth_progress 为唯一真源)。"""
    return ok(
        admin_service.admin_set_plot_crop(
            db, user_id, plot_idx, req.model_dump(exclude_none=True)
        )
    )


@router.delete("/users/{user_id}/plots/{plot_idx}/crop")
def user_plot_crop_delete(
    user_id: str,
    plot_idx: int,
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """清除地块作物(无产量)。"""
    return ok(admin_service.admin_clear_plot_crop(db, user_id, plot_idx))


@router.put("/users/{user_id}/plots/{plot_idx}/growth")
def user_plot_growth(
    user_id: str,
    plot_idx: int,
    req: AdminPlotGrowthPayload,
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """调整地块已有作物生长进度% / 浇水。"""
    return ok(
        admin_service.admin_set_plot_growth(
            db, user_id, plot_idx, req.model_dump(exclude_none=True)
        )
    )


@router.put("/users/{user_id}/inventory/{item_id}")
def user_inventory_set(
    user_id: str,
    item_id: str,
    req: AdminQuantityPayload,
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """设定玩家道具数量(绝对值;0=清空;写账本)。"""
    return ok(admin_service.admin_set_inventory(db, user_id, item_id, req.quantity))


@router.get("/users/{user_id}/inventory")
def user_inventory_list(
    user_id: str,
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """玩家背包明细(全部道具 + 当前数量)。"""
    return ok(admin_service.list_player_inventory(db, user_id))


@router.put("/users/{user_id}/storage/{crop_id}")
def user_storage_set(
    user_id: str,
    crop_id: str,
    req: AdminQuantityPayload,
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """设定收成仓该作物库存(绝对值;0=清空)。"""
    return ok(admin_service.admin_set_storage(db, user_id, crop_id, req.quantity))


@router.get("/users/{user_id}/storage")
def user_storage_list(
    user_id: str,
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """玩家收成仓明细(全部作物 + 当前数量)。"""
    return ok(admin_service.list_player_storage(db, user_id))


@router.get("/worlds")
def worlds(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """每用户世界/节气列表(含在线状态与累计世界秒)。"""
    return ok(admin_service.list_worlds(db, page, page_size))


@router.put("/worlds/{player_id}")
def world_update(
    player_id: str,
    req: AdminWorldPayload,
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """重置/设定某玩家世界:reset 回到立春;或设定累计世界秒;或覆盖/清除速率。"""
    return ok(
        admin_service.update_world(
            db, player_id,
            accum=req.accum, reset=req.reset,
            time_scale=req.time_scale, clear_override=req.clear_override,
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


# ---------- 虫害设置与事件 ----------

@router.get("/pest/config")
def pest_config(admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    """虫害系统配置(触发频率/大虫害参数/阶段倒计时)。"""
    return ok(pest_service.pest_config(db))


@router.put("/pest/config")
def pest_config_save(
    payload: dict,
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """保存虫害配置(pest.*,任意子集)。"""
    return ok(pest_service.save_pest_config(db, payload))


@router.get("/pest/events")
def pest_events(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """虫害事件记录(玩家/类型/成绩/奖励/惩罚)。"""
    return ok(pest_service.list_events(db, page, page_size))


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


@router.get("/guests")
def list_guests(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status: str | None = Query(default=None, description="过滤状态:bargaining/done/closed/cancelled"),
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """AI 客人会话列表(玩家/菜/状态/报价/轮次),管理端可观测。"""
    from app.models import AiGuestSession, Player, User, Crop

    qs = (
        db.query(AiGuestSession, Player, User, Crop)
        .join(Player, Player.id == AiGuestSession.player_id)
        .join(User, User.id == Player.user_id)
        .join(Crop, Crop.id == AiGuestSession.crop_id)
    )
    if status:
        qs = qs.filter(AiGuestSession.status == status)
    total = qs.count()
    rows = (
        qs.order_by(AiGuestSession.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    items = [
        {
            "session_id": str(s.id),
            "player_name": u.name,
            "crop_name": c.name,
            "guest_name": s.guest_name,
            "status": s.status,
            "offer": s.offer,
            "base_price": s.base_price,
            "turns": s.turns,
            "mood": s.last_mood,
            "created_at": s.created_at.isoformat(timespec="seconds"),
            "finished_at": s.finished_at.isoformat(timespec="seconds") if s.finished_at else None,
        }
        for s, p, u, c in rows
    ]
    return ok({"items": items, "page": page, "page_size": page_size, "total": total})


# ---------- 兑换码管理(仅 admin) ----------

@router.post("/redeem/codes")
def redeem_create(
    req: AdminRedeemCreatePayload,
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """发布兑换码(单个/批量):明文只在响应返回一次,库中存哈希。"""
    return ok(redeem_service.create_code(db, admin, req.model_dump()))


@router.get("/redeem/codes")
def redeem_list(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """兑换码列表(运营视图):只回前 6 位 hint + 用量/状态。"""
    return ok(
        redeem_service.list_codes(
            db, limit=page_size, offset=(page - 1) * page_size
        )
    )


@router.put("/redeem/codes/{code_id}")
def redeem_update(
    code_id: str,
    req: AdminRedeemUpdatePayload,
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """更新兑换码:停用/启用、次数上限、过期时间(软管理不删除)。"""
    return ok(redeem_service.update_code(db, admin, code_id, req.model_dump(exclude_none=True)))


@router.put("/users/{user_id}/rename")
def user_rename(
    user_id: str,
    req: AdminRenamePayload,
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """管理端改名(无限速):同步 User.name + Player.name。"""
    return ok(admin_service.rename_user(db, user_id, req.new_name))
