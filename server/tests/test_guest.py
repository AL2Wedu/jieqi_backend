"""AI 客人议价出售测试(mock LLM,不依赖真实上游):会话/校验/状态机/结算/冷却。"""
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
    """种一株水稻并收获,让收成仓有货(推进到宜种窗 5-8,debug 催熟)。"""
    for _ in range(30):
        cal = client.get("/v1/calendar/current", headers=h).json()["data"]
        if 5 <= cal["term_index"] <= 8:
            break
        client.post("/v1/debug/term/advance", headers=h)
    shop = client.get("/v1/shop/items", headers=h).json()["data"]["items"]
    seed = next(i for i in shop if i["code"] == "seed_shuidao")
    r = client.post(f"/v1/shop/items/{seed['item_id']}/buy", json={"quantity": 1}, headers=h).json()
    assert r["code"] == 0
    st = client.get("/v1/farm/state", headers=h).json()["data"]
    pid = st["plots"][0]["plot_id"]
    r = client.post(
        f"/v1/farm/plots/{pid}/sow", json={"crop_id": seed["effect"]["crop_id"]}, headers=h
    ).json()
    assert r["code"] == 0, r
    r = client.post("/v1/debug/grow", json={"plot_id": pid}, headers=h).json()
    assert r["code"] == 0, r
    r = client.post(f"/v1/farm/plots/{pid}/harvest", headers=h).json()
    assert r["code"] == 0, r
    return {"crop_id": seed["effect"]["crop_id"], "pid": pid}


def _mock_chat(monkeypatch, content):
    from app.services import ai_service

    async def fake_chat(db, player, payload):
        return {"choices": [{"message": {"content": content}}], "usage": {}}

    monkeypatch.setattr(ai_service, "chat", fake_chat)


def _start(client, h, crop_id):
    r = client.post("/v1/shop/guest/start", json={"crop_id": crop_id}, headers=h).json()
    assert r["code"] == 0, r
    return r["data"]


# ---------- T1 表 ----------

def test_tables_exist(client):
    from app.core.db import SessionLocal
    from app.models import AiGuestMessage, AiGuestSession

    with SessionLocal() as db:
        s = AiGuestSession(
            player_id=uuid.uuid4(), crop_id=uuid.uuid4(), guest_key="k",
            guest_name="测试", base_price=10,
        )
        db.add(s)
        db.flush()
        db.add(AiGuestMessage(session_id=s.id, role="guest", content="你好"))
        db.commit()
        assert db.query(AiGuestSession).count() == 1
        assert db.query(AiGuestMessage).count() == 1


# ---------- T3 配置 ----------

def test_guest_config_defaults(client):
    from app.services.guest_service import guest_config

    with TestClient(app) as c:
        pass  # client 已启动
    from app.core.db import SessionLocal

    with SessionLocal() as db:
        cfg = guest_config(db)
        assert cfg["guest.enabled"] is True
        assert cfg["guest.max_turns"] == 8
        assert cfg["guest.price_floor"] == 0.5 and cfg["guest.price_ceil"] == 1.5


def test_pick_guest():
    from app.services.guest_service import _pick_guest, load_guests

    guests = load_guests()
    assert len(guests) == 3
    keys = {g["key"] for g in guests}
    assert "thrifty_granny" in keys and "foodie_chef" in keys
    for _ in range(5):
        assert _pick_guest()["key"] in keys


# ---------- T4 start ----------

def test_start_guest_flow(client):
    h = _reg(client, "guest_s1")
    crop = _harvest_rice(client, h)
    d = _start(client, h, crop["crop_id"])
    assert d["status"] == "bargaining"
    assert d["guest_name"] in ("王奶奶", "陈大厨", "小美")
    assert d["turns"] == 1
    assert d["offer"] >= 1
    assert 1 <= d["target_min"] <= d["target_max"]
    assert d["base_price"] > 0
    # 已有活跃会话 → GUEST_BUSY
    r = client.post("/v1/shop/guest/start", json={"crop_id": crop["crop_id"]}, headers=h).json()
    assert r["code"] == 29001
    # 收成仓无货 → NOT_ENOUGH_CROP
    h2 = _reg(client, "guest_empty")
    shop = client.get("/v1/shop/items", headers=h2).json()["data"]["items"]
    seed = next(i for i in shop if i["code"] == "seed_shuidao")
    r = client.post("/v1/shop/guest/start", json={"crop_id": seed["effect"]["crop_id"]}, headers=h2).json()
    assert r["code"] == 22007


# ---------- T5 上下文 ----------

