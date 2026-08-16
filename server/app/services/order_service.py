"""AI 客人点菜购买服务:客人报菜单+总价,玩家核对后成交。

与议价(guest_service)并存,独立前缀 /v1/shop/order。

流程:
1. start: 收集所有菜(种类+当前季节价)+ 默认提示词 + 客人独立提示词 + 客人名/年龄
   → 调 AI 输出 {raw_text, items:[crop.id], total_price} → 回传前端
2. chat: 多轮对话(保持上下文)→ AI 返回 {raw_text, emotion, is_complete}
3. confirm: 玩家提交实际选择的菜+总价 → 服务端权威校验 → 成交扣菜+加金币

安全:
- total_price 服务端按 _crop_price 重算校验,不信 AI 报的价(防作弊)
- is_right 由服务端比对(玩家 confirm 的 items/price vs AI 报的),不依赖 LLM 自报
- 极限 4 轮,超了强制 emotion=sad, is_complete=true, is_right=false
- 没菜了 → emotion=sad, is_complete=true, is_right=false, 不扣不加
"""
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.utils import ensure_aware
from app.models import AiGuestMessage, AiGuestSession, Crop, CropStorage, GameConfig, Player
from app.services import ai_service, guest_service, shop_service

_KEYS = (
    "order.enabled",
    "order.cooldown_seconds",
    "order.max_turns",
    "order.context_messages",
    "order.json_retries",
)
_DEFAULTS = {
    "order.enabled": True,
    "order.cooldown_seconds": 10,  # 客人走后 10-20s 再来（前端等待，冷却须 ≤ 10s）
    "order.max_turns": 4,  # 极限 4 轮
    "order.context_messages": 12,
    "order.json_retries": 1,
}
_EMOTIONS = ("happy", "calm", "sad", "confused")
_PROMPTS_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "guest_prompts.json"


def load_prompts() -> list[str]:
    """身份模板池(guest_prompts.json,list of 模板字符串,支持 {name}/{age}/{personality} 占位符)。"""
    try:
        data = json.loads(_PROMPTS_PATH.read_text(encoding="utf-8"))
        return [str(p).strip() for p in data if str(p).strip()]
    except (OSError, ValueError):
        return []


def _pick_prompt(guest: dict) -> str:
    """随机挑一个身份模板(密码学安全),替换占位符;池空时退回客人自带 order_prompt。"""
    import random

    pool = load_prompts()
    if pool:
        template = pool[random.SystemRandom().randrange(len(pool))]
    else:
        template = guest.get("order_prompt", "")
    if not template:
        return "你是一位普通顾客。"
    return (
        template.replace("{name}", guest.get("name", "顾客"))
        .replace("{age}", str(guest.get("age", "")))
        .replace("{personality}", guest.get("personality", "普通顾客"))
    )


def order_config(db: Session) -> dict:
    rows = {
        c.key: c.value
        for c in db.query(GameConfig).filter(GameConfig.key.in_(_KEYS)).all()
    }
    cfg = dict(_DEFAULTS)
    for k, v in rows.items():
        if v is not None:
            cfg[k] = v
    cfg["order.cooldown_seconds"] = max(0, int(cfg["order.cooldown_seconds"]))
    cfg["order.max_turns"] = max(1, min(10, int(cfg["order.max_turns"])))
    cfg["order.context_messages"] = max(2, int(cfg["order.context_messages"]))
    cfg["order.json_retries"] = max(0, min(3, int(cfg["order.json_retries"])))
    return cfg


def save_order_config(db: Session, data: dict) -> dict:
    for key in _KEYS:
        if key in data and data[key] is not None:
            row = db.query(GameConfig).filter(GameConfig.key == key).first()
            if row:
                row.value = data[key]
            else:
                db.add(GameConfig(key=key, value=data[key]))
    db.commit()
    return order_config(db)


# ---------- 菜单 ----------

def _menu(db: Session, player: Player) -> list[dict]:
    """所有在售菜:active 作物 + 当前季节价。"""
    settings = shop_service.get_settings(db)
    season = shop_service.current_season(db, player)
    crops = db.query(Crop).filter(Crop.active.is_(True)).order_by(Crop.sort_order).all()
    return [
        {
            "crop_id": str(c.id),
            "name": c.name,
            "price": shop_service._crop_price(c, settings, season),
        }
        for c in crops
    ]


