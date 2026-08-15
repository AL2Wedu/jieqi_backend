"""杂草系统测试:触发/地块标记/生长减速/节气调度/重新随机。"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.db import SessionLocal
from app.models import Player, User


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


def test_weed_trigger_and_state(client):
    """触发杂草生长 → 随机地块 weeded 标记 → 清除。"""
    h = _reg(client, "weed_t1")
    r = client.post("/v1/debug/weed/trigger", headers=h).json()
    assert r["code"] == 0, r
    targets = r["data"]["targets"]
    assert 1 <= len(targets) <= 3

    st = client.get("/v1/farm/state", headers=h).json()["data"]
    weeded = [p for p in st["plots"] if p["weeded"]]
    assert len(weeded) == len(targets)
    assert {p["idx"] for p in weeded} == {t["idx"] for t in targets}

    r = client.post("/v1/debug/weed/clear", headers=h).json()
    assert r["code"] == 0 and r["data"]["cleared"] == len(targets)
    st = client.get("/v1/farm/state", headers=h).json()["data"]
    assert all(not p["weeded"] for p in st["plots"])


def test_weed_slowdown():
    """杂草地块生长速度 × slow_factor(默认 0.5,进度减半)。"""
    from app.models import Crop, CropInstance
    from app.services.farm_service import crop_view

    now = datetime.now(timezone.utc)
    crop = Crop(
        id=uuid.uuid4(), name="测试", category="谷物",
        grow_seconds=1000, yield_base=1, base_price=1, settings={},
    )
    ci = CropInstance(
        id=uuid.uuid4(), plot_id=uuid.uuid4(), crop_id=crop.id,
        sowed_at=now - timedelta(seconds=400), sowed_term_index=1,
        water_level=100, extra={"term_dur": 300},
    )
    normal = crop_view(ci, crop)["growth_progress"]
    slow = crop_view(ci, crop, weeded=True, slow_factor=0.5)["growth_progress"]
    assert normal == 40 and slow == 20, (normal, slow)


def test_weed_schedule_fires(client):
    """每个节气内随机时刻触发一次:首次检查排程 → 到点触发 → 重新排程。"""
    h = _reg(client, "weed_t2")
    from app.services import weed_service, world_service

    with SessionLocal() as db:
        u = db.query(User).filter(User.name == "weed_t2").first()
        player = db.query(Player).filter(Player.user_id == u.id).first()
        # 首次检查:只排程,不触发
        assert weed_service.check_weed(db, player) == []
        assert player.weed_scheduled_accum is not None
        target = float(player.weed_scheduled_accum)
        # 世界时间推到触发点之后 → 触发并重新排程
        world_service.set_world(db, player, accum=target + 1)
        targets = weed_service.check_weed(db, player)
        assert len(targets) >= 1
        assert float(player.weed_scheduled_accum) > target  # 已排到下一节气


def test_weed_accumulates(client):
    """杂草累积:新一次生长不清除旧草,只在未长草地块新增。"""
    h = _reg(client, "weed_t3")
    r1 = client.post("/v1/debug/weed/trigger", headers=h).json()
    first = {t["idx"] for t in r1["data"]["targets"]}
    assert first
    r2 = client.post("/v1/debug/weed/trigger", headers=h).json()
    second = {t["idx"] for t in r2["data"]["targets"]}
    st = client.get("/v1/farm/state", headers=h).json()["data"]
    weeded_now = {p["idx"] for p in st["plots"] if p["weeded"]}
    # 旧草仍在,新增不重叠(候选只选未长草地)
    assert first <= weeded_now
    assert first.isdisjoint(second)
    assert len(weeded_now) == len(first) + len(second) == len(first | second)


def test_sow_clears_weed_on_plot(client):
    """播种(翻地)清除该地块杂草,不影响其他地块。"""
    h = _reg(client, "weed_sow")
    # 先推进到水稻宜种窗,再触发杂草(避免播种后推进节气时新杂草又盖回)
    for _ in range(30):
        cal = client.get("/v1/calendar/current", headers=h).json()["data"]
        if 5 <= cal["term_index"] <= 8:
            break
        client.post("/v1/debug/term/advance", headers=h)
    client.post("/v1/debug/weed/trigger", headers=h)
    st = client.get("/v1/farm/state", headers=h).json()["data"]
    weeded = [p for p in st["plots"] if p["weeded"] and p["crop"] is None]
    assert weeded
    target = weeded[0]

    shop = client.get("/v1/shop/items", headers=h).json()["data"]["items"]
    seed = next(i for i in shop if i["code"] == "seed_shuidao")
    client.post(f"/v1/shop/items/{seed['item_id']}/buy", json={"quantity": 1}, headers=h)
    r = client.post(
        f"/v1/farm/plots/{target['plot_id']}/sow",
        json={"crop_id": seed["effect"]["crop_id"]},
        headers=h,
    ).json()
    assert r["code"] == 0, r
    # 直接查 DB 确认该格已清草(不走 farm/state,避免其 check_weed 副作用可能的新杂草)
    from app.models import Farm, Plot as PlotM, Player, User

    with SessionLocal() as db:
        u = db.query(User).filter(User.name == "weed_sow").first()
        player = db.query(Player).filter(Player.user_id == u.id).first()
        farm = db.query(Farm).filter(Farm.owner_id == player.id).first()
        p = (
            db.query(PlotM)
            .filter(PlotM.farm_id == farm.id, PlotM.id == uuid.UUID(target["plot_id"]))
            .first()
        )
        assert p.weeded is False  # 翻地清草
        others = db.query(PlotM).filter(PlotM.farm_id == farm.id, PlotM.weeded.is_(True)).all()
        assert {o.id for o in others} == {
            uuid.UUID(x["plot_id"]) for x in weeded if x["plot_id"] != target["plot_id"]
        }  # 只清该格,其他格杂草保留


def test_weed_max_total_cap(client):
    """杂草总量上限:触发多次也不超过 weed.max_total(调到小值验证)。"""
    h = _reg(client, "weed_cap")
    admin = client.post(
        "/v1/admin/login", json={"username": "admin", "password": "admin123"}
    ).json()
    ah = {"Authorization": f"Bearer {admin['data']['token']}"}
    client.put("/v1/admin/config/weed.max_total", json={"value": 4}, headers=ah)
    try:
        for _ in range(6):
            client.post("/v1/debug/weed/trigger", headers=h)
        st = client.get("/v1/farm/state", headers=h).json()["data"]
        weeded = [p for p in st["plots"] if p["weeded"]]
        assert len(weeded) <= 4  # 上限生效
    finally:
        client.delete("/v1/admin/config/weed.max_total", headers=ah)


def test_weed_clear_single_plot(client):
    """POST /v1/farm/plots/{id}/weed-clear:只清所选格的杂草,不影响其他格。"""
    h = _reg(client, "weed_clear1")
    r = client.post("/v1/debug/weed/trigger", headers=h).json()
    targets = r["data"]["targets"]
    assert len(targets) >= 2  # 至少覆盖 2 格,验证"只清一格"
    target = targets[0]

    # 清掉选中的格
    r = client.post(f"/v1/farm/plots/{target['plot_id']}/weed-clear", headers=h).json()
    assert r["code"] == 0, r
    assert r["data"]["cleared"] is True and r["data"]["idx"] == target["idx"]

    st = client.get("/v1/farm/state", headers=h).json()["data"]
    weeded = {p["idx"] for p in st["plots"] if p["weeded"]}
    assert target["idx"] not in weeded  # 所选格已清
    assert weeded == {t["idx"] for t in targets[1:]}  # 其他格仍带杂草

    # 幂等:再清一次原本已无杂草的格 → cleared=False
    r = client.post(f"/v1/farm/plots/{target['plot_id']}/weed-clear", headers=h).json()
    assert r["code"] == 0 and r["data"]["cleared"] is False


def test_weed_clear_foreign_or_missing_plot(client):
    """清除不属于自己的地块 / 不存在的地块 → 21001 PLOT_NOT_FOUND。"""
    h = _reg(client, "weed_clear2")
    h_other = _reg(client, "weed_clear3")
    # 他人地块触发杂草
    client.post("/v1/debug/weed/trigger", headers=h_other).json()
    other = client.get("/v1/farm/state", headers=h_other).json()["data"]
    foreign_plot = next(p["plot_id"] for p in other["plots"] if p["weeded"])

    r = client.post(f"/v1/farm/plots/{foreign_plot}/weed-clear", headers=h).json()
    assert r["code"] == 21001 and r["error_code"] == "PLOT_NOT_FOUND", r

    # 不存在的地块
    r = client.post(
        f"/v1/farm/plots/{uuid.uuid4()}/weed-clear", headers=h
    ).json()
    assert r["code"] == 21001 and r["error_code"] == "PLOT_NOT_FOUND", r

    # 非法 UUID
    r = client.post("/v1/farm/plots/not-a-uuid/weed-clear", headers=h).json()
    assert r["code"] == 21001 and r["error_code"] == "PLOT_NOT_FOUND", r