def test_build_messages_truncation():
    from app.services.guest_service import _build_messages_impl
    from app.models import AiGuestSession, Crop
    import uuid as _uuid

    s = AiGuestSession(
        player_id=_uuid.uuid4(), crop_id=_uuid.uuid4(), guest_key="thrifty_granny",
        guest_name="王奶奶", base_price=10, target_min=6, target_max=9,
    )
    crop = Crop(id=_uuid.uuid4(), name="水稻", category="谷物", grow_seconds=1,
                yield_base=1, base_price=1, settings={})
    history = [{"role": "user" if i % 2 == 0 else "guest", "content": f"m{i}"} for i in range(20)]
    msgs = _build_messages_impl(s, crop, history, "老板便宜点", False, {"guest.context_messages": 6})
    assert msgs[0]["role"] == "system"
    assert "王奶奶" in msgs[0]["content"] and "水稻" in msgs[0]["content"]
    assert "6~9" in msgs[0]["content"]
    assert len(msgs) == 1 + 6 + 1  # system + 最近 6 条 + 当前消息
    assert msgs[-1]["content"] == "老板便宜点"
    assert msgs[1]["content"] == "m14"  # 只留最近 6 条


# ---------- T6 AI 校验管线 ----------

def test_validate_reply_clamps_and_defaults():
    from app.services.guest_service import _validate_reply
    from app.models import AiGuestSession, Crop
    import uuid as _uuid

    s = AiGuestSession(
        player_id=_uuid.uuid4(), crop_id=_uuid.uuid4(), guest_key="k",
        guest_name="王奶奶", base_price=10, target_min=6, target_max=9,
    )
    crop = Crop(
        id=_uuid.uuid4(), name="测试", category="谷物",
        grow_seconds=100, yield_base=1, base_price=10, settings={},  # 无 max_value → 不额外封顶
    )
    cfg = {"guest.price_floor": 0.5, "guest.price_ceil": 1.5}
    # offer 越界(天价 999)→ 截断到 15;mood 非法 → plain
    v = _validate_reply(
        {"reply_text": "就这价", "guest_name": "王奶奶", "mood": "rage", "offer": 999, "deal": False}, s, crop, cfg
    )
    assert v["offer"] == 15 and v["mood"] == "plain"
    # offer 过低 → 抬到 5
    v = _validate_reply(
        {"reply_text": "行吧", "guest_name": "王奶奶", "mood": "happy", "offer": 1, "deal": True}, s, crop, cfg
    )
    assert v["offer"] == 5 and v["deal"] is True
    # reply_text 为空 → 抛错(触发重试/兜底)
    with pytest.raises(ValueError):
        _validate_reply({"reply_text": " ", "offer": 8, "deal": False}, s, crop, cfg)


def test_ask_parse_retry_and_fallback(client, monkeypatch):
    """解析失败 → 重试 → 仍失败 → 兜底话术(会话不坏)。"""
    from app.services.guest_service import start_guest, chat_guest
    from app.core.db import SessionLocal
    from app.models import Player, User

    h = _reg(client, "guest_retry")
    crop = _harvest_rice(client, h)

    calls = {"n": 0}

    async def broken_chat(db, player, payload):
        calls["n"] += 1
        return {"choices": [{"message": {"content": "不是JSON"}}], "usage": {}}

    from app.services import ai_service
    monkeypatch.setattr(ai_service, "chat", broken_chat)

    with SessionLocal() as db:
        u = db.query(User).filter(User.name == "guest_retry").first()
        player = db.query(Player).filter(Player.user_id == u.id).first()
        s = start_guest(db, player, crop["crop_id"])
        import asyncio

        r = asyncio.run(chat_guest(db, player, s["session_id"], "5块卖吗?"))
        # 兜底回复:deal=False 对话继续
        assert r["deal"] is False and r["status"] == "bargaining"
        assert r["reply_text"]
    # 默认重试 1 次 → 共调 2 次
    assert calls["n"] == 2


# ---------- T7 chat 状态机 ----------

def test_chat_deal_false_continues(client, monkeypatch):
    h = _reg(client, "guest_chat1")
    crop = _harvest_rice(client, h)
    d = _start(client, h, crop["crop_id"])
    _mock_chat(
        monkeypatch,
        '{"reply_text": "再加点,12块行不?", "guest_name": "王奶奶", "mood": "confused", "offer": 12, "deal": false}',
    )
    r = client.post(
        f"/v1/shop/guest/{d['session_id']}/chat", json={"message": "6块"}, headers=h
    ).json()
    assert r["code"] == 0
    data = r["data"]
    assert data["status"] == "bargaining" and data["deal"] is False
    assert data["offer"] == 12 and data["mood"] == "confused"
    # 会话仍在谈判
    snap = client.get(f"/v1/shop/guest/{d['session_id']}", headers=h).json()["data"]
    assert snap["status"] == "bargaining" and len(snap["history"]) == 3  # 开场+玩家+回复


