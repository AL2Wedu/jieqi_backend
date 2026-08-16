"""植物设定系统测试:JSONC 加载 / 解锁经验 / 季节加速 / 水分衰减停滞 / 枯萎 / 肥力减产 / 单株价值上限 / 文件同步。"""
import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.db import SessionLocal
from app.models import Crop, CropInstance, User


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
    r = client.post(
        "/v1/admin/login", json={"username": "admin", "password": "admin123"}
    ).json()
    assert r["code"] == 0
    return {"Authorization": f"Bearer {r['data']['token']}"}

def _advance_term(client, h, target_range):
    """推进节气直到落在 target_range(闭区间);玩家世界随 authed 请求同步。"""
    for _ in range(30):
        cal = client.get("/v1/calendar/current", headers=h).json()["data"]
        if target_range[0] <= cal["term_index"] <= target_range[1]:
            return cal["term_index"]
        client.post("/v1/debug/term/advance", headers=h)
    raise AssertionError("节气推进超限")


def _buy_seed(client, h, seed_code, n=1):
    shop = client.get("/v1/shop/items", headers=h).json()["data"]["items"]
    seed = next(i for i in shop if i["code"] == seed_code)
    r = client.post(
        f"/v1/shop/items/{seed['item_id']}/buy", json={"quantity": n}, headers=h
    ).json()
    assert r["code"] == 0, r
    return seed


def _sow(client, h, seed, plot_id):
    return client.post(
        f"/v1/farm/plots/{plot_id}/sow",
        json={"crop_id": seed["effect"]["crop_id"]},
        headers=h,
    ).json()


def _player_by_name(name):
    with SessionLocal() as db:
        u = db.query(User).filter(User.name == name).first()
        from app.models import Player

        return db.query(Player).filter(Player.user_id == u.id).first()


# ---------- 1. JSONC 加载器 ----------

def test_jsonc_loader():
    """每株植物一个 JSONC 文件,注释可剥离;模板文件不导入。"""
    from scripts.crop_loader import load_crops

    crops = load_crops()
    slugs = {c["slug"] for c in crops}
    assert {"shuidao", "xiaomai", "mianhua"} <= slugs
    assert all(not c.get("_template") for c in crops)
    rice = next(c for c in crops if c["slug"] == "shuidao")
    assert rice["settings"]["water_need"]["min"] == 60
    assert rice["settings"]["fast_growth_seasons"] == {"summer": 1.5}


# ---------- 2. 解锁经验 ----------

def test_unlock_exp_gate(client):
    """棉花需 300 经验/6 级:新玩家被锁(商店购买 + 播种双门控);admin 给经验后解锁。"""
    h = _reg(client, "unlock_cotton")
    _advance_term(client, h, (5, 7))  # 棉花宜种窗
    shop = client.get("/v1/shop/items", headers=h).json()["data"]["items"]
    seed = next(i for i in shop if i["code"] == "seed_mianhua")
    state = client.get("/v1/farm/state", headers=h).json()["data"]
    pid = state["plots"][0]["plot_id"]

    # 新玩家:商店购买被拒(ITEM_LOCKED,种子跟随作物解锁)
    r = client.post(
        f"/v1/shop/items/{seed['item_id']}/buy", json={"quantity": 1}, headers=h
    ).json()
    assert r["code"] == 22008 and r["error_code"] == "ITEM_LOCKED", r

    # 管理端直接发种子(绕过商店)→ 播种仍被锁(CROP_LOCKED)
    ah = _admin(client)
    users = client.get("/v1/admin/users?page_size=50", headers=ah).json()["data"]["items"]
    uid = next(u["user_id"] for u in users if u["name"] == "unlock_cotton")
    r = client.put(
        f"/v1/admin/users/{uid}/inventory/{seed['item_id']}",
        json={"quantity": 1}, headers=ah,
    ).json()
    assert r["code"] == 0, r
    r = _sow(client, h, seed, pid)
    assert r["code"] == 21008, r  # CROP_LOCKED
    assert r["error_code"] == "CROP_LOCKED"

    # admin 给 300 经验 → 解锁:可买 + 可种
    client.patch(f"/v1/admin/users/{uid}/assets", json={"exp": 300}, headers=ah)
    r = client.post(
        f"/v1/shop/items/{seed['item_id']}/buy", json={"quantity": 1}, headers=h
    ).json()
    assert r["code"] == 0, r
    r = _sow(client, h, seed, pid)
    assert r["code"] == 0, r