def _menu_text(menu: list[dict]) -> str:
    return "\n".join(f"- {m['name']}(id={m['crop_id']}): {m['price']} 金币" for m in menu)


# ---------- 会话 ----------

def _get_session(db: Session, player: Player, session_id: str) -> AiGuestSession:
    try:
        sid = uuid.UUID(session_id)
    except ValueError:
        raise AppError("GUEST_NOT_FOUND", "会话不存在", code=29003)
    s = db.get(AiGuestSession, sid)
    if not s or s.player_id != player.id or s.mode != "order":
        raise AppError("GUEST_NOT_FOUND", "会话不存在或不属于你", code=29003)
    return s


def _check_bargaining(s: AiGuestSession) -> None:
    if s.status != "bargaining":
        raise AppError("GUEST_CLOSED", f"会话已结束({s.status})", code=29004)


def _finish(db: Session, player: Player, s: AiGuestSession, status: str) -> None:
    s.status = status
    s.finished_at = datetime.now(timezone.utc)
    if player.guest_encounter_key == s.guest_key:
        player.guest_encounter_key = None


def _try_finish(db: Session, s: AiGuestSession, status: str) -> bool:
    now = datetime.now(timezone.utc)
    rows = (
        db.query(AiGuestSession)
        .filter(AiGuestSession.id == s.id, AiGuestSession.status == "bargaining")
        .update({AiGuestSession.status: status, AiGuestSession.finished_at: now})
    )
    return rows == 1


# ---------- AI 调用 ----------

def _build_system_prompt(guest: dict, menu: list[dict], history: list[dict], user_msg: str, retrying: bool, cfg: dict) -> list[dict]:
    """构造 AI 输入:菜种类+价格 + 默认提示词 + 客人独立提示词 + 客人名/年龄。"""
    system = (
        f"你是{guest['name']}({guest['age']}岁),{_pick_prompt(guest)}\n"
        f"摊主今天有这些菜:\n{_menu_text(menu)}\n"
        "规则:\n"
        "1. 用自然口语表达你想买什么菜,每次回复必须同时给出你的点单。\n"
        "2. 输出 JSON 对象(不要 markdown 代码块,不要多余文字):\n"
        '{"raw_text": "...", "items": ["<crop_id>", ...], "total_price": <整数>}\n'
        "3. items 填你想买的菜的 crop_id(可多个),total_price 是这些菜的总价(按上面价格表算)。\n"
        "4. 如果摊主说没有某道菜了,你要表示失望并结束对话。\n"
    )
    if retrying:
        system += "5. 你上一次输出不是合法 JSON!必须只输出一个合法 JSON 对象。\n"
    messages = [{"role": "system", "content": system}]
    for m in history[-int(cfg["order.context_messages"]):]:
        # 客人消息 role 存库为 "guest",OpenAI 兼容 API 只认 assistant → 映射
        role = "assistant" if m["role"] == "guest" else m["role"]
        messages.append({"role": role, "content": m["content"]})
    messages.append({"role": "user", "content": user_msg})
    return messages


def _build_chat_system_prompt(guest: dict, menu: list[dict], history: list[dict], user_msg: str, retrying: bool, cfg: dict) -> list[dict]:
    """多轮对话提示词:AI 返回 {raw_text, emotion, is_complete}。"""
    system = (
        f"你是{guest['name']}({guest['age']}岁),{_pick_prompt(guest)}\n"
        f"摊主今天有这些菜:\n{_menu_text(menu)}\n"
        "规则:\n"
        "1. 用自然口语和摊主对话,表达你的购买意愿。\n"
        "2. 输出 JSON 对象(不要 markdown 代码块,不要多余文字):\n"
        f'{{"raw_text": "...", "emotion": "{"/".join(_EMOTIONS)}", "is_complete": true|false}}\n'
        "3. emotion 只能取 happy/calm/sad/confused:满意→happy;平静→calm;失望/没菜→sad;困惑→confused。\n"
        "4. is_complete 表示对话是否结束:成交或放弃→true;还想继续→false。\n"
    )
    if retrying:
        system += "5. 你上一次输出不是合法 JSON!必须只输出一个合法 JSON 对象。\n"
    messages = [{"role": "system", "content": system}]
    for m in history[-int(cfg["order.context_messages"]):]:
        # 客人消息 role 存库为 "guest",OpenAI 兼容 API 只认 assistant → 映射
        role = "assistant" if m["role"] == "guest" else m["role"]
        messages.append({"role": role, "content": m["content"]})
    messages.append({"role": "user", "content": user_msg})
    return messages