def test_chat_deal_true_settles(client, monkeypatch):
    h = _reg(client, "guest_chat2")
    crop = _harvest_rice(client, h)
    d = _start(client, h, crop["crop_id"])
    before = client.get("/v1/player/me", headers=h).json()["data"]["coins"]
    offer = 12  # 落在服务端校验区间内
    _mock_chat(
        monkeypatch,
        f'{{"reply_text": "行,成交!", "guest_name": "王奶奶", "mood": "happy", "offer": {offer}, "deal": true}}',
    )
    r = client.post(
        f"/v1/shop/guest/{d['session_id']}/chat", json={"message": "那就成交吧"}, headers=h
    ).json()
    assert r["code"] == 0
    data = r["data"]
    assert data["status"] == "done" and data["deal"] is True
    # 成交价 = 服务端校验后的 offer(≤ 1.5×市场价)
    assert data["settle"]["price"] == offer
    after = client.get("/v1/player/me", headers=h).json()["data"]["coins"]
    assert after == before + offer
    # 会话已结束,再聊 → GUEST_CLOSED
    r = client.post(
        f"/v1/shop/guest/{d['session_id']}/chat", json={"message": "还在吗"}, headers=h
    ).json()
    assert r["code"] == 29004


def test_chat_max_turns_closed(client, monkeypatch):
    from app.core.db import SessionLocal
    from app.services.guest_service import save_guest_config

    with SessionLocal() as db:
        save_guest_config(db, {"guest.max_turns": 2})
    try:
        h = _reg(client, "guest_turns")
        crop = _harvest_rice(client, h)
        d = _start(client, h, crop["crop_id"])  # turns=1
        _mock_chat(
            monkeypatch,
            '{"reply_text": "还是这个价", "guest_name": "王奶奶", "mood": "sad", "offer": 7, "deal": false}',
        )
        r = client.post(
            f"/v1/shop/guest/{d['session_id']}/chat", json={"message": "7块"}, headers=h
        ).json()
        data = r["data"]
        assert data["status"] == "closed" and data["closed_reason"] == "max_turns"
        assert data["deal"] is False  # 不自动成交
    finally:
        with SessionLocal() as db:
            save_guest_config(db, {"guest.max_turns": 8})


# ---------- T8 accept / cancel ----------

def test_accept_settles_at_offer(client):
    h = _reg(client, "guest_acc")
    crop = _harvest_rice(client, h)
    d = _start(client, h, crop["crop_id"])
    before = client.get("/v1/player/me", headers=h).json()["data"]["coins"]
    offer = d["offer"]
    r = client.post(f"/v1/shop/guest/{d['session_id']}/accept", headers=h).json()
    assert r["code"] == 0
    assert r["data"]["status"] == "done"
    assert r["data"]["settle"]["price"] == offer
    after = client.get("/v1/player/me", headers=h).json()["data"]["coins"]
    assert after == before + offer


def test_cancel_no_settle(client):
    h = _reg(client, "guest_cancel")
    crop = _harvest_rice(client, h)
    d = _start(client, h, crop["crop_id"])
    before = client.get("/v1/player/me", headers=h).json()["data"]["coins"]
    r = client.post(f"/v1/shop/guest/{d['session_id']}/cancel", headers=h).json()
    assert r["code"] == 0 and r["data"]["status"] == "cancelled"
    assert client.get("/v1/player/me", headers=h).json()["data"]["coins"] == before


def test_guest_not_found(client):
    h = _reg(client, "guest_nf")
    r = client.post(f"/v1/shop/guest/{uuid.uuid4()}/cancel", headers=h).json()
    assert r["code"] == 29003


# ---------- T9 冷却 ----------

def test_cooldown_blocks_start(client):
    from app.core.db import SessionLocal
    from app.services.guest_service import save_guest_config

    with SessionLocal() as db:
        save_guest_config(db, {"guest.cooldown_seconds": 600})
    try:
        h = _reg(client, "guest_cool")
        crop = _harvest_rice(client, h)
        d = _start(client, h, crop["crop_id"])
        client.post(f"/v1/shop/guest/{d['session_id']}/cancel", headers=h)
        # 冷却窗口内再开 → GUEST_COOLDOWN
        r = client.post("/v1/shop/guest/start", json={"crop_id": crop["crop_id"]}, headers=h).json()
        assert r["code"] == 29002
    finally:
        with SessionLocal() as db:
            save_guest_config(db, {"guest.cooldown_seconds": 30})