# ---------- 3. 季节加速 ----------

def test_fast_growth_season(client):
    """水稻夏季播种(term 7)→ 生长时长 300/1.5 = 200 秒。"""
    h = _reg(client, "fast_rice")
    _advance_term(client, h, (7, 7))
    seed = _buy_seed(client, h, "seed_shuidao")
    state = client.get("/v1/farm/state", headers=h).json()["data"]
    r = _sow(client, h, seed, state["plots"][0]["plot_id"])
    assert r["code"] == 0, r
    assert r["data"]["grow_seconds_eff"] == 200
    assert r["data"]["season_boost"] == 1.5


# ---------- 4. 水分衰减 + 生长停滞(纯推导,单元级) ----------

def test_water_decay_and_stall():
    """水分每节气 -10;跌破需水红线后进度冻结在红线时刻。"""
    from app.services.farm_service import crop_view

    now = datetime.now(timezone.utc)
    crop = Crop(
        id=uuid.uuid4(),
        name="测试长作物",
        category="谷物",
        grow_seconds=4000,
        yield_base=1,
        base_price=1,
        settings={"water_need": {"min": 60, "ideal": 90}},
    )
    # 播种 2400s = 8 个节气(term_dur 300)→ 水分 100-80=20 < 60;红线在 1200s → 冻结 1200/4000=30%
    ci = CropInstance(
        id=uuid.uuid4(),
        plot_id=uuid.uuid4(),
        crop_id=crop.id,
        sowed_at=now - timedelta(seconds=2400),
        sowed_term_index=1,
        water_level=100,
        extra={"term_dur": 300},
    )
    view = crop_view(ci, crop)
    assert view["water_level"] == 20
    assert view["growth_progress"] == 30  # 停滞冻结,而非 60%

    # 浇过水(2 个节气前)→ 水分 100-20=80,未破红线 → 正常推进
    ci2 = CropInstance(
        id=uuid.uuid4(),
        plot_id=uuid.uuid4(),
        crop_id=crop.id,
        sowed_at=now - timedelta(seconds=4000),
        sowed_term_index=1,
        water_level=100,
        extra={"term_dur": 300, "watered_at": (now - timedelta(seconds=600)).isoformat()},
    )
    view2 = crop_view(ci2, crop)
    assert view2["water_level"] == 80
    assert view2["growth_progress"] == 100  # 无停滞,照常成熟


# ---------- 5. 枯萎(改状态:冻死仍占地块,可铲除或收割,不直接消失) ----------

def test_wither_on_season(client):
    """玩家世界进入冬季 → 未收获水稻标记枯萎(仍占地块,status=wilted,不直接消失)。"""
    h = _reg(client, "wither_rice")
    _advance_term(client, h, (5, 8))  # 水稻宜种窗(清明~小满)
    seed = _buy_seed(client, h, "seed_shuidao")
    state = client.get("/v1/farm/state", headers=h).json()["data"]
    r = _sow(client, h, seed, state["plots"][0]["plot_id"])
    assert r["code"] == 0, r

    # 玩家世界推到冬季(立冬 term 19 起点);按实际节气时长计算(鲁棒于时长被改)
    from app.models import Player, TermConfig
    from app.services import world_service

    with SessionLocal() as db:
        terms = db.query(TermConfig).order_by(TermConfig.term_index).all()
        accum = sum(t.duration_seconds for t in terms[:18])
        u = db.query(User).filter(User.name == "wither_rice").first()
        player = db.query(Player).filter(Player.user_id == u.id).first()
        world_service.set_world(db, player, accum=accum)

    st = client.get("/v1/farm/state", headers=h).json()["data"]
    assert st["current_term"]["name"] == "立冬", st["current_term"]  # 确保真的在冬季
    assert len(st["wither_events"]) == 1
    assert st["wither_events"][0]["crop_name"] == "水稻"
    plot = next(p for p in st["plots"] if p["idx"] == 1)
    assert plot["crop"] is not None  # 枯萎作物仍在地块,不直接消失
    assert plot["crop"]["status"] == "wilted"  # 前端据此显示"植物冻死了"
    assert plot["crop"]["name"] == "水稻"

    # 枯萎作物不能浇水
    r = client.post(f"/v1/farm/plots/{plot['plot_id']}/water", headers=h).json()
    assert r["code"] == 21009 and r["error_code"] == "CROP_WILTED", r

    # 铲除(clear)清掉枯萎作物 → 地块可再种
    r = client.post(f"/v1/farm/plots/{plot['plot_id']}/clear", headers=h).json()
    assert r["code"] == 0 and r["data"]["wilted"] is True
    st = client.get("/v1/farm/state", headers=h).json()["data"]
    plot = next(p for p in st["plots"] if p["idx"] == 1)
    assert plot["crop"] is None