def _parse_reply(raw: str) -> dict:
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        raise ValueError("no json object")
    return json.loads(m.group(0))


def _validate_start_reply(data: dict, menu: list[dict]) -> dict:
    """校验 start 的 AI 输出:raw_text + items(合法 crop_id)+ total_price。"""
    raw_text = str(data.get("raw_text") or "").strip()
    if not raw_text:
        raise ValueError("raw_text empty")
    valid_ids = {m["crop_id"] for m in menu}
    items = []
    for it in (data.get("items") or []):
        cid = str(it).strip()
        if cid not in valid_ids:
            raise ValueError(f"invalid crop_id: {cid}")
        items.append(cid)
    if not items:
        raise ValueError("items empty")
    total_price = int(data.get("total_price") or 0)
    if total_price < 1:
        raise ValueError("total_price invalid")
    return {"raw_text": raw_text, "items": items, "total_price": total_price}


def _validate_chat_reply(data: dict) -> dict:
    """校验 chat 的 AI 输出:raw_text + emotion + is_complete。"""
    raw_text = str(data.get("raw_text") or "").strip()
    if not raw_text:
        raise ValueError("raw_text empty")
    emotion = str(data.get("emotion") or "calm")
    if emotion not in _EMOTIONS:
        emotion = "calm"
    is_complete = bool(data.get("is_complete"))
    return {"raw_text": raw_text, "emotion": emotion, "is_complete": is_complete}


def _fallback_start(guest: dict, menu: list[dict]) -> dict:
    """AI 失败兜底:随机点一道菜。"""
    import random

    m = menu[random.SystemRandom().randrange(len(menu))]
    return {"raw_text": f"我想买点{m['name']},多少钱?", "items": [m["crop_id"]], "total_price": m["price"]}


def _fallback_chat(guest: dict, emotion: str = "calm", is_complete: bool = False) -> dict:
    return {"raw_text": "……我再想想。", "emotion": emotion, "is_complete": is_complete}


async def _ask_start(db: Session, player: Player, guest: dict, menu: list[dict], cfg: dict) -> dict:
    """调 AI 生成点单。"""
    retries = cfg["order.json_retries"]
    for attempt in range(retries + 1):
        messages = _build_system_prompt(guest, menu, [], "请开始点单", attempt > 0, cfg)
        try:
            raw = await ai_service.chat(
                db, player, {"model": None, "messages": messages, "temperature": 0.8, "max_tokens": 300}
            )
            text = raw["choices"][0]["message"]["content"]
            return _validate_start_reply(_parse_reply(text), menu)
        except (AppError, KeyError, ValueError, TypeError, IndexError):
            if attempt < retries:
                continue
            return _fallback_start(guest, menu)
    raise AppError("GUEST_AI_RESPONSE", "AI 客人回复异常", code=29005)


async def _ask_chat(db: Session, player: Player, guest: dict, menu: list[dict], history: list[dict], user_msg: str, cfg: dict) -> dict:
    """调 AI 多轮对话。"""
    retries = cfg["order.json_retries"]
    for attempt in range(retries + 1):
        messages = _build_chat_system_prompt(guest, menu, history, user_msg, attempt > 0, cfg)
        try:
            raw = await ai_service.chat(
                db, player, {"model": None, "messages": messages, "temperature": 0.8, "max_tokens": 300}
            )
            text = raw["choices"][0]["message"]["content"]
            return _validate_chat_reply(_parse_reply(text))
        except (AppError, KeyError, ValueError, TypeError, IndexError):
            if attempt < retries:
                continue
            return _fallback_chat(guest)
    raise AppError("GUEST_AI_RESPONSE", "AI 客人回复异常", code=29005)


# ---------- 结算 ----------

def _settle_order(db: Session, player: Player, s: AiGuestSession, items: list[dict]) -> dict:
    """成交结算:逐项扣收成仓 + 加金币。items: [{crop_id, quantity}]。"""
    total = 0
    details = []
    for it in items:
        crop = db.get(Crop, uuid.UUID(it["crop_id"]))
        qty = int(it["quantity"])
        settings = shop_service.get_settings(db)
        season = shop_service.current_season(db, player)
        unit = shop_service._crop_price(crop, settings, season)
        wilted_unit = shop_service._wilted_price(crop, settings, season)
        settle = shop_service._settle_sale(
            db, player, crop, qty, unit, wilted_unit, f"order_sell:{s.guest_key}"
        )
        total += settle["price"]
        details.append(settle)
    return {"total_price": total, "details": details}


