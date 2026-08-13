"""任务 / 社交 / 成就 / AI 转发 测试。

AI 部分使用进程内 stub 上游(OpenAI 兼容),验证转发 + 用量记录 + 管理端配置。
"""
import threading
import time

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
    r = client.post(
        "/v1/auth/register", json={"name": name, "password": "pass123456"}
    ).json()
    assert r["code"] == 0
    return {"Authorization": f"Bearer {r['data']['token']}"}


def _advance_to_rice_window(client, h):
    for _ in range(40):
        cal = client.get("/v1/calendar/current").json()["data"]
        if 5 <= cal["term_index"] <= 9:
            return
        client.post("/v1/debug/term/advance", headers=h)


def _sow_and_harvest_one(client, h):
    _advance_to_rice_window(client, h)
    shop = client.get("/v1/shop/items", headers=h).json()["data"]["items"]
    seed = next(i for i in shop if i["code"] == "seed_rice")
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