def test_wilted_harvest_salvage_and_sell(client):
    """枯萎作物收割:产量减半,入仓为劣质收成(wilted_quantity),售价大打折扣。"""
    h = _reg(client, "wilt_rice_harvest")
    _advance_term(client, h, (5, 8))
    seed = _buy_seed(client, h, "seed_shuidao")
    state = client.get("/v1/farm/state", headers=h).json()["data"]
    pid = state["plots"][0]["plot_id"]
    r = _sow(client, h, seed, pid)
    assert r["code"] == 0, r

    # 推到冬季触发枯萎
    from app.models import Player, TermConfig
    from app.services import world_service

    with SessionLocal() as db:
        terms = db.query(TermConfig).order_by(TermConfig.term_index).all()
        accum = sum(t.duration_seconds for t in terms[:18])
        u = db.query(User).filter(User.name == "wilt_rice_harvest").first()
        player = db.query(Player).filter(Player.user_id == u.id).first()
        world_service.set_world(db, player, accum=accum)

    st = client.get("/v1/farm/state", headers=h).json()["data"]
    assert next(p for p in st["plots"] if p["idx"] == 1)["crop"]["status"] == "wilted"

    # 收割枯萎作物:水稻 base6 × 肥力加成1.0 × 枯萎系数0.5 = 3(不必成熟也能抢收)
    r = client.post(f"/v1/farm/plots/{pid}/harvest", headers=h).json()
    assert r["code"] == 0, r
    assert r["data"]["wilted"] is True
    assert r["data"]["yield"] == 3

    # 收成仓:全部为劣质收成;冬季正常价 20×0.8×0.9×1.0=14,枯萎价 round(14×0.3)=4
    storage = client.get("/v1/shop/storage", headers=h).json()["data"]["items"]
    rice = next(i for i in storage if i["name"] == "水稻")
    assert rice["quantity"] == 3 and rice["wilted_quantity"] == 3
    assert rice["sell_price"] == 14
    assert rice["wilted_sell_price"] == 4

    # 3 株枯萎 = 12 金币
    r = client.post(
        f"/v1/shop/crops/{seed['effect']['crop_id']}/sell",
        json={"quantity": 3},
        headers=h,
    ).json()
    assert r["code"] == 0, r
    assert r["data"]["price"] == 12
    assert r["data"]["wilted"] == 3


def test_mixed_storage_sell_price(client):
    """收成仓正常+枯萎混合出售:先扣正常价,再扣枯萎打折价。"""
    h = _reg(client, "mixed_sell")
    _advance_term(client, h, (5, 8))
    seed = _buy_seed(client, h, "seed_shuidao")
    state = client.get("/v1/farm/state", headers=h).json()["data"]
    pid = state["plots"][0]["plot_id"]

    # 第一株正常收获(未枯萎):base6 × 肥力1.0 = 6
    r = _sow(client, h, seed, pid)
    assert r["code"] == 0, r
    client.post("/v1/debug/grow", json={"plot_id": pid}, headers=h)
    hv = client.post(f"/v1/farm/plots/{pid}/harvest", headers=h).json()
    assert hv["code"] == 0 and hv["data"]["wilted"] is False
    assert hv["data"]["yield"] == 6

    # 第二株种下后推到冬季 → 枯萎 → 收割(6×0.5=3 劣质入仓)
    seed2 = _buy_seed(client, h, "seed_shuidao")
    r = _sow(client, h, seed2, pid)
    assert r["code"] == 0, r
    from app.models import Player, TermConfig
    from app.services import world_service

    with SessionLocal() as db:
        terms = db.query(TermConfig).order_by(TermConfig.term_index).all()
        accum = sum(t.duration_seconds for t in terms[:18])
        u = db.query(User).filter(User.name == "mixed_sell").first()
        player = db.query(Player).filter(Player.user_id == u.id).first()
        world_service.set_world(db, player, accum=accum)
    st = client.get("/v1/farm/state", headers=h).json()["data"]
    assert next(p for p in st["plots"] if p["idx"] == 1)["crop"]["status"] == "wilted"
    r = client.post(f"/v1/farm/plots/{pid}/harvest", headers=h).json()
    assert r["code"] == 0 and r["data"]["wilted"] is True and r["data"]["yield"] == 3

    storage = client.get("/v1/shop/storage", headers=h).json()["data"]["items"]
    rice = next(i for i in storage if i["name"] == "水稻")
    assert rice["quantity"] == 9 and rice["wilted_quantity"] == 3  # 6正常 + 3枯萎

    # 冬季正常 14/枯萎 4;卖 7 先扣正常(6×14 + 1×4)= 88,剩余 0 正常 + 2 枯萎
    r = client.post(
        f"/v1/shop/crops/{seed['effect']['crop_id']}/sell",
        json={"quantity": 7},
        headers=h,
    ).json()
    assert r["code"] == 0, r
    assert r["data"]["price"] == 88
    assert r["data"]["wilted"] == 1
    storage = client.get("/v1/shop/storage", headers=h).json()["data"]["items"]
    rice = next(i for i in storage if i["name"] == "水稻")
    assert rice["quantity"] == 2 and rice["wilted_quantity"] == 2

    # 剩余 2 株枯萎全卖 = 2×4 = 8
    r = client.post(
        f"/v1/shop/crops/{seed['effect']['crop_id']}/sell",
        json={"quantity": 2},
        headers=h,
    ).json()
    assert r["code"] == 0, r
    assert r["data"]["price"] == 8
    assert r["data"]["wilted"] == 2


