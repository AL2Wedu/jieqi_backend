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


def test_weed_replaces_next_round(client):
    """新一次生长先清除旧杂草再重新随机(杂草存活不超过一个节气)。"""
    h = _reg(client, "weed_t3")
    r1 = client.post("/v1/debug/weed/trigger", headers=h).json()
    first = {t["idx"] for t in r1["data"]["targets"]}
    assert first
    r2 = client.post("/v1/debug/weed/trigger", headers=h).json()
    second = {t["idx"] for t in r2["data"]["targets"]}
    st = client.get("/v1/farm/state", headers=h).json()["data"]
    weeded_now = {p["idx"] for p in st["plots"] if p["weeded"]}
    assert weeded_now == second  # 旧杂草已被清除,只剩新一轮
    assert len(weeded_now) <= 3
