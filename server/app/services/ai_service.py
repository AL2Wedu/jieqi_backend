"""AI 大模型转发服务:OpenAI 兼容接口代理 + 每用户用量跟踪。

- 上游:任意 OpenAI 兼容服务(DeepSeek / 通义 / 智谱 / OpenAI 均可)
- 配置存 game_config(管理后台可改):ai.enabled / ai.base_url / ai.api_key / ai.model
- 用量:每请求记录 prompt/completion/total tokens 到 ai_usage(按玩家×模型×日聚合)
"""
from datetime import date

import httpx
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import AiUsage, GameConfig, Player, User

AI_KEYS = ("ai.enabled", "ai.base_url", "ai.api_key", "ai.model")
# 请求字段 → 存储键 映射
AI_FIELD_MAP = {
    "enabled": "ai.enabled",
    "base_url": "ai.base_url",
    "api_key": "ai.api_key",
    "model": "ai.model",
}


def get_ai_config(db: Session) -> dict:
    cfgs = {
        c.key: c.value
        for c in db.query(GameConfig).filter(GameConfig.key.in_(AI_KEYS)).all()
    }
    return {
        "enabled": bool(cfgs.get("ai.enabled", False)),
        "base_url": str(cfgs.get("ai.base_url", "")).rstrip("/"),
        "api_key": str(cfgs.get("ai.api_key", "")),
        "model": str(cfgs.get("ai.model", "deepseek-chat")),
    }


def masked_config(db: Session) -> dict:
    cfg = get_ai_config(db)
    key = cfg["api_key"]
    cfg["api_key"] = (key[:4] + "****" + key[-4:]) if len(key) > 8 else ("****" if key else "")
    cfg["configured"] = bool(cfg["base_url"] and key)
    return cfg


def save_ai_config(db: Session, data: dict) -> dict:
    for field, storage_key in AI_FIELD_MAP.items():
        if field not in data:
            continue
        value = data[field]
        cfg = db.query(GameConfig).filter(GameConfig.key == storage_key).first()
        if cfg:
            cfg.value = value
        else:
            db.add(GameConfig(key=storage_key, value=value))
    db.commit()
    return masked_config(db)


def _record_usage(db: Session, player: Player, model: str, usage: dict) -> None:
    today = date.today().isoformat()
    row = (
        db.query(AiUsage)
        .filter(
            AiUsage.player_id == player.id,
            AiUsage.model == model,
            AiUsage.stat_date == today,
        )
        .first()
    )
    if not row:
        row = AiUsage(
            player_id=player.id,
            model=model,
            stat_date=today,
            requests=0,
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
        )
        db.add(row)
    row.requests = (row.requests or 0) + 1
    row.prompt_tokens += int(usage.get("prompt_tokens", 0) or 0)
    row.completion_tokens += int(usage.get("completion_tokens", 0) or 0)
    row.total_tokens += int(usage.get("total_tokens", 0) or 0)
    db.commit()


async def chat(db: Session, player: Player, payload: dict) -> dict:
    """OpenAI 兼容 /chat/completions 转发(透传请求体与响应,记录用量)。"""
    cfg = get_ai_config(db)
    if not cfg["enabled"]:
        raise AppError("AI_DISABLED", "AI 服务未启用", code=24001)
    if not cfg["base_url"] or not cfg["api_key"]:
        raise AppError("AI_NOT_CONFIGURED", "AI 服务器或 API Key 未配置", code=24002)
    model = str(payload.get("model") or cfg["model"])
    body = {k: v for k, v in payload.items() if k != "model"}
    body["model"] = model
    headers = {
        "Authorization": f"Bearer {cfg['api_key']}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{cfg['base_url']}/chat/completions", json=body, headers=headers
            )
    except httpx.HTTPError as e:
        raise AppError("AI_UPSTREAM_ERROR", f"AI 上游连接失败: {e}", code=24003)
    if resp.status_code != 200:
        raise AppError(
            "AI_UPSTREAM_ERROR",
            f"AI 上游返回错误: HTTP {resp.status_code} {resp.text[:200]}",
            code=24003,
        )
    data = resp.json()
    _record_usage(db, player, model, data.get("usage") or {})
    return data


async def list_models(db: Session) -> dict:
    """透传上游 /models(供客户端与管理后台选择模型)。"""
    cfg = get_ai_config(db)
    if not cfg["enabled"] or not cfg["base_url"] or not cfg["api_key"]:
        raise AppError("AI_NOT_CONFIGURED", "AI 服务未配置", code=24002)
    headers = {"Authorization": f"Bearer {cfg['api_key']}"}
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"{cfg['base_url']}/models", headers=headers)
    except httpx.HTTPError as e:
        raise AppError("AI_UPSTREAM_ERROR", f"AI 上游连接失败: {e}", code=24003)
    if resp.status_code != 200:
        raise AppError(
            "AI_UPSTREAM_ERROR",
            f"AI 上游返回错误: HTTP {resp.status_code} {resp.text[:200]}",
            code=24003,
        )
    data = resp.json()
    return {
        "models": [m.get("id") for m in data.get("data", []) if m.get("id")],
    }


def player_usage(db: Session, player: Player) -> dict:
    rows = (
        db.query(AiUsage)
        .filter(AiUsage.player_id == player.id)
        .order_by(AiUsage.stat_date.desc())
        .all()
    )
    by_day = [
        {
            "date": r.stat_date,
            "model": r.model,
            "requests": r.requests,
            "prompt_tokens": r.prompt_tokens,
            "completion_tokens": r.completion_tokens,
            "total_tokens": r.total_tokens,
        }
        for r in rows
    ]
    total = {
        "requests": sum(r["requests"] for r in by_day),
        "prompt_tokens": sum(r["prompt_tokens"] for r in by_day),
        "completion_tokens": sum(r["completion_tokens"] for r in by_day),
        "total_tokens": sum(r["total_tokens"] for r in by_day),
    }
    return {"total": total, "by_day": by_day}


def admin_usage(db: Session, page: int, page_size: int) -> dict:
    """全服每用户 AI 用量(按玩家聚合,总 token 降序)。"""
    total_users = (
        db.query(func.count(func.distinct(AiUsage.player_id))).scalar() or 0
    )
    rows = (
        db.query(
            Player.id,
            User.name,
            func.sum(AiUsage.requests),
            func.sum(AiUsage.prompt_tokens),
            func.sum(AiUsage.completion_tokens),
            func.sum(AiUsage.total_tokens),
        )
        .join(AiUsage, AiUsage.player_id == Player.id)
        .join(User, User.id == Player.user_id)
        .group_by(Player.id)
        .order_by(func.sum(AiUsage.total_tokens).desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    items = [
        {
            "player_id": str(pid),
            "name": name,
            "requests": int(reqs or 0),
            "prompt_tokens": int(pt or 0),
            "completion_tokens": int(ct or 0),
            "total_tokens": int(tt or 0),
        }
        for pid, name, reqs, pt, ct, tt in rows
    ]
    return {
        "items": items,
        "page": page,
        "page_size": page_size,
        "total": total_users,
    }
