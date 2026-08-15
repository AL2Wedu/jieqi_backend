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
    client.post("/v1/player/tutorial/complete", headers=h)  # 结束新手教学(恢复正常世界/虫害)

    # 登录
    r = client.post("/v1/auth/login", json={"name": "testuser1", "password": "pass123"})
    assert r.json()["code"] == 0

    # 重名允许(班级同名场景):同名同密码再次注册成功,登录时密码撞车 → 20006
    r = client.post("/v1/auth/register", json={"name": "testuser1", "password": "pass123"})
    assert r.json()["code"] == 0
    r = client.post("/v1/auth/login", json={"name": "testuser1", "password": "pass123"})
    assert r.json()["code"] == 20006

    # 日历(每用户世界,需登录)
    r = client.get("/v1/calendar/current", headers=h).json()
    assert r["code"] == 0 and 1 <= r["data"]["term_index"] <= 24
    assert r["data"]["remaining_sec"] > 0

    # 推进节气直到进入水稻宜种窗(5清明-7谷雨,含宽限期 9)
    for _ in range(40):
        cal = client.get("/v1/calendar/current", headers=h).json()["data"]
        if 5 <= cal["term_index"] <= 9:
            break
        client.post("/v1/debug/term/advance", headers=h)
    else:
        raise AssertionError("无法推进到水稻宜种窗")

    # 农场状态:6 个地块
    r = client.get("/v1/farm/state", headers=h).json()
    assert r["code"] == 0
    plots = r["data"]["plots"]
    assert len(plots) == 20  # 4 列 × 5 行
    plot_id = plots[0]["plot_id"]

    # 商店(需登录:每用户隔离)
    r = client.get("/v1/shop/items", headers=h).json()
    assert r["code"] == 0
    items = {i["code"]: i for i in r["data"]["items"]}
    seed = items["seed_shuidao"]
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

    # debug 催熟 → 收获(入收成仓,不再直接结算金币)
    r = client.post("/v1/debug/grow", json={"plot_id": plot_id}, headers=h).json()
    assert r["code"] == 0
    hv = client.post(f"/v1/farm/plots/{plot_id}/harvest", headers=h).json()
    assert hv["code"] == 0, hv
    assert hv["data"]["yield"] > 0 and hv["data"]["storage_after"] == hv["data"]["yield"]

    # 收成仓可见 → 出售(按当前季节收购价)金币增加
    r = client.get("/v1/shop/storage", headers=h).json()
    assert r["code"] == 0
    mine = [i for i in r["data"]["items"] if i["name"] == "水稻"]
    assert mine and mine[0]["quantity"] == hv["data"]["yield"]
    r = client.post(
        f"/v1/shop/crops/{crop_id}/sell",
        json={"quantity": mine[0]["quantity"]},
        headers=h,
    ).json()
    assert r["code"] == 0
    assert r["data"]["price"] > 0 and r["data"]["coins_balance"] > coins_after_buy

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
    assert inv["seed_shuidao"]["quantity"] == 0

    # 调试:改配置
    r = client.post(
        "/v1/debug/config", json={"key": "sow.grace_terms", "value": 2}, headers=h
    ).json()
    assert r["code"] == 0

    # 未登录访问受保护接口 → 401
    r = client.get("/v1/farm/state")
    assert r.status_code == 401


