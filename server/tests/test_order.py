"""AI 客人点菜购买测试(mock LLM,不依赖真实上游):start/chat/confirm/结算/4轮上限。"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _reg(client, name):
    r = client.post("/v1/auth/register", json={"name": name, "password": "pass123456"}).json()
    assert r["code"] == 0
    client.post("/v1/player/tutorial/complete", headers={"Authorization": f"Bearer {r['data']['token']}"})
    return {"Authorization": f"Bearer {r['data']['token']}"}


def _harvest_rice(client, h):
    """种一株水稻并收获,让收成仓有货。"""
    for _ in range(30):
        cal = client.get("/v1/calendar/current", headers=h).json()["data"]
        if 5 <= cal["term_index"] <= 8:
            break
        client.post("/v1/debug/term/advance", headers=h)
    shop = client.get("/v1/shop/items", headers=h).json()["data"]["items"]
    seed = next(i for i in shop if i["code"] == "seed_shuidao")
    client.post(f"/v1/shop/items/{seed['item_id']}/buy", json={"quantity": 1}, headers=h)
    st = client.get("/v1/farm/state", headers=h).json()["data"]
    pid = st["plots"][0]["plot_id"]
    client.post(f"/v1/farm/plots/{pid}/sow", json={"crop_id": seed["effect"]["crop_id"]}, headers=h)
    client.post("/v1/debug/grow", json={"plot_id": pid}, headers=h)
    client.post(f"/v1/farm/plots/{pid}/harvest", headers=h)
    return seed["effect"]["crop_id"]


def _mock_chat(monkeypatch, content):
    from app.services import ai_service

    async def fake_chat(db, player, payload, **kwargs):
        return {"choices": [{"message": {"content": content}}], "usage": {}}

    monkeypatch.setattr(ai_service, "chat", fake_chat)


def _start(client, h):
    r = client.post("/v1/shop/order/start", headers=h).json()
    assert r["code"] == 0, r
    return r["data"]


# ---------- start ----------

def test_start_order_returns_guest_and_menu(client, monkeypatch):
    """start 返回客人+菜单+AI 点单。"""
    h = _reg(client, "order_s1")
    _harvest_rice(client, h)
    _mock_chat(
        monkeypatch,
        '{"raw_text": "我想买点水稻", "items": ["<crop_id>"], "total_price": 10}',
    )
    d = _start(client, h)
    assert d["status"] == "bargaining" if "status" in d else True
    assert d["guest_name"] in ("王奶奶", "陈大厨", "小美")
    assert d["guest_age"] in (68, 45, 22)
    assert d["avatar_url"].startswith("/v1/assets/images/animals/")
    assert d["raw_text"]
    assert "menu" in d and len(d["menu"]) > 0
    assert d["total_price"] >= 1


def test_start_order_requires_login(client):
    """未登录 → 401。"""
    r = client.post("/v1/shop/order/start")
    assert r.status_code == 401


# ---------- chat 多轮 ----------

def test_chat_order_keeps_context(client, monkeypatch):
    """多轮对话保持上下文。"""
    h = _reg(client, "order_chat1")
    _harvest_rice(client, h)
    _mock_chat(
        monkeypatch,
        '{"raw_text": "我想买点水稻", "items": ["<crop_id>"], "total_price": 10}',
    )
    d = _start(client, h)
    _mock_chat(
        monkeypatch,
        '{"raw_text": "那来一份吧", "emotion": "happy", "is_complete": false}',
    )
    r = client.post(
        f"/v1/shop/order/{d['session_id']}/chat", json={"message": "好的"}, headers=h
    ).json()
    assert r["code"] == 0
    data = r["data"]
    assert data["emotion"] == "happy" and data["is_complete"] is False
    assert data["status"] == "bargaining"
    # 快照含历史
    snap = client.get(f"/v1/shop/order/{d['session_id']}", headers=h).json()["data"]
    assert len(snap["history"]) >= 3  # 开场+玩家+回复


def test_chat_order_4_turns_fail(client, monkeypatch):
    """4 轮后仍错误 → emotion=sad, is_complete=true, is_right=false。"""
    from app.core.db import SessionLocal
    from app.services.order_service import save_order_config

    with SessionLocal() as db:
        save_order_config(db, {"order.max_turns": 2})
    try:
        h = _reg(client, "order_turns")
        _harvest_rice(client, h)
        _mock_chat(
            monkeypatch,
            '{"raw_text": "我想买点水稻", "items": ["<crop_id>"], "total_price": 10}',
        )
        d = _start(client, h)  # turns=1
        _mock_chat(
            monkeypatch,
            '{"raw_text": "还是这个", "emotion": "confused", "is_complete": false}',
        )
        r = client.post(
            f"/v1/shop/order/{d['session_id']}/chat", json={"message": "再聊聊"}, headers=h
        ).json()
        data = r["data"]
        assert data["status"] == "closed" and data["closed_reason"] == "max_turns"
        assert data["emotion"] == "sad" and data["is_complete"] is True
        assert data["is_right"] is False
    finally:
        with SessionLocal() as db:
            save_order_config(db, {"order.max_turns": 4})


# ---------- confirm 成交 ----------

def test_confirm_order_correct_settles(client, monkeypatch):
    """正确成交 → 扣菜+加金币。"""
    h = _reg(client, "order_ok")
    crop_id = _harvest_rice(client, h)
    _mock_chat(
        monkeypatch,
        f'{{"raw_text": "我想买点水稻", "items": ["{crop_id}"], "total_price": 10}}',
    )
    d = _start(client, h)
    before = client.get("/v1/player/me", headers=h).json()["data"]["coins"]
    # 服务端重算价
    shop = client.get("/v1/shop/state", headers=h).json()["data"]
    crop_quote = next(c for c in shop["crop_quotes"] if c["crop_id"] == crop_id)
    price = crop_quote["sell_price"]
    r = client.post(
        f"/v1/shop/order/{d['session_id']}/confirm",
        json={"items": [{"crop_id": crop_id, "quantity": 1}], "total_price": price},
        headers=h,
    ).json()
    assert r["code"] == 0
    data = r["data"]
    assert data["is_right"] is True and data["is_complete"] is True
    assert data["status"] == "done"
    assert data["settle"]["total_price"] == price
    after = client.get("/v1/player/me", headers=h).json()["data"]["coins"]
    assert after == before + price


def test_confirm_order_wrong_price_no_settle(client, monkeypatch):
    """价格错误 → 不结算。"""
    h = _reg(client, "order_wrong")
    crop_id = _harvest_rice(client, h)
    _mock_chat(
        monkeypatch,
        f'{{"raw_text": "我想买点水稻", "items": ["{crop_id}"], "total_price": 10}}',
    )
    d = _start(client, h)
    before = client.get("/v1/player/me", headers=h).json()["data"]["coins"]
    r = client.post(
        f"/v1/shop/order/{d['session_id']}/confirm",
        json={"items": [{"crop_id": crop_id, "quantity": 1}], "total_price": 99999},
        headers=h,
    ).json()
    assert r["code"] == 0
    data = r["data"]
    assert data["is_right"] is False and data["is_complete"] is True
    assert data["status"] == "closed" and data["closed_reason"] == "price_mismatch"
    after = client.get("/v1/player/me", headers=h).json()["data"]["coins"]
    assert after == before  # 不结算


def test_confirm_order_no_stock_no_settle(client, monkeypatch):
    """没菜了 → emotion=sad, is_complete=true, is_right=false, 不扣不加。"""
    h = _reg(client, "order_nostock")
    crop_id = _harvest_rice(client, h)
    _mock_chat(
        monkeypatch,
        f'{{"raw_text": "我想买点水稻", "items": ["{crop_id}"], "total_price": 10}}',
    )
    d = _start(client, h)
    before = client.get("/v1/player/me", headers=h).json()["data"]["coins"]
    # 提交远超库存的数量
    r = client.post(
        f"/v1/shop/order/{d['session_id']}/confirm",
        json={"items": [{"crop_id": crop_id, "quantity": 999}], "total_price": 99999},
        headers=h,
    ).json()
    assert r["code"] == 0
    data = r["data"]
    assert data["is_right"] is False and data["is_complete"] is True
    assert data["emotion"] == "sad"
    assert data["status"] == "closed" and data["closed_reason"] == "no_stock"
    after = client.get("/v1/player/me", headers=h).json()["data"]["coins"]
    assert after == before  # 不扣不加


# ---------- cancel / 锁定 ----------

def test_cancel_order(client):
    h = _reg(client, "order_cancel")
    _harvest_rice(client, h)
    d = _start(client, h)
    r = client.post(f"/v1/shop/order/{d['session_id']}/cancel", headers=h).json()
    assert r["code"] == 0 and r["data"]["status"] == "cancelled"


def test_order_guest_locked(client, monkeypatch):
    """会话结束前锁定同一位客人(单活跃会话)。"""
    h = _reg(client, "order_lock")
    _harvest_rice(client, h)
    _mock_chat(
        monkeypatch,
        '{"raw_text": "我想买点水稻", "items": ["<crop_id>"], "total_price": 10}',
    )
    d1 = _start(client, h)
    # 已有活跃点菜会话 → GUEST_BUSY
    r = client.post("/v1/shop/order/start", headers=h).json()
    assert r["code"] == 29001


def test_fused_chat_or_start(client, monkeypatch):
    """融合接口:首次调用(无 session_id)自动创建会话+AI 点单;后续(带 session_id)多轮对话。"""
    h = _reg(client, "order_fused")
    _harvest_rice(client, h)
    # 首次调用:无 session_id → 自动创建会话 + AI 点单
    _mock_chat(
        monkeypatch,
        '{"raw_text": "我想买点水稻", "items": ["<crop_id>"], "total_price": 10}',
    )
    r = client.post("/v1/shop/order/chat", json={"message": "你好"}, headers=h).json()
    assert r["code"] == 0, r
    d = r["data"]
    assert d["session_id"]  # 返回 session_id
    assert d["guest_name"] in ("王奶奶", "陈大厨", "小美")
    assert d["raw_text"] and d["items"] and d["total_price"] >= 1
    # 后续调用:带 session_id → 多轮对话
    _mock_chat(
        monkeypatch,
        '{"raw_text": "那来一份吧", "emotion": "happy", "is_complete": false}',
    )
    r = client.post(
        "/v1/shop/order/chat",
        json={"message": "好的", "session_id": d["session_id"]},
        headers=h,
    ).json()
    assert r["code"] == 0
    assert r["data"]["emotion"] == "happy" and r["data"]["is_complete"] is False
    assert r["data"]["status"] == "bargaining"


def test_guest_prompt_pool_random_and_fallback():
    """身份模板池:加载/占位符替换/随机性/池空兜底 order_prompt。"""
    from app.services import guest_service, order_service

    pool = order_service.load_prompts()
    assert len(pool) >= 1  # 模板池非空
    guest = guest_service._guest_by_key("thrifty_granny")
    # 占位符全部替换
    p = order_service._pick_prompt(guest)
    assert "{name}" not in p and "{age}" not in p and "{personality}" not in p
    assert guest["name"] in p and str(guest["age"]) in p
    # 随机性:多次调用应出现不同模板
    seen = {order_service._pick_prompt(guest) for _ in range(20)}
    assert len(seen) >= 2
    # 池空兜底 order_prompt
    orig = order_service._PROMPTS_PATH
    order_service._PROMPTS_PATH = orig.with_name("nonexistent.json")
    try:
        p2 = order_service._pick_prompt(guest)
        assert "节俭" in p2 or "老奶奶" in p2
    finally:
        order_service._PROMPTS_PATH = orig
