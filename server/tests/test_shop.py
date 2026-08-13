"""商店系统测试:每用户隔离 / 售空 / 周期补货 / 季节涨降 / 收成仓出售 / 管理端覆盖。"""
from fastapi.testclient import TestClient

from app.main import app


def _reg(c, name):
    r = c.post("/v1/auth/register", json={"name": name, "password": "pass123456"}).json()
    assert r["code"] == 0
    return {"Authorization": f"Bearer {r['data']['token']}"}


def _admin(c):
    r = c.post("/v1/admin/login", json={"username": "admin", "password": "admin123"}).json()
    assert r["code"] == 0
    return {"Authorization": f"Bearer {r['data']['token']}"}


def test_shop_isolation():
    """每个用户商店相互隔离:一人购买不影响他人库存。"""
    with TestClient(app) as c:
        hA = _reg(c, "shop_iso_a")
        hB = _reg(c, "shop_iso_b")
        stateA = c.get("/v1/shop/state", headers=hA).json()["data"]
        stateB = c.get("/v1/shop/state", headers=hB).json()["data"]
        seedA = next(i for i in stateA["items"] if i["code"] == "seed_shuidao")
        seedB = next(i for i in stateB["items"] if i["code"] == "seed_shuidao")
        assert seedA["stock"] == seedB["stock"] == 5
        r = c.post(
            f"/v1/shop/items/{seedA['item_id']}/buy", json={"quantity": 2}, headers=hA
        ).json()
        assert r["code"] == 0
        # A 减了 2,B 不变
        a2 = next(i for i in c.get("/v1/shop/state", headers=hA).json()["data"]["items"] if i["code"] == "seed_shuidao")
        b2 = next(i for i in c.get("/v1/shop/state", headers=hB).json()["data"]["items"] if i["code"] == "seed_shuidao")
        assert a2["stock"] == 3 and b2["stock"] == 5


def test_sell_out_and_restock():
    """售空后拒绝购买;周期到点自动补货。"""
    with TestClient(app) as c:
        ah = _admin(c)
        # 默认库存调小 + 补货周期 1 秒
        r = c.put(
            "/v1/admin/shop/settings",
            json={"default_stock": 2, "restock_seconds": 1},
            headers=ah,
        ).json()
        assert r["code"] == 0
        h = _reg(c, "shop_sellout")
        seed = next(i for i in c.get("/v1/shop/state", headers=h).json()["data"]["items"] if i["code"] == "seed_shuidao")
        c.post(f"/v1/shop/items/{seed['item_id']}/buy", json={"quantity": 2}, headers=h)
        # 售空后再买 → NOT_ENOUGH_STOCK
        r = c.post(f"/v1/shop/items/{seed['item_id']}/buy", json={"quantity": 1}, headers=h).json()
        assert r["code"] == 22006
        # 等 1.2s 自动补货
        import time

        time.sleep(1.2)
        state = c.get("/v1/shop/state", headers=h).json()["data"]
        seed2 = next(i for i in state["items"] if i["code"] == "seed_shuidao")
        assert state["restocked"] is True and seed2["stock"] == 2


def test_season_price_fluctuation():
    """农作物收购价随季节涨降:春 1.1 / 夏 1.0 / 秋 1.2。"""
    with TestClient(app) as c:
        h = _reg(c, "shop_season")

        def quote():
            state = c.get("/v1/shop/state", headers=h).json()["data"]
            rice = next(q for q in state["crop_quotes"] if q["name"] == "水稻")
            return rice["sell_price"], state["season"]

        def advance_to(pred):
            for _ in range(30):
                if pred(c.get("/v1/calendar/current").json()["data"]["term_index"]):
                    return
                c.post("/v1/debug/term/advance", headers=h)

        advance_to(lambda t: 1 <= t <= 6)
        spring, s1 = quote()
        advance_to(lambda t: 7 <= t <= 12)
        summer, s2 = quote()
        advance_to(lambda t: 13 <= t <= 18)
        autumn, s3 = quote()
        assert s1 == "春" and s2 == "夏" and s3 == "秋"
        assert summer != spring
        assert autumn > summer  # 秋系数 1.2 > 夏 1.0


