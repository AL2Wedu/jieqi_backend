"""管理端全面掌控测试:地块作物(种/换/清/调进度)/ 背包 / 收成仓。"""
import uuid

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

def _admin(client):
    r = client.post("/v1/admin/login", json={"username": "admin", "password": "admin123"})
    assert r.json()["code"] == 0
    return {"Authorization": f"Bearer {r.json()['data']['token']}"}

def _uid(client, ah, name):
    users = client.get("/v1/admin/users", headers=ah).json()["data"]["items"]
    return next(u for u in users if u["name"] == name)["user_id"]


def _crop_id(client, ah, name):
    crops = client.get("/v1/admin/crops", headers=ah).json()["data"]["items"]
    return next(c for c in crops if c["name"] == name)["crop_id"]


def test_admin_plant_crop(client):
    """admin 给地块种指定作物(不消耗种子、进度 60),玩家视角可见。"""
    h = _reg(client, "ctl_plant")
    ah = _admin(client)
    uid = _uid(client, ah, "ctl_plant")
    rice = _crop_id(client, ah, "水稻")
    wheat = _crop_id(client, ah, "小麦")

    # 玩家无种子,admin 直接种
    r = client.put(
        f"/v1/admin/users/{uid}/plots/1/crop",
        json={"crop_id": rice, "growth_progress": 60, "water_level": 80},
        headers=ah,
    ).json()
    assert r["code"] == 0, r
    assert r["data"]["crop_id"] == rice
    assert r["data"]["growth_progress"] == 60
    assert r["data"]["stage"] == 2  # 60% → 生长期

    # 玩家视角
    state = client.get("/v1/farm/state", headers=h).json()["data"]
    plot1 = next(p for p in state["plots"] if p["idx"] == 1)
    assert plot1["crop"]["name"] == "水稻"
    assert abs(plot1["crop"]["growth_progress"] - 60) <= 1
    assert plot1["crop"]["water_level"] == 80

    # 替换为小麦 → 旧作物被清、新作物生效
    r = client.put(
        f"/v1/admin/users/{uid}/plots/1/crop",
        json={"crop_id": wheat},
        headers=ah,
    ).json()
    assert r["code"] == 0 and r["data"]["crop_id"] == wheat
    state = client.get("/v1/farm/state", headers=h).json()["data"]
    plot1 = next(p for p in state["plots"] if p["idx"] == 1)
    assert plot1["crop"]["name"] == "小麦"

    # 无效作物
    r = client.put(
        f"/v1/admin/users/{uid}/plots/1/crop",
        json={"crop_id": str(uuid.uuid4())},
        headers=ah,
    ).json()
    assert r["code"] != 0


def test_admin_clear_and_growth(client):
    """admin 清除地块 + 调整进度/浇水。"""
    h = _reg(client, "ctl_growth")
    ah = _admin(client)
    uid = _uid(client, ah, "ctl_growth")
    rice = _crop_id(client, ah, "水稻")

    client.put(
        f"/v1/admin/users/{uid}/plots/2/crop",
        json={"crop_id": rice, "growth_progress": 20},
        headers=ah,
    )

    # 调进度到 100,浇水 50
    r = client.put(
        f"/v1/admin/users/{uid}/plots/2/growth",
        json={"growth_progress": 100, "water_level": 50},
        headers=ah,
    ).json()
    assert r["code"] == 0, r
    assert r["data"]["stage"] == 3
    assert r["data"]["water_level"] == 50

    state = client.get("/v1/farm/state", headers=h).json()["data"]
    plot2 = next(p for p in state["plots"] if p["idx"] == 2)
    assert plot2["crop"]["growth_progress"] == 100
    assert plot2["crop"]["water_level"] == 50

    # 清除
    r = client.delete(f"/v1/admin/users/{uid}/plots/2/crop", headers=ah).json()
    assert r["code"] == 0 and r["data"]["cleared"] is True
    state = client.get("/v1/farm/state", headers=h).json()["data"]
    plot2 = next(p for p in state["plots"] if p["idx"] == 2)
    assert plot2["crop"] is None

    # 空地块调进度 → 报错
    r = client.put(
        f"/v1/admin/users/{uid}/plots/2/growth",
        json={"growth_progress": 50},
        headers=ah,
    ).json()
    assert r["code"] != 0


def test_admin_inventory(client):
    """admin 设背包道具数量,玩家视角可见;置 0 清空;账本有 admin 记录。"""
    h = _reg(client, "ctl_inv")
    ah = _admin(client)
    uid = _uid(client, ah, "ctl_inv")

    items = client.get("/v1/admin/items", headers=ah).json()["data"]["items"]
    fertilizer = next(i for i in items if i["code"] == "fertilizer")

    r = client.put(
        f"/v1/admin/users/{uid}/inventory/{fertilizer['item_id']}",
        json={"quantity": 5},
        headers=ah,
    ).json()
    assert r["code"] == 0 and r["data"]["quantity"] == 5

    inv = client.get("/v1/player/inventory", headers=h).json()["data"]["items"]
    row = next(i for i in inv if i["code"] == "fertilizer")
    assert row["quantity"] == 5

    # 置 0 → 清空
    client.put(
        f"/v1/admin/users/{uid}/inventory/{fertilizer['item_id']}",
        json={"quantity": 0},
        headers=ah,
    )
    inv = client.get("/v1/player/inventory", headers=h).json()["data"]["items"]
    assert not any(i["code"] == "fertilizer" for i in inv)

    # admin 明细接口
    d = client.get(f"/v1/admin/users/{uid}/inventory", headers=ah).json()["data"]
    assert any(i["code"] == "fertilizer" and i["quantity"] == 0 for i in d["items"])


def test_admin_storage(client):
    """admin 设收成仓数量,玩家视角 /shop/storage 可见。"""
    _reg(client, "ctl_st")
    ah = _admin(client)
    uid = _uid(client, ah, "ctl_st")
    rice = _crop_id(client, ah, "水稻")

    r = client.put(
        f"/v1/admin/users/{uid}/storage/{rice}",
        json={"quantity": 12},
        headers=ah,
    ).json()
    assert r["code"] == 0 and r["data"]["quantity"] == 12

    # 玩家视角(收成仓经 /v1/shop/storage,需玩家 token)
    st = client.get(f"/v1/admin/users/{uid}/storage", headers=ah).json()["data"]
    assert any(c["crop_id"] == rice and c["quantity"] == 12 for c in st["crops"])


def test_admin_guard(client):
    """无 admin token 被拒。"""
    r = client.put(
        f"/v1/admin/users/{uuid.uuid4()}/plots/1/crop",
        json={"crop_id": str(uuid.uuid4())},
    )
    assert r.status_code == 401

    r = client.get(f"/v1/admin/users/{uuid.uuid4()}/inventory")
    assert r.status_code == 401
