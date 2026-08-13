"""管理后台全链路测试:登录/守卫/仪表盘/用户/配置/作物/道具/节气时钟。"""
import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _admin_login(client) -> tuple[str, dict]:
    r = client.post("/v1/admin/login", json={"username": "admin", "password": "admin123"})
    assert r.json()["code"] == 0, r.json()
    token = r.json()["data"]["token"]
    return token, {"Authorization": f"Bearer {token}"}


def test_admin_login_bad(client):
    r = client.post("/v1/admin/login", json={"username": "admin", "password": "wrong"})
    assert r.status_code == 401
    assert r.json()["code"] == 30001


def test_admin_guard(client):
    r = client.get("/v1/admin/dashboard")
    assert r.status_code == 401


def test_dashboard(client):
    _, h = _admin_login(client)
    r = client.get("/v1/admin/dashboard", headers=h).json()
    assert r["code"] == 0
    d = r["data"]
    assert d["server"]["pid"] > 0
    assert d["counts"]["terms"] == 24
    assert d["counts"]["crops"] >= 6
    assert 1 <= d["calendar"]["term_index"] <= 24


def test_users_and_ban(client):
    token, h = _admin_login(client)
    client.post("/v1/auth/register", json={"name": "admin_test_user", "password": "pass123"})
    r = client.get("/v1/admin/users", headers=h).json()
    assert r["code"] == 0
    target = next(u for u in r["data"]["items"] if u["name"] == "admin_test_user")
    uid = target["user_id"]

    # 封禁 → 登录失败
    r = client.patch(f"/v1/admin/users/{uid}/status", json={"status": 0}, headers=h).json()
    assert r["code"] == 0 and r["data"]["status"] == 0
    r = client.post("/v1/auth/login", json={"name": "admin_test_user", "password": "pass123"})
    assert r.json()["code"] != 0

    # 解封 → 登录成功
    r = client.patch(f"/v1/admin/users/{uid}/status", json={"status": 1}, headers=h).json()
    assert r["code"] == 0 and r["data"]["status"] == 1
    r = client.post("/v1/auth/login", json={"name": "admin_test_user", "password": "pass123"})
    assert r.json()["code"] == 0


def test_config_crud(client):
    _, h = _admin_login(client)
    r = client.put("/v1/admin/config/sow.grace_terms", json={"value": 2}, headers=h).json()
    assert r["code"] == 0
    r = client.get("/v1/admin/config", headers=h).json()
    assert any(
        i["key"] == "sow.grace_terms" and i["value"] == 2 for i in r["data"]["items"]
    )
    r = client.put("/v1/admin/config/sow.grace_terms", json={"value": 3}, headers=h).json()
    assert r["code"] == 0
    r = client.delete("/v1/admin/config/sow.grace_terms", headers=h).json()
    assert r["code"] == 0
    r = client.get("/v1/admin/config", headers=h).json()
    assert not any(i["key"] == "sow.grace_terms" for i in r["data"]["items"])


def test_crops_crud(client):
    _, h = _admin_login(client)
    # 商店检查需要玩家视角(每用户隔离)
    pr = client.post(
        "/v1/auth/register", json={"name": "crop_shop_check", "password": "pass123456"}
    ).json()
    ph = {"Authorization": f"Bearer {pr['data']['token']}"}
    r = client.get("/v1/admin/crops", headers=h).json()
    assert r["code"] == 0 and len(r["data"]["items"]) >= 6

    # 新增作物 + 自动创建种子
    r = client.post(
        "/v1/admin/crops",
        json={
            "name": "西瓜",
            "category": "蔬菜",
            "sow_window": {"type": "term", "start": 14, "end": 16, "grace": 2},
            "grow_seconds": 700,
            "yield_base": 4,
            "base_price": 14,
            "auto_seed": True,
        },
        headers=h,
    ).json()
    assert r["code"] == 0, r
    assert r["data"]["seed_created"] is True
    crop_id = r["data"]["crop_id"]
    # 自动生成美术资产:种子 + 三阶段路径齐全
    art = r["data"]["art"]
    assert art["seed"].endswith("seed.svg")
    assert len(art["stages"]) == 3 and all(s.endswith(".svg") for s in art["stages"])

    # 商店出现萝卜种子(玩家视角)
    shop = client.get("/v1/shop/items", headers=ph).json()["data"]["items"]
    assert any(
        i["name"] == "西瓜种子" and i["effect"]["crop_id"] == crop_id for i in shop
    )

    # 编辑
    r = client.put(
        f"/v1/admin/crops/{crop_id}", json={"base_price": 18, "grow_seconds": 800}, headers=h
    ).json()
    assert r["code"] == 0 and r["data"]["base_price"] == 18

    # 软删 → 商店种子消失(玩家视角)
    r = client.delete(f"/v1/admin/crops/{crop_id}", headers=h).json()
    assert r["code"] == 0 and r["data"]["active"] is False
    shop = client.get("/v1/shop/items", headers=ph).json()["data"]["items"]
    assert not any(i["name"] == "西瓜种子" for i in shop)