def test_harvest_storage_and_sell():
    """收获入收成仓 → 出售 → 金币增加,账本正确。"""
    with TestClient(app) as c:
        h = _reg(c, "shop_storage")
        # 推进到水稻宜种窗
        for _ in range(40):
            cal = c.get("/v1/calendar/current").json()["data"]
            if 5 <= cal["term_index"] <= 9:
                break
            c.post("/v1/debug/term/advance", headers=h)
        state = c.get("/v1/shop/state", headers=h).json()["data"]
        seed = next(i for i in state["items"] if i["code"] == "seed_shuidao")
        c.post(f"/v1/shop/items/{seed['item_id']}/buy", json={"quantity": 1}, headers=h)
        crop_id = seed["effect"]["crop_id"]
        plot = c.get("/v1/farm/state", headers=h).json()["data"]["plots"][0]["plot_id"]
        c.post(f"/v1/farm/plots/{plot}/sow", json={"crop_id": crop_id}, headers=h)
        c.post("/v1/debug/grow", json={"plot_id": plot}, headers=h)
        hv = c.post(f"/v1/farm/plots/{plot}/harvest", headers=h).json()
        assert hv["code"] == 0 and hv["data"]["storage_after"] == hv["data"]["yield"]
        # 收成仓
        st = c.get("/v1/shop/storage", headers=h).json()["data"]
        mine = next(i for i in st["items"] if i["name"] == "水稻")
        assert mine["quantity"] == hv["data"]["yield"] and mine["sell_price"] > 0
        # 出售
        before = c.get("/v1/player/me", headers=h).json()["data"]["coins"]
        r = c.post(
            f"/v1/shop/crops/{crop_id}/sell", json={"quantity": mine["quantity"]}, headers=h
        ).json()
        assert r["code"] == 0 and r["data"]["price"] > 0
        after = c.get("/v1/player/me", headers=h).json()["data"]["coins"]
        assert after == before + r["data"]["price"]
        # 出售过量 → NOT_ENOUGH_CROP
        r = c.post(f"/v1/shop/crops/{crop_id}/sell", json={"quantity": 1}, headers=h).json()
        assert r["code"] == 22007


def test_admin_shop_manage():
    """管理端:全局设置 / 每用户商品覆盖 / 补货 / 恢复公式价。"""
    with TestClient(app) as c:
        ah = _admin(c)
        h = _reg(c, "shop_admin")
        # 全局设置
        r = c.put(
            "/v1/admin/shop/settings",
            json={"default_stock": 3, "sell_factor": 0.5, "item_factor": 2.0},
            headers=ah,
        ).json()
        assert r["code"] == 0
        s = r["data"]
        assert s["default_stock"] == 3 and s["sell_factor"] == 0.5 and s["item_factor"] == 2.0
        # 每用户商店列表
        r = c.get("/v1/admin/shop/users", headers=ah).json()
        assert r["code"] == 0 and any(i["name"] == "shop_admin" for i in r["data"]["items"])
        mine = next(i for i in r["data"]["items"] if i["name"] == "shop_admin")
        pid = mine["player_id"]
        # 商品明细
        r = c.get(f"/v1/admin/shop/users/{pid}/items", headers=ah).json()
        seed = next(i for i in r["data"]["items"] if i["code"] == "seed_shuidao")
        assert seed["stock"] == 3 and seed["buy_override"] is None
        # 覆盖价格(水稻种子 25 × item_factor 2.0 = 50,覆盖为 40)
        r = c.put(
            f"/v1/admin/shop/users/{pid}/items/{seed['item_id']}",
            json={"buy_price": 40},
            headers=ah,
        ).json()
        assert r["code"] == 0 and r["data"]["buy_override"] == 40
        # 玩家视角看到覆盖价
        price = next(i for i in c.get("/v1/shop/state", headers=h).json()["data"]["items"] if i["code"] == "seed_shuidao")["buy_price"]
        assert price == 40
        # 清除覆盖 → 恢复公式价(25 × item_factor 2.0 = 50)
        c.put(f"/v1/admin/shop/users/{pid}/items/{seed['item_id']}", json={"buy_price": 99}, headers=ah)
        c.put(f"/v1/admin/shop/users/{pid}/items/{seed['item_id']}", json={"buy_price": None}, headers=ah)
        price2 = next(i for i in c.get("/v1/shop/state", headers=h).json()["data"]["items"] if i["code"] == "seed_shuidao")["buy_price"]
        assert price2 == 50  # 公式价(25 × item_factor 2.0)
        # 手动补货
        c.post(f"/v1/admin/shop/users/{pid}/restock", headers=ah)
        r_get = c.get(f"/v1/admin/shop/users/{pid}/items", headers=ah)
        assert r_get.status_code == 200, r_get.text
        stock = next(i for i in r_get.json()["data"]["items"] if i["code"] == "seed_shuidao")["stock"]
        assert stock == 3