# ---------- 主流程 ----------

async def start_order(db: Session, player: Player) -> dict:
    """开始点菜会话:收集菜单 → 调 AI 生成点单 → 存会话 → 回传前端。"""
    cfg = order_config(db)
    if not cfg["order.enabled"]:
        raise AppError("GUEST_DISABLED", "AI 客人暂未开放", code=29006)
    # 冷却
    last = (
        db.query(AiGuestSession)
        .filter(AiGuestSession.player_id == player.id, AiGuestSession.finished_at.isnot(None))
        .order_by(AiGuestSession.finished_at.desc())
        .first()
    )
    if last is not None:
        elapsed = (datetime.now(timezone.utc) - ensure_aware(last.finished_at)).total_seconds()
        if elapsed < cfg["order.cooldown_seconds"]:
            raise AppError(
                "GUEST_COOLDOWN",
                f"客人刚走,{int(cfg['order.cooldown_seconds'] - elapsed)} 秒后再招呼",
                code=29002,
            )
    # 单活跃点菜会话
    active = (
        db.query(AiGuestSession)
        .filter(AiGuestSession.player_id == player.id, AiGuestSession.status == "bargaining", AiGuestSession.mode == "order")
        .first()
    )
    if active:
        raise AppError(
            "GUEST_BUSY", "已有客人正在点菜,先完成这单", code=29001,
            extra={"session_id": str(active.id)},  # 客户端据此恢复会话
        )
    # 客人:优先用 encounter 锁定的;无则随机
    guest = guest_service._guest_by_key(player.guest_encounter_key) if player.guest_encounter_key else None
    if guest is None:
        guest = guest_service._pick_guest()
        player.guest_encounter_key = guest["key"]
    menu = _menu(db, player)
    if not menu:
        raise AppError("NO_CROP", "当前没有可售的菜", code=21005)
    reply = await _ask_start(db, player, guest, menu, cfg)
    s = AiGuestSession(
        player_id=player.id,
        guest_key=guest["key"],
        guest_name=guest["name"],
        mode="order",
        status="bargaining",
        order_items={cid: 1 for cid in reply["items"]},
        order_total=reply["total_price"],
        turns=1,
        last_mood="calm",
    )
    db.add(s)
    db.flush()
    db.add(AiGuestMessage(session_id=s.id, role="guest", content=reply["raw_text"], reply=reply))
    db.commit()
    return {
        "session_id": str(s.id),
        "guest_key": guest["key"],
        "guest_name": guest["name"],
        "guest_age": guest.get("age"),
        "avatar_url": guest_service._avatar_url(guest),
        "raw_text": reply["raw_text"],
        "items": reply["items"],
        "total_price": reply["total_price"],
        "menu": menu,
    }


async def chat_or_start_order(db: Session, player: Player, session_id: str | None, message: str) -> dict:
    """融合接口:首次调用(无 session_id)自动创建会话+AI 点单;后续调用(带 session_id)多轮对话。

    前端只调这一个接口即可完成整个点菜流程:
    - 无 session_id → 走 start 逻辑(创建会话 + AI 点单),返回含 session_id
    - 有 session_id → 走 chat 逻辑(多轮对话)
    """
    if not session_id:
        return await start_order(db, player)
    return await chat_order(db, player, session_id, message)


async def chat_order(db: Session, player: Player, session_id: str, message: str) -> dict:
    """多轮对话:保持上下文,AI 返回 {raw_text, emotion, is_complete}。"""
    s = _get_session(db, player, session_id)
    _check_bargaining(s)
    message = (message or "").strip()
    if not message:
        raise AppError("INVALID_PARAMS", "消息不能为空", code=10001)
    cfg = order_config(db)
    guest = guest_service._guest_by_key(s.guest_key) or {}
    menu = _menu(db, player)
    history = [
        {"role": m.role, "content": m.content}
        for m in db.query(AiGuestMessage)
        .filter(AiGuestMessage.session_id == s.id)
        .order_by(AiGuestMessage.created_at)
        .all()
    ]
    db.add(AiGuestMessage(session_id=s.id, role="user", content=message))
    db.flush()
    reply = await _ask_chat(db, player, guest, menu, history, message, cfg)
    db.add(AiGuestMessage(session_id=s.id, role="guest", content=reply["raw_text"], reply=reply))
    s.last_mood = reply["emotion"]
    s.turns += 1
    out = {**reply, "status": s.status}
    # 极限 4 轮:超了强制失败
    if s.turns >= cfg["order.max_turns"] and not reply["is_complete"]:
        reply["emotion"] = "sad"
        reply["is_complete"] = True
        reply["is_right"] = False
        out = {**reply, "status": "closed", "closed_reason": "max_turns"}
        _finish(db, player, s, "closed")
    elif reply["is_complete"]:
        # 成交判定:is_right 由服务端在 confirm 时权威判定;这里先标记待确认
        out["is_right"] = None
        out["need_confirm"] = True
    db.commit()
    return out