def test_items_crud(client):
    _, h = _admin_login(client)
    r = client.post(
        "/v1/admin/items",
        json={
            "code": "test_sprinkler",
            "name": "测试洒水器",
            "category": "tool",
            "effect": {"type": "water", "amount": 100},
            "buy_price": 40,
            "sell_price": 8,
        },
        headers=h,
    ).json()
    assert r["code"] == 0, r
    item_id = r["data"]["item_id"]

    r = client.put(f"/v1/admin/items/{item_id}", json={"buy_price": 45}, headers=h).json()
    assert r["code"] == 0 and r["data"]["buy_price"] == 45

    # 种子 effect 校验:无效 crop_id 拒绝
    r = client.post(
        "/v1/admin/items",
        json={
            "code": "bad_seed",
            "name": "坏种子",
            "category": "seed",
            "effect": {"type": "seed", "crop_id": "00000000-0000-0000-0000-000000000000"},
        },
        headers=h,
    ).json()
    assert r["code"] != 0

    r = client.delete(f"/v1/admin/items/{item_id}", headers=h).json()
    assert r["code"] == 0 and r["data"]["active"] is False


def test_plantings_view(client):
    """全服种植状态:每株植物的服务器权威状态可见,收获后不再列为种植中。"""
    _, h = _admin_login(client)
    # 准备一个玩家 + 一株作物
    reg = client.post("/v1/auth/register", json={"name": "plant_owner", "password": "pass123"}).json()
    token = reg["data"]["token"]
    ph = {"Authorization": f"Bearer {token}"}
    # 推进到水稻宜种窗
    for _ in range(40):
        cal = client.get("/v1/calendar/current").json()["data"]
        if 5 <= cal["term_index"] <= 9:
            break
        client.post("/v1/debug/term/advance", headers=ph)
    shop = client.get("/v1/shop/items", headers=ph).json()["data"]["items"]
    seed = next(i for i in shop if i["code"] == "seed_shuidao")
    client.post(f"/v1/shop/items/{seed['item_id']}/buy", json={"quantity": 1}, headers=ph)
    plot = client.get("/v1/farm/state", headers=ph).json()["data"]["plots"][0]["plot_id"]
    client.post(f"/v1/farm/plots/{plot}/sow", json={"crop_id": seed["effect"]["crop_id"]}, headers=ph)

    # 种植状态列表可见该株
    r = client.get("/v1/admin/plantings", headers=h).json()
    assert r["code"] == 0
    mine = [p for p in r["data"]["items"] if p["player"] == "plant_owner"]
    assert len(mine) == 1
    p = mine[0]
    assert p["crop"] == "水稻"
    assert p["stage"] in (1, 2, 3)
    assert 0 <= p["growth_progress"] <= 100
    assert p["water_level"] == 100
    assert p["plot_idx"] == 1

    # 收获后不再是"种植中"
    client.post("/v1/debug/grow", json={"plot_id": plot}, headers=ph)
    client.post(f"/v1/farm/plots/{plot}/harvest", headers=ph)
    r = client.get("/v1/admin/plantings", headers=h).json()
    assert not any(p["player"] == "plant_owner" for p in r["data"]["items"])


def test_terms_and_clock(client):
    _, h = _admin_login(client)
    r = client.get("/v1/admin/terms", headers=h).json()
    assert r["code"] == 0 and len(r["data"]["items"]) == 24

    r = client.put("/v1/admin/terms/1", json={"duration_seconds": 600}, headers=h).json()
    assert r["code"] == 0 and r["data"]["duration_seconds"] == 600

    r = client.put(
        "/v1/admin/clock", json={"time_scale": 2.0, "paused": True}, headers=h
    ).json()
    assert r["code"] == 0
    assert r["data"]["paused"] is True and r["data"]["time_scale"] == 2.0

    # 恢复默认
    r = client.put(
        "/v1/admin/clock", json={"time_scale": 1.0, "paused": False, "reset_epoch": True}, headers=h
    ).json()
    assert r["code"] == 0 and r["data"]["paused"] is False


def test_admin_logs_ws(client):
    """日志监控流:有效 token 收到日志行或提示;无效 token 被拒绝(4401)。"""
    import pytest
    from starlette.websockets import WebSocketDisconnect

    token, _ = _admin_login(client)

    # 有效 token:收到初始回放(测试环境无日志文件 → 收到错误提示消息)
    with client.websocket_connect(f"/v1/admin/logs?token={token}") as ws:
        first = ws.receive_json()
        assert first["type"] in ("log", "error")

    # 无效 token:连接被拒
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/v1/admin/logs?token=bad-token"):
            pass
    assert exc.value.code == 4401