# ---------- T10 encounter 随机客人 + 锁定 ----------

def test_encounter_returns_guest_with_avatar(client):
    """encounter 返回随机客人(名称+头像 URL),头像指向 animals 素材。"""
    h = _reg(client, "guest_enc1")
    r = client.get("/v1/shop/guest/encounter", headers=h).json()
    assert r["code"] == 0
    d = r["data"]
    assert d["guest_key"] in ("thrifty_granny", "foodie_chef", "curious_student")
    assert d["guest_name"] in ("王奶奶", "陈大厨", "小美")
    assert d["avatar_url"].startswith("/v1/assets/images/animals/")
    assert d["avatar_url"].endswith("?w=128")
    assert d["locked"] is False


def test_encounter_locks_until_session_ends(client, monkeypatch):
    """锁定:会话结束前 encounter 返回同一位;成交后解锁,重新随机。"""
    h = _reg(client, "guest_enc2")
    crop = _harvest_rice(client, h)
    # 第一次 encounter → 锁定
    d1 = client.get("/v1/shop/guest/encounter", headers=h).json()["data"]
    assert d1["locked"] is False
    # 再 encounter → 同一位(锁定中)
    d2 = client.get("/v1/shop/guest/encounter", headers=h).json()["data"]
    assert d2["guest_key"] == d1["guest_key"]
    assert d2["guest_name"] == d1["guest_name"]
    assert d2["locked"] is True
    # start 用锁定的客人(遇到谁就是谁)
    s = _start(client, h, crop["crop_id"])
    assert s["guest_key"] == d1["guest_key"]
    # 成交 → 解锁
    _mock_chat(
        monkeypatch,
        f'{{"reply_text": "行,成交!", "guest_name": "{d1["guest_name"]}", "mood": "happy", "offer": {s["offer"]}, "deal": true}}',
    )
    r = client.post(
        f"/v1/shop/guest/{s['session_id']}/chat", json={"message": "成交"}, headers=h
    ).json()
    assert r["code"] == 0 and r["data"]["status"] == "done"
    # 解锁后 encounter 重新随机(可能同一位,但 locked=False 且不再锁定)
    d3 = client.get("/v1/shop/guest/encounter", headers=h).json()["data"]
    assert d3["locked"] is False


def test_encounter_unlock_on_cancel(client):
    """赶客(cancel)同样解锁。"""
    h = _reg(client, "guest_enc3")
    crop = _harvest_rice(client, h)
    d1 = client.get("/v1/shop/guest/encounter", headers=h).json()["data"]
    s = _start(client, h, crop["crop_id"])
    assert s["guest_key"] == d1["guest_key"]
    r = client.post(f"/v1/shop/guest/{s['session_id']}/cancel", headers=h).json()
    assert r["code"] == 0 and r["data"]["status"] == "cancelled"
    d2 = client.get("/v1/shop/guest/encounter", headers=h).json()["data"]
    assert d2["locked"] is False


def test_encounter_requires_login(client):
    """未登录 → 401。"""
    r = client.get("/v1/shop/guest/encounter")
    assert r.status_code == 401


# ---------- 修复回归:议价不超 max_value ----------

def test_guest_offer_capped_by_max_value():
    """客人议价成交价不突破作物单株卖价上限(max_value)。"""
    import uuid
    from app.models import Crop
    from app.services.guest_service import _validate_reply
    from app.models import AiGuestSession

    # base_price 已是 max_value 封顶价(与 shop_service._crop_price 一致):白菜 max_value=30 → base=30
    crop = Crop(
        id=uuid.uuid4(), name="白菜", category="蔬菜",
        grow_seconds=100, yield_base=1, base_price=100,
        settings={"max_value": 30},
    )
    s = AiGuestSession(
        id=uuid.uuid4(), player_id=uuid.uuid4(), crop_id=crop.id,
        guest_key="k", guest_name="测试", base_price=30,
        offer=0, target_min=15, target_max=45,
    )
    cfg = {"guest.price_floor": 0.5, "guest.price_ceil": 1.5}
    # 客户/AI 报 offer=45(1.5×30),但 max_value=30 → 应收敛到 30
    r = _validate_reply({"reply_text": "就这个价", "mood": "happy", "offer": 45, "deal": True}, s, crop, cfg)
    assert r["offer"] == 30, r  # 不超单株上限
    # 报价低于 floor 时仍被抬到 floor(15)
    r2 = _validate_reply({"reply_text": "再低点", "mood": "sad", "offer": 1, "deal": False}, s, crop, cfg)
    assert r2["offer"] == 15, r2