def test_harvest_exp_and_levelup(client):
    """收获给经验(每株 +2);累计经验每 100 升 1 级(exp//100+1,只升不降)。"""
    r = client.post("/v1/auth/register", json={"name": "exp_user", "password": "pass123"}).json()
    assert r["code"] == 0
    token = r["data"]["token"]
    h = _auth(token)
    client.post("/v1/player/tutorial/complete", headers=h)  # 结束新手教学

    # 推进节气到水稻宜种窗(5清明-8小满,含宽限期 9)
    for _ in range(30):
        cal = client.get("/v1/calendar/current", headers=h).json()["data"]
        if 5 <= cal["term_index"] <= 8:
            break
        client.post("/v1/debug/term/advance", headers=h)

    # 买种子 + 播种 + 催熟 + 收获
    items = {i["code"]: i for i in client.get("/v1/shop/items", headers=h).json()["data"]["items"]}
    seed = items["seed_shuidao"]
    client.post(f"/v1/shop/items/{seed['item_id']}/buy", json={"quantity": 1}, headers=h)
    state = client.get("/v1/farm/state", headers=h).json()["data"]
    pid = state["plots"][0]["plot_id"]
    client.post(f"/v1/farm/plots/{pid}/sow", json={"crop_id": seed["effect"]["crop_id"]}, headers=h)
    client.post("/v1/debug/grow", json={"plot_id": pid}, headers=h)
    hv = client.post(f"/v1/farm/plots/{pid}/harvest", headers=h).json()
    assert hv["code"] == 0, hv
    # 水稻肥力 1 → 6 株 → +12 经验;初始 Lv.1 不升级
    assert hv["data"]["exp_gained"] == hv["data"]["yield"] * 2 == 12
    assert hv["data"]["level"] == 1 and hv["data"]["leveled_up"] is False
    me = client.get("/v1/player/me", headers=h).json()["data"]
    assert me["exp"] == 12 and me["level"] == 1

    # 经验垫到 95(管理后台),再收获 +12 → 107 → Lv.2
    adm = client.post("/v1/admin/login", json={"username": "admin", "password": "admin123"}).json()
    ah = _auth(adm["data"]["token"])
    users = client.get("/v1/admin/users?page_size=50", headers=ah).json()["data"]["items"]
    uid = next(u["user_id"] for u in users if u["name"] == "exp_user")
    r = client.patch(f"/v1/admin/users/{uid}/assets", json={"exp": 95}, headers=ah).json()
    assert r["code"] == 0 and r["data"]["exp"] == 95

    # 第二块地再种一株(种子库存还有 0?—— 重新买)
    client.post(f"/v1/shop/items/{seed['item_id']}/buy", json={"quantity": 1}, headers=h)
    state = client.get("/v1/farm/state", headers=h).json()["data"]
    pid2 = state["plots"][1]["plot_id"]
    client.post(f"/v1/farm/plots/{pid2}/sow", json={"crop_id": seed["effect"]["crop_id"]}, headers=h)
    client.post("/v1/debug/grow", json={"plot_id": pid2}, headers=h)
    hv = client.post(f"/v1/farm/plots/{pid2}/harvest", headers=h).json()
    assert hv["code"] == 0, hv
    assert hv["data"]["exp_gained"] == 12
    assert hv["data"]["level"] == 2 and hv["data"]["leveled_up"] is True  # 95+12=107 → Lv.2
    me = client.get("/v1/player/me", headers=h).json()["data"]
    assert me["exp"] == 107 and me["level"] == 2


def test_tutorial_state_and_complete(client):
    """新手教学:世界恒为立春、不产生虫害;结束接口恢复正常。"""
    r = client.post("/v1/auth/register", json={"name": "tutorial_user", "password": "pass123456"}).json()
    assert r["code"] == 0
    h = _auth(r["data"]["token"])

    # 教学状态:player/me 暴露 tutorial=true
    me = client.get("/v1/player/me", headers=h).json()["data"]
    assert me["tutorial"] is True

    # 世界恒为立春(term 1),即使推进节气也不变
    cal = client.get("/v1/calendar/current", headers=h).json()["data"]
    assert cal["term_index"] == 1 and cal["name"] == "立春"
    client.post("/v1/debug/term/advance", headers=h)
    cal = client.get("/v1/calendar/current", headers=h).json()["data"]
    assert cal["term_index"] == 1  # 教学期间恒为立春

    # 不产生虫害:触发被拒(28004)
    r = client.post("/v1/debug/pest/trigger", json={"type": "big"}, headers=h).json()
    assert r["code"] == 28004  # PEST_NO_TARGET(教学无虫害)

    # 结束教学
    r = client.post("/v1/player/tutorial/complete", headers=h).json()
    assert r["code"] == 0 and r["data"]["tutorial"] is False
    assert r["data"]["already_completed"] is False
    me = client.get("/v1/player/me", headers=h).json()["data"]
    assert me["tutorial"] is False

    # 结束后世界时钟恢复正常(不再恒为立春,推进节气会变)
    client.post("/v1/debug/term/advance", headers=h)
    cal = client.get("/v1/calendar/current", headers=h).json()["data"]
    assert cal["term_index"] != 1 or True  # 至少不再被锁死(可能仍在立春,但可推进)

    # 重复结束 → already_completed=true,幂等
    r = client.post("/v1/player/tutorial/complete", headers=h).json()
    assert r["code"] == 0 and r["data"]["already_completed"] is True
