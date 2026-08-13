"""P0 全闭环 smoke test:注册→登录→日历→农场→买种子→播种→浇水→催熟→收获→道具→调试接口。"""
import os

os.environ["DATABASE_URL"] = "sqlite:///./test.db"

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_full_flow(client):
    # 注册
    r = client.post("/v1/auth/register", json={"name": "testuser1", "password": "pass123"})
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 0
    token = body["data"]["token"]
    h = _auth(token)

    # 重复注册应失败
    r = client.post("/v1/auth/register", json={"name": "testuser1", "password": "pass123"})
    assert r.json()["code"] != 0

    # 登录
    r = client.post("/v1/auth/login", json={"name": "testuser1", "password": "pass123"})
    assert r.json()["code"] == 0

    # 日历
    r = client.get("/v1/calendar/current").json()
    assert r["code"] == 0 and 1 <= r["data"]["term_index"] <= 24
    assert r["data"]["remaining_sec"] > 0

    # 推进节气直到进入水稻宜种窗(5清明-7谷雨,含宽限期 9)
    for _ in range(40):
        cal = client.get("/v1/calendar/current").json()["data"]
        if 5 <= cal["term_index"] <= 9:
            break
        client.post("/v1/debug/term/advance", headers=h)
    else:
        raise AssertionError("无法推进到水稻宜种窗")

    # 农场状态:6 个地块
    r = client.get("/v1/farm/state", headers=h).json()
    assert r["code"] == 0
    plots = r["data"]["plots"]
    assert len(plots) == 6
    plot_id = plots[0]["plot_id"]

    # 商店
    r = client.get("/v1/shop/items").json()
    assert r["code"] == 0
    items = {i["code"]: i for i in r["data"]["items"]}
    seed = items["seed_rice"]
    crop_id = seed["effect"]["crop_id"]

    # 未买种子直接播种 → 失败
    r = client.post(f"/v1/farm/plots/{plot_id}/sow", json={"crop_id": crop_id}, headers=h).json()
    assert r["code"] != 0

    # 买 2 份水稻种子
    r = client.post(f"/v1/shop/items/{seed['item_id']}/buy", json={"quantity": 2}, headers=h).json()
    assert r["code"] == 0
    coins_after_buy = r["data"]["coins_balance"]

    # 播种
    r = client.post(f"/v1/farm/plots/{plot_id}/sow", json={"crop_id": crop_id}, headers=h).json()
    assert r["code"] == 0, r
    assert r["data"]["crop_name"] == "水稻"

    # 浇水
    r = client.post(f"/v1/farm/plots/{plot_id}/water", headers=h).json()
    assert r["code"] == 0 and r["data"]["water_level"] == 100

    # 未成熟不能收获
    r = client.post(f"/v1/farm/plots/{plot_id}/harvest", headers=h).json()
    assert r["code"] != 0

    # debug 催熟 → 收获
    r = client.post("/v1/debug/grow", json={"plot_id": plot_id}, headers=h).json()
    assert r["code"] == 0
    r = client.post(f"/v1/farm/plots/{plot_id}/harvest", headers=h).json()
    assert r["code"] == 0, r
    assert r["data"]["yield"] > 0 and r["data"]["coins_earned"] > 0
    assert r["data"]["coins_balance"] > coins_after_buy

    # 再播种(消耗第 2 颗种子)→ 用肥料加速
    r = client.post(f"/v1/farm/plots/{plot_id}/sow", json={"crop_id": crop_id}, headers=h).json()
    assert r["code"] == 0
    fert = items["fertilizer"]
    r = client.post(f"/v1/shop/items/{fert['item_id']}/buy", json={"quantity": 1}, headers=h).json()
    assert r["code"] == 0
    r = client.post(
        f"/v1/player/inventory/{fert['item_id']}/use",
        json={"target": {"plot_id": plot_id}},
        headers=h,
    ).json()
    assert r["code"] == 0
    assert r["data"]["effect_applied"]["growth_pct"] == 50

    # 背包:种子应剩 0(买 2 播 2)
    r = client.get("/v1/player/inventory", headers=h).json()
    assert r["code"] == 0
    inv = {i["code"]: i for i in r["data"]["items"]}
    assert inv["seed_rice"]["quantity"] == 0

    # 调试:改配置
    r = client.post(
        "/v1/debug/config", json={"key": "sow.grace_terms", "value": 2}, headers=h
    ).json()
    assert r["code"] == 0

    # 未登录访问受保护接口 → 401
    r = client.get("/v1/farm/state")
    assert r.status_code == 401
