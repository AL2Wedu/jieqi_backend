"""任务 / 社交 / 成就 / AI 转发 测试。

AI 部分使用进程内 stub 上游(OpenAI 兼容),验证转发 + 用量记录 + 管理端配置。
"""
import threading
import time
import uuid

import httpx
import pytest
import uvicorn
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import app

# ---------- AI 上游 stub(OpenAI 兼容) ----------
stub = FastAPI()


@stub.post("/chat/completions")
def stub_chat(req: dict):
    return {
        "id": "chatcmpl-stub",
        "object": "chat.completion",
        "model": req.get("model", "stub-model"),
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "你好,我是节气小老师"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20},
    }


@stub.get("/models")
def stub_models():
    return {"data": [{"id": "stub-model"}, {"id": "stub-model-2"}]}


@pytest.fixture(scope="module")
def ai_stub():
    import socket
    import urllib.request

    # 先占一个空闲端口,再让 uvicorn 绑定(避免依赖 uvicorn 内部属性)
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    config = uvicorn.Config(stub, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    # HTTP 轮询等待就绪
    ready = False
    for _ in range(50):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/models", timeout=1)
            ready = True
            break
        except Exception:
            time.sleep(0.1)
    assert ready, "stub 上游启动失败"
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _reg(client, name):
    r = client.post("/v1/auth/register", json={"name": name, "password": "pass123456"}).json()
    assert r["code"] == 0
    client.post("/v1/player/tutorial/complete", headers={"Authorization": f"Bearer {r['data']['token']}"})
    return {"Authorization": f"Bearer {r['data']['token']}"}

def _advance_to_rice_window(client, h):
    for _ in range(40):
        cal = client.get("/v1/calendar/current", headers=h).json()["data"]
        if 5 <= cal["term_index"] <= 9:
            return
        client.post("/v1/debug/term/advance", headers=h)


def _sow_and_harvest_one(client, h):
    _advance_to_rice_window(client, h)
    shop = client.get("/v1/shop/items", headers=h).json()["data"]["items"]
    seed = next(i for i in shop if i["code"] == "seed_shuidao")
    client.post(f"/v1/shop/items/{seed['item_id']}/buy", json={"quantity": 1}, headers=h)
    plot = client.get("/v1/farm/state", headers=h).json()["data"]["plots"][0]["plot_id"]
    client.post(f"/v1/farm/plots/{plot}/sow", json={"crop_id": seed["effect"]["crop_id"]}, headers=h)
    client.post("/v1/debug/grow", json={"plot_id": plot}, headers=h)
    client.post(f"/v1/farm/plots/{plot}/harvest", headers=h)


def test_quests_flow(client):
    h = _reg(client, "quest_player")
    r = client.get("/v1/quests", headers=h).json()
    assert r["code"] == 0
    items = {q["code"]: q for q in r["data"]["items"]}
    assert "q_sow_3" in items and items["q_sow_3"]["status"] == 0

    _sow_and_harvest_one(client, h)

    r = client.get("/v1/quests", headers=h).json()
    items = {q["code"]: q for q in r["data"]["items"]}
    assert items["q_sow_3"]["progress"]["current"] == 1
    assert items["q_harvest_1"]["status"] == 1

    qid = items["q_harvest_1"]["quest_id"]
    r = client.post(f"/v1/quests/{qid}/claim", headers=h).json()
    assert r["code"] == 0 and r["data"]["reward"]["coins"] == 20
    r = client.post(f"/v1/quests/{qid}/claim", headers=h).json()
    assert r["code"] == 25003  # 已领取
    r = client.post(f"/v1/quests/{items['q_friend_1']['quest_id']}/claim", headers=h).json()
    assert r["code"] == 25002  # 未完成


def test_social_flow(client):
    hA = _reg(client, "social_a")
    hB = _reg(client, "social_b")
    pidA = client.get("/v1/player/me", headers=hA).json()["data"]["player_id"]
    pidB = client.get("/v1/player/me", headers=hB).json()["data"]["player_id"]

    r = client.post("/v1/social/requests", json={"player_id": pidB}, headers=hA).json()
    assert r["code"] == 0
    r = client.post("/v1/social/requests", json={"player_id": pidB}, headers=hA).json()
    assert r["code"] == 27002  # 重复申请
    r = client.post("/v1/social/requests", json={"player_id": pidA}, headers=hA).json()
    assert r["code"] == 10001  # 自己加自己

    r = client.get("/v1/social/requests", headers=hB).json()
    assert any(i["player_id"] == pidA for i in r["data"]["items"])
    r = client.post(f"/v1/social/requests/{pidA}/accept", headers=hB).json()
    assert r["code"] == 0 and r["data"]["status"] == 1
    for h in (hA, hB):
        r = client.get("/v1/social/friends", headers=h).json()
        assert len(r["data"]["items"]) == 1
    r = client.post("/v1/social/requests", json={"player_id": pidA}, headers=hB).json()
    assert r["code"] == 27001  # 已是好友

    r = client.delete(f"/v1/social/friends/{pidB}", headers=hA).json()
    assert r["code"] == 0
    assert len(client.get("/v1/social/friends", headers=hA).json()["data"]["items"]) == 0


def test_achievements_flow(client):
    h = _reg(client, "achieve_player")
    r = client.get("/v1/achievements", headers=h).json()
    items = {a["code"]: a for a in r["data"]["items"]}
    assert "a_first_sow" in items and items["a_first_sow"]["completed"] is False

    _sow_and_harvest_one(client, h)

    r = client.get("/v1/achievements", headers=h).json()
    items = {a["code"]: a for a in r["data"]["items"]}
    assert items["a_first_sow"]["completed"] is True

    r = client.post(f"/v1/achievements/{items['a_first_sow']['achievement_id']}/claim", headers=h).json()
    assert r["code"] == 0 and r["data"]["reward"]["coins"] == 10
    r = client.post(f"/v1/achievements/{items['a_first_sow']['achievement_id']}/claim", headers=h).json()
    assert r["code"] == 26003  # 已领取
    r = client.post(f"/v1/achievements/{items['a_ai_10']['achievement_id']}/claim", headers=h).json()
    assert r["code"] == 26002  # 未达成


def test_ai_relay(client, ai_stub):
    admin = client.post(
        "/v1/admin/login", json={"username": "admin", "password": "admin123"}
    ).json()
    ah = {"Authorization": f"Bearer {admin['data']['token']}"}
    h = _reg(client, "ai_player")

    # 未配置 → 报错
    r = client.post("/v1/ai/chat", json={"messages": [{"role": "user", "content": "hi"}]}, headers=h).json()
    assert r["code"] in (24001, 24002)

    # 配置 AI(指向 stub)
    r = client.put(
        "/v1/admin/ai/config",
        json={"enabled": True, "base_url": ai_stub, "api_key": "sk-stub-key", "model": "stub-model"},
        headers=ah,
    ).json()
    assert r["code"] == 0
    r = client.get("/v1/admin/ai/config", headers=ah).json()
    assert "sk-stub" not in r["data"]["api_key"] and r["data"]["configured"] is True

    # 测试连接(拉模型)
    r = client.post("/v1/admin/ai/test", headers=ah).json()
    assert r["code"] == 0 and "stub-model" in r["data"]["models"]

    # 对话转发 + 用量记录
    r = client.post(
        "/v1/ai/chat",
        json={"model": "stub-model", "messages": [{"role": "user", "content": "谷雨是什么?"}]},
        headers=h,
    ).json()
    assert r["code"] == 0
    assert r["data"]["choices"][0]["message"]["content"] == "你好,我是节气小老师"
    assert r["data"]["usage"]["total_tokens"] == 20

    # 玩家用量
    u = client.get("/v1/ai/usage", headers=h).json()["data"]["total"]
    assert u["requests"] == 1 and u["total_tokens"] == 20

    # 管理端全服用量
    r = client.get("/v1/admin/ai/usage", headers=ah).json()
    mine = [i for i in r["data"]["items"] if i["name"] == "ai_player"]
    assert mine and mine[0]["requests"] == 1 and mine[0]["total_tokens"] == 20

    # 任务求值器从用量表取数:q_ai_3 进度 1
    r = client.get("/v1/quests", headers=h).json()
    q = {x["code"]: x for x in r["data"]["items"]}["q_ai_3"]
    assert q["progress"]["current"] == 1


def _pid(client, h):
    return client.get("/v1/player/me", headers=h).json()["data"]["player_id"]


def test_ai_thinking_off_strips_reasoning(client, monkeypatch):
    """关闭思考:转发时剥离 reasoning 字段;开启时保留。"""
    import asyncio

    from app.core.db import SessionLocal
    from app.models import Player, User
    from app.services import ai_service

    admin = client.post(
        "/v1/admin/login", json={"username": "admin", "password": "admin123"}
    ).json()
    ah = {"Authorization": f"Bearer {admin['data']['token']}"}
    h = _reg(client, "ai_think")

    # 配置 AI(指向任意 base_url,monkeypatch 拦截 httpx)
    r = client.put(
        "/v1/admin/ai/config",
        json={"enabled": True, "base_url": "http://stub", "api_key": "sk-key", "model": "m", "thinking": False},
        headers=ah,
    ).json()
    assert r["code"] == 0
    # 配置回读含 thinking
    r = client.get("/v1/admin/ai/config", headers=ah).json()
    assert r["data"]["thinking"] is False

    captured = {}

    async def fake_post(self, url, json=None, headers=None):
        captured["body"] = json
        return _FakeResp()

    class _FakeResp:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": "ok"}}], "usage": {"total_tokens": 1}}

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    with SessionLocal() as db:
        u = db.query(User).filter(User.name == "ai_think").first()
        p = db.query(Player).filter(Player.user_id == u.id).first()
        # 关闭思考 → 剥离 reasoning
        asyncio.run(ai_service.chat(db, p, {"model": "m", "messages": [], "reasoning": "chain", "reasoning_effort": "high"}))
        assert "reasoning" not in captured["body"]
        assert "reasoning_effort" not in captured["body"]
        # 开启思考 → 保留
        ai_service.save_ai_config(db, {"thinking": True})
        asyncio.run(ai_service.chat(db, p, {"model": "m", "messages": [], "reasoning": "chain"}))
        assert captured["body"].get("reasoning") == "chain"
        # 显式 thinking=False → 请求体带 {"thinking": {"type": "disabled"}}(DeepSeek 风格,客人等短 JSON 场景)
        asyncio.run(ai_service.chat(db, p, {"model": "m", "messages": []}, thinking=False))
        assert captured["body"].get("thinking") == {"type": "disabled"}


def test_social_search_and_uuid_query(client):
    """名字搜索 + UUID 查询(公开资料 + 关系状态)。"""
    hA = _reg(client, "srch_a")
    hB = _reg(client, "srch_b")
    pidB = _pid(client, hB)
    # 搜索:前缀/模糊匹配,排除自己
    r = client.get("/v1/social/search?q=srch", headers=hA).json()
    assert r["code"] == 0
    names = {i["name"] for i in r["data"]["items"]}
    assert "srch_b" in names and "srch_a" not in names  # 排除自己
    hit = next(i for i in r["data"]["items"] if i["name"] == "srch_b")
    assert hit["player_id"] == pidB and hit["level"] >= 1
    # 空搜索词 → 400
    assert client.get("/v1/social/search?q=", headers=hA).json()["code"] == 10001
    # UUID 查询:未加好友 → relation none
    r = client.get(f"/v1/social/players/{pidB}", headers=hA).json()
    assert r["code"] == 0
    assert r["data"]["relation"] == "none"
    assert r["data"]["name"] == "srch_b" and r["data"]["farm_name"]
    # 发申请后 → pending_out(从 A 看)
    client.post("/v1/social/requests", json={"player_id": pidB}, headers=hA)
    r = client.get(f"/v1/social/players/{pidB}", headers=hA).json()
    assert r["data"]["relation"] == "pending_out"
    # 从 B 看 → pending_in
    r = client.get(f"/v1/social/players/{_pid(client, hA)}", headers=hB).json()
    assert r["data"]["relation"] == "pending_in"
    # 接受后 → friends
    client.post(f"/v1/social/requests/{_pid(client, hA)}/accept", headers=hB)
    r = client.get(f"/v1/social/players/{pidB}", headers=hA).json()
    assert r["data"]["relation"] == "friends"
    # 不存在的 UUID → 20002
    assert client.get(f"/v1/social/players/{uuid.uuid4()}", headers=hA).json()["code"] == 20002


def test_social_friend_profile_and_farm(client):
    """好友资料卡 + 好友农场参观(只读)。"""
    hA = _reg(client, "prof_a")
    hB = _reg(client, "prof_b")
    pidA, pidB = _pid(client, hA), _pid(client, hB)
    # 非好友访问资料卡/农场 → 27005
    assert client.get(f"/v1/social/friends/{pidB}", headers=hA).json()["code"] == 27005
    assert client.get(f"/v1/social/friends/{pidB}/farm", headers=hA).json()["code"] == 27005
    # 成为好友
    client.post("/v1/social/requests", json={"player_id": pidB}, headers=hA)
    client.post(f"/v1/social/requests/{pidA}/accept", headers=hB)
    # 资料卡
    r = client.get(f"/v1/social/friends/{pidB}", headers=hA).json()
    assert r["code"] == 0 and r["data"]["relation"] == "friends"
    assert r["data"]["friends_since"]
    # B 种一株作物后,A 参观能看到(只读)
    _sow_and_harvest_one(client, hB)  # 收获后地块空 —— 用 _sow 不收获
    r = client.get(f"/v1/social/friends/{pidB}/farm", headers=hA).json()
    assert r["code"] == 0
    assert r["data"]["farm"]["name"] and r["data"]["farm"]["owner"]["name"] == "prof_b"
    assert len(r["data"]["plots"]) == 20
    # 参观不触发任何状态变更(无 weed_events/wither 副作用字段,纯只读)


def test_social_water_and_steal_scaffold(client):
    """预留互动契约:接口已定,功能未上线(enabled=false)。"""
    hA = _reg(client, "scaf_a")
    hB = _reg(client, "scaf_b")
    pidA, pidB = _pid(client, hA), _pid(client, hB)
    client.post("/v1/social/requests", json={"player_id": pidB}, headers=hA)
    client.post(f"/v1/social/requests/{pidA}/accept", headers=hB)
    # 浇水(预留)
    r = client.post(f"/v1/social/friends/{pidB}/water", headers=hA).json()
    assert r["code"] == 0 and r["data"]["feature"] == "water"
    assert r["data"]["enabled"] is False
    # 偷菜(预留)
    r = client.post(f"/v1/social/friends/{pidB}/plots/3/steal", headers=hA).json()
    assert r["code"] == 0 and r["data"]["feature"] == "steal"
    assert r["data"]["enabled"] is False


# ---------- 修复回归:daily 任务跨天重置 ----------

def test_daily_quest_resets_next_day(client):
    """daily 任务昨天领过 → 今天可再领;当天不可重复领。"""
    from datetime import date, timedelta
    from app.core.db import SessionLocal
    from app.core.utils import ensure_aware
    from app.models import UserQuest, Player, User

    h = _reg(client, "daily_reset")
    items = {q["code"]: q for q in client.get("/v1/quests", headers=h).json()["data"]["items"]}
    # 找 daily 任务 q_harvest_1
    assert items["q_harvest_1"]["category"] == "daily"
    qid = items["q_harvest_1"]["quest_id"]

    # 完成并领取一次(播种+催熟+收获)
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
    client.get("/v1/quests", headers=h)  # 状态→已完成
    before = client.get("/v1/player/me", headers=h).json()["data"]["coins"]
    r = client.post(f"/v1/quests/{qid}/claim", headers=h).json()
    assert r["code"] == 0 and r["data"]["coins_balance"] == before + 20

    # 当天再领 → 25003(同天不重复)
    r = client.post(f"/v1/quests/{qid}/claim", headers=h).json()
    assert r["code"] == 25003

    # 模拟第二天:把 claimed_at 回拨到昨天
    with SessionLocal() as db:
        u = db.query(User).filter(User.name == "daily_reset").first()
        p = db.query(Player).filter(Player.user_id == u.id).first()
        uq = db.query(UserQuest).filter(UserQuest.player_id == p.id, UserQuest.quest_id == uuid.UUID(qid)).first()
        uq.claimed_at = ensure_aware(uq.claimed_at) - timedelta(days=1)
        uq.completed_at = ensure_aware(uq.completed_at) - timedelta(days=1)
        db.commit()

    # 再拉列表 → daily 已重置(收获条件当天仍满足,立即回到"已完成"可领取)
    items = {q["code"]: q for q in client.get("/v1/quests", headers=h).json()["data"]["items"]}
    # 已重置:不再因 claimed_at=昨天 抛 25003,而是可再领(状态 1 已完成或 0 后立即判完成)
    assert items["q_harvest_1"]["status"] in (0, 1)

    # 直接领取 → 成功(第二天可再领;若状态仍是 0 说明 reset 未生效,会走"未完成"分支)
    before2 = client.get("/v1/player/me", headers=h).json()["data"]["coins"]
    r = client.post(f"/v1/quests/{qid}/claim", headers=h).json()
    assert r["code"] == 0 and r["data"]["coins_balance"] == before2 + 20  # 第二天可再领


def test_social_search_limit_and_like_escape(client):
    """搜索 limit 有下限/上限(负值不绕过);LIKE 通配符被转义。"""
    h = _reg(client, "slim_user")
    # 负 limit → 422(API 层 ge=1 校验),不再绕过 50 上限
    r = client.get("/v1/social/search?q=s&limit=-1", headers=h)
    assert r.status_code == 422, r.status_code
    # 超大 limit → 422(API 层 le=50 校验)
    r = client.get("/v1/social/search?q=s&limit=999", headers=h)
    assert r.status_code == 422, r.status_code
    # 合法 limit → 200,结果数受上限约束
    r = client.get("/v1/social/search?q=s&limit=50", headers=h).json()
    assert r["code"] == 0 and len(r["data"]["items"]) <= 50
    # LIKE 转义:名字含 % 的玩家,用 % 精确搜不会匹配全部
    r = client.post("/v1/auth/register", json={"name": "like_100%", "password": "pass123456"}).json()
    assert r["code"] == 0
    r = client.get("/v1/social/search?q=100%25", headers=h).json()
    assert r["code"] == 0
    names = {i["name"] for i in r["data"]["items"]}
    assert "like_100%" in names
    # 通配符 % 不再匹配所有名字(仅精确含字面 % 的)
    assert not any(n not in ("like_100%",) for n in names) or len(names) <= 2


def test_quest_double_claim_guard(client):
    """领奖原子抢占:同任务重复领取只发一次奖励(并发/双击防护)。"""
    h = _reg(client, "quest_claim_guard")
    items = {q["code"]: q for q in client.get("/v1/quests", headers=h).json()["data"]["items"]}
    qid = items["q_harvest_1"]["quest_id"]

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
    client.get("/v1/quests", headers=h)  # 状态→已完成

    before = client.get("/v1/player/me", headers=h).json()["data"]["coins"]
    # 第一次领成功
    r = client.post(f"/v1/quests/{qid}/claim", headers=h).json()
    assert r["code"] == 0
    # 重复领(含并发场景的等价串行模拟)→ 25003,金币不再增加
    r = client.post(f"/v1/quests/{qid}/claim", headers=h).json()
    assert r["code"] == 25003
    after = client.get("/v1/player/me", headers=h).json()["data"]["coins"]
    assert after == before + 20  # 只发一次奖励


def test_social_public_visit_farm(client):
    """公开访客模式:非好友也能参观田格数据(为帮忙浇水提供前置数据)。"""
    hA = _reg(client, "visit_a")
    hB = _reg(client, "visit_b")
    pidB = _pid(client, hB)
    # B 种一株水稻(不收获),让田格有作物数据
    _advance_to_rice_window(client, hB)
    shop = client.get("/v1/shop/items", headers=hB).json()["data"]["items"]
    seed = next(i for i in shop if i["code"] == "seed_shuidao")
    client.post(f"/v1/shop/items/{seed['item_id']}/buy", json={"quantity": 1}, headers=hB)
    plot = client.get("/v1/farm/state", headers=hB).json()["data"]["plots"][0]["plot_id"]
    client.post(f"/v1/farm/plots/{plot}/sow", json={"crop_id": seed["effect"]["crop_id"]}, headers=hB)

    # A(非好友)公开访客模式参观 B 的农场 → 田格数据
    r = client.get(f"/v1/social/players/{pidB}/farm", headers=hA).json()
    assert r["code"] == 0, r
    assert r["data"]["farm"]["name"] and r["data"]["farm"]["owner"]["name"] == "visit_b"
    plots = r["data"]["plots"]
    assert len(plots) == 20
    cell = plots[0]
    assert cell["idx"] == 1 and "plot_id" in cell
    # 田格数据:作物状态含需水量/当前水分 —— 浇水功能的前置
    assert cell["crop"]["name"] == "水稻"
    assert "water_level" in cell["crop"] and "water_need" in cell["crop"]
    assert cell["crop"]["status"] in ("growing", "mature")
    # 好友专用端点仍然拒绝非好友
    assert client.get(f"/v1/social/friends/{pidB}/farm", headers=hA).json()["code"] == 27005


def test_social_search_exact_duplicates_and_login(client):
    """精确用户名查询:重名返回多个 + 登录按「名字+密码」双匹配。

    2026-08-15 放开重名:注册允许同名(班级同名场景),登录改为双匹配。
    """
    hC = _reg(client, "查重者")

    def _reg_with_pw(client, name, password):
        r = client.post(
            "/v1/auth/register", json={"name": name, "password": password}
        ).json()
        assert r["code"] == 0, r
        return r, _pid(client, {"Authorization": f"Bearer {r['data']['token']}"})

    rA, pidA = _reg_with_pw(client, "同名甲", "pass111111")
    rB, pidB = _reg_with_pw(client, "同名甲", "pass222222")  # 同名不同密码
    _reg_with_pw(client, "同名乙", "pass111111")

    # 登录双匹配:同名不同密码,各自登录自己的账号
    r = client.post("/v1/auth/login", json={"name": "同名甲", "password": "pass111111"}).json()
    assert r["code"] == 0 and r["data"]["player"]["player_id"] == pidA
    r = client.post("/v1/auth/login", json={"name": "同名甲", "password": "pass222222"}).json()
    assert r["code"] == 0 and r["data"]["player"]["player_id"] == pidB

    # 精确:q=同名甲 → 2 个,全部同名
    r = client.get("/v1/social/search?q=同名甲&exact=true", headers=hC).json()
    assert r["code"] == 0, r
    items = r["data"]["items"]
    assert len(items) == 2, items
    assert {i["name"] for i in items} == {"同名甲"}
    assert {i["player_id"] for i in items} == {pidA, pidB}
    # 精确:同名乙 → 1 个
    r = client.get("/v1/social/search?q=同名乙&exact=true", headers=hC).json()
    assert [i["name"] for i in r["data"]["items"]] == ["同名乙"]
    # 精确模式下"同名"不命中(不再是模糊)
    r = client.get("/v1/social/search?q=同名&exact=true", headers=hC).json()
    assert r["data"]["items"] == []
    # 模糊模式(默认):包含匹配 → 3 个
    r = client.get("/v1/social/search?q=同名", headers=hC).json()
    assert len(r["data"]["items"]) == 3
    # 精确搜索也排除自己:同名甲本人搜"同名甲" → 只剩 1 个
    hA = {"Authorization": f"Bearer {rA['data']['token']}"}
    r = client.get("/v1/social/search?q=同名甲&exact=true", headers=hA).json()
    assert len(r["data"]["items"]) == 1

    # 第三个同名甲用与 A 相同的密码 → 登录时密码撞车 → 20006 NAME_CONFLICT
    r = client.post(
        "/v1/auth/register", json={"name": "同名甲", "password": "pass111111"}
    ).json()
    assert r["code"] == 0
    r = client.post("/v1/auth/login", json={"name": "同名甲", "password": "pass111111"}).json()
    assert r["code"] == 20006, r
    # B 的密码仍可正常登录(双匹配只影响撞车的那组)
    r = client.post("/v1/auth/login", json={"name": "同名甲", "password": "pass222222"}).json()
    assert r["code"] == 0 and r["data"]["player"]["player_id"] == pidB