def confirm_order(db: Session, player: Player, session_id: str, items: list[dict], total_price: int) -> dict:
    """玩家确认成交:服务端权威校验 items/price → 成交扣菜+加金币。"""
    s = _get_session(db, player, session_id)
    _check_bargaining(s)
    if not items:
        raise AppError("INVALID_PARAMS", "请选择要卖的菜", code=10001)
    # 服务端权威:校验库存 + 重算价格
    settings = shop_service.get_settings(db)
    season = shop_service.current_season(db, player)
    expected_total = 0
    for it in items:
        crop = db.get(Crop, uuid.UUID(it["crop_id"]))
        if not crop:
            raise AppError("CROP_NOT_FOUND", "作物不存在", code=21005)
        qty = int(it["quantity"])
        row = (
            db.query(CropStorage)
            .filter(CropStorage.player_id == player.id, CropStorage.crop_id == crop.id)
            .first()
        )
        have = (row.quantity if row else 0) + (row.wilted_quantity if row else 0)
        if have < qty:
            # 没菜了 → 失望结束,不结算
            s.is_right = False
            s.last_mood = "sad"
            _finish(db, player, s, "closed")
            db.commit()
            return {
                "is_right": False,
                "is_complete": True,
                "emotion": "sad",
                "raw_text": "啊,这道菜没有了啊……那算了。",
                "status": "closed",
                "closed_reason": "no_stock",
            }
        expected_total += shop_service._crop_price(crop, settings, season) * qty
    # 价格校验:玩家提交的总价必须等于服务端重算价(防作弊)
    if total_price != expected_total:
        s.is_right = False
        s.last_mood = "sad"
        _finish(db, player, s, "closed")
        db.commit()
        return {
            "is_right": False,
            "is_complete": True,
            "emotion": "sad",
            "raw_text": "价格不对吧?我再算算……",
            "status": "closed",
            "closed_reason": "price_mismatch",
        }
    # 原子终结 + 结算
    if not _try_finish(db, s, "done"):
        raise AppError("GUEST_CLOSED", "会话已结束,无法重复成交", code=29004)
    s.is_right = True
    s.last_mood = "happy"
    settle = _settle_order(db, player, s, items)
    _finish(db, player, s, "done")
    db.commit()
    return {
        "is_right": True,
        "is_complete": True,
        "emotion": "happy",
        "raw_text": "成交!谢谢摊主!",
        "status": "done",
        "settle": settle,
    }


def cancel_order(db: Session, player: Player, session_id: str) -> dict:
    s = _get_session(db, player, session_id)
    _check_bargaining(s)
    _finish(db, player, s, "cancelled")
    db.commit()
    return {"status": "cancelled"}


def get_order(db: Session, player: Player, session_id: str) -> dict:
    s = _get_session(db, player, session_id)
    guest = guest_service._guest_by_key(s.guest_key) or {}
    snap = {
        "session_id": str(s.id),
        "guest_key": s.guest_key,
        "guest_name": s.guest_name,
        "guest_age": guest.get("age"),
        "avatar_url": guest_service._avatar_url(guest) if guest else "",
        "emotion": s.last_mood,
        "status": s.status,
        "turns": s.turns,
        "order_items": s.order_items,
        "order_total": s.order_total,
        "is_right": s.is_right,
        "finished_at": s.finished_at.isoformat() if s.finished_at else None,
    }
    snap["history"] = [
        {"role": m.role, "content": m.content}
        for m in db.query(AiGuestMessage)
        .filter(AiGuestMessage.session_id == s.id)
        .order_by(AiGuestMessage.created_at)
        .all()
    ]
    return snap