# ---------- 6. 肥力减产 ----------

def test_fertility_penalty(client):
    """玉米需肥力 2,地块肥力 1 → 产量 7×1.0×(1/2)=3.5 → 4。"""
    h = _reg(client, "fert_corn")
    ah = _admin(client)
    users = client.get("/v1/admin/users?page_size=50", headers=ah).json()["data"]["items"]
    uid = next(u["user_id"] for u in users if u["name"] == "fert_corn")
    crops = client.get("/v1/admin/crops", headers=ah).json()["data"]["items"]
    corn = next(c for c in crops if c["name"] == "玉米")
    r = client.put(
        f"/v1/admin/users/{uid}/plots/1/crop",
        json={"crop_id": corn["crop_id"], "growth_progress": 100, "water_level": 100},
        headers=ah,
    ).json()
    assert r["code"] == 0, r
    # 玩家收获 → 入仓
    state = client.get("/v1/farm/state", headers=h).json()["data"]
    pid = next(p for p in state["plots"] if p["idx"] == 1)["plot_id"]
    r = client.post(f"/v1/farm/plots/{pid}/harvest", headers=h).json()
    assert r["code"] == 0, r
    assert r["data"]["yield"] == 4  # 7 × (1/2) = 3.5 → round → 4


# ---------- 7. 单株价值上限 ----------

def test_max_value_cap():
    """单株价值上限:公式价超过 settings.max_value → 封顶;未超不封顶。"""
    from app.services.shop_service import ShopSettings, _crop_price

    s = ShopSettings(
        id=1,
        sell_factor=2.0,
        season_effect={"spring": 1.1, "summer": 1.0, "autumn": 1.2, "winter": 0.9},
        category_factor={"谷物": 1.0, "蔬菜": 1.1},
    )
    rice = Crop(
        id=uuid.uuid4(), name="水稻", category="谷物",
        grow_seconds=300, yield_base=6, base_price=20,
        settings={"max_value": 30},
    )
    # 20×2×1.1×1.0 = 44 → 封顶 30
    assert _crop_price(rice, s, "spring") == 30
    # 无 max_value 设定 → 不封顶
    rice2 = Crop(
        id=uuid.uuid4(), name="水稻", category="谷物",
        grow_seconds=300, yield_base=6, base_price=20,
        settings={},
    )
    assert _crop_price(rice2, s, "spring") == 44


# ---------- 8. 文件 → DB 同步 ----------

def test_sync_crops_from_files(client):
    """修改植物 JSON 文件 → sync_crops 幂等 upsert 到 DB。"""
    from scripts import crop_loader
    from scripts.seed import sync_crops

    p = crop_loader.CROPS_DIR / "luobo.json"
    data = json.loads(crop_loader.strip_jsonc(p.read_text(encoding="utf-8")))
    data["grow_seconds"] = 12345
    crop_loader.dump_crop_file(data, "luobo.json")

    with SessionLocal() as db:
        changed = sync_crops(db)
        assert changed > 0
    with SessionLocal() as db:
        luobo = db.query(Crop).filter(Crop.name == "萝卜").first()
        assert luobo.grow_seconds == 12345
