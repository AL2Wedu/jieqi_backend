"""虫害系统测试:配置 / 大虫害对抗(防作弊+奖惩) / 小虫害寄生(驱赶+到点摧毁)。"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import pest_service


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


def _plant(client, h, n=1):
    """种 n 株水稻,返回 plot_id 列表。"""
    # 先推进节气到水稻宜种窗(4-8 谷雨~立秋):每次 authed 请求会同步玩家世界
    for _ in range(30):
        cal = client.get("/v1/calendar/current", headers=h).json()["data"]
        if 4 <= cal["term_index"] <= 8:
            break
        client.post("/v1/debug/term/advance", headers=h)
    shop = client.get("/v1/shop/items", headers=h).json()["data"]["items"]
    seed = next(i for i in shop if i["code"] == "seed_shuidao")
    r = client.post(
        f"/v1/shop/items/{seed['item_id']}/buy", json={"quantity": n}, headers=h
    ).json()
    assert r["code"] == 0
    state = client.get("/v1/farm/state", headers=h).json()["data"]
    plots = state["plots"]
    for i in range(n):
        r = client.post(
            f"/v1/farm/plots/{plots[i]['plot_id']}/sow",
            json={"crop_id": seed["effect"]["crop_id"]},
            headers=h,
        ).json()
        assert r["code"] == 0, r
    return [p["plot_id"] for p in plots[:n]]


def _backdate_event(client, h, pest_id, seconds):
    """直接把事件的 broadcast_at 回拨(模拟音游时长流逝,绕过防作弊)。"""
    from app.core.db import SessionLocal
    from app.models import PestEvent

    with SessionLocal() as db:
        ev = db.query(PestEvent).filter(PestEvent.id == uuid.UUID(pest_id)).first()
        ev.broadcast_at = datetime.now(timezone.utc) - timedelta(seconds=seconds)
        db.commit()


def _backdate_target(client, h, pest_id, plot_id, seconds):
    from app.core.db import SessionLocal
    from app.models import PestTarget

    with SessionLocal() as db:
        t = (
            db.query(PestTarget)
            .filter(
                PestTarget.pest_id == uuid.UUID(pest_id),
                PestTarget.plot_id == uuid.UUID(plot_id),
            )
            .first()
        )
        t.ready_at = datetime.now(timezone.utc) - timedelta(seconds=seconds)
        db.commit()


def test_pest_config_admin(client):
    admin = client.post(
        "/v1/admin/login", json={"username": "admin", "password": "admin123"}
    ).json()
    ah = {"Authorization": f"Bearer {admin['data']['token']}"}
    # 默认值
    r = client.get("/v1/admin/pest/config", headers=ah).json()
    assert r["code"] == 0
    cfg = r["data"]
    assert cfg["pest.enabled"] is True
    assert cfg["pest.events_per_window"] == 3
    assert cfg["pest.window_terms"] == 2
    assert cfg["pest.big_duration_seconds"] == 30
    # JSON 往返后键为字符串;归一化再比(服务内部已归一化为 int 使用)
    assert {int(k): int(v) for k, v in cfg["pest.stage_wait"].items()} == {
        1: 120,
        2: 90,
        3: 60,
    }
    # 保存
    r = client.put(
        "/v1/admin/pest/config",
        json={"pest.events_per_window": 5, "pest.big_duration_seconds": 20},
        headers=ah,
    ).json()
    assert r["code"] == 0 and r["data"]["pest.events_per_window"] == 5
    # 还原
    client.put("/v1/admin/pest/config", json={"pest.events_per_window": 3, "pest.big_duration_seconds": 30}, headers=ah)


def test_pest_disabled(client):
    admin = client.post(
        "/v1/admin/login", json={"username": "admin", "password": "admin123"}
    ).json()
    ah = {"Authorization": f"Bearer {admin['data']['token']}"}
    client.put("/v1/admin/pest/config", json={"pest.enabled": False}, headers=ah)
    try:
        h = _reg(client, "pest_disabled")
        r = client.post("/v1/debug/pest/trigger", json={"type": "big"}, headers=h).json()
        assert r["code"] == 28002  # PEST_DISABLED
    finally:
        client.put("/v1/admin/pest/config", json={"pest.enabled": True}, headers=ah)


def test_small_pest_lifecycle(client, monkeypatch):
    h = _reg(client, "pest_small")
    plots = _plant(client, h, n=3)

    # 固定寄生数量为 3,避免随机 flaky(randint 由 fire_pest 内部调用)
    monkeypatch.setattr("app.services.pest_service.random.randint", lambda a, b: 3)
    # 触发小虫害(强制 small)
    r = client.post("/v1/debug/pest/trigger", json={"type": "small"}, headers=h).json()
    assert r["code"] == 0, r
    event = r["data"]
    assert event["type"] == "pest_small"
    targets = event["payload"]["targets"]
    assert 1 <= len(targets) <= 3
    for t in targets:
        assert t["plot_id"] in plots
        assert t["wait_seconds"] > 0

    # 状态接口可见
    st = client.get("/v1/pest/state", headers=h).json()["data"]
    assert len(st["active_small"]) == len(targets)
    assert st["active_big"] is None

    # 驱赶第一块
    t0 = targets[0]
    r = client.post(
        f"/v1/farm/pest/{t0['pest_id']}/drive-away",
        json={"plot_id": t0["plot_id"]},
        headers=h,
    ).json()
    assert r["code"] == 0 and r["data"]["destroyed"] is False
    st = client.get("/v1/pest/state", headers=h).json()["data"]
    assert len(st["active_small"]) == len(targets) - 1
    # 作物还在
    farm = client.get("/v1/farm/state", headers=h).json()["data"]
    crop_on_t0 = next(p for p in farm["plots"] if p["plot_id"] == t0["plot_id"])["crop"]
    assert crop_on_t0 is not None

    # 剩余目标到点摧毁(直接回拨 ready_at → 服务检查)
    from app.core.db import SessionLocal
    from app.models import PestTarget

    with SessionLocal() as db:
        for t in targets[1:]:
            tgt = db.query(PestTarget).filter(
                PestTarget.pest_id == uuid.UUID(t["pest_id"]),
                PestTarget.plot_id == uuid.UUID(t["plot_id"]),
            ).first()
            tgt.ready_at = datetime.now(timezone.utc) - timedelta(seconds=5)
        db.commit()  # 必须提交,否则退出上下文时回滚
    with SessionLocal() as db:
        from app.models import Player as P

        # 找 pest_small 玩家
        from app.models import User

        u = db.query(User).filter(User.name == "pest_small").first()
        player = db.query(P).filter(P.user_id == u.id).first()
        destroyed = pest_service.check_expiry(db, player)
    assert len(destroyed) == len(targets) - 1
    # 作物被摧毁 → 地块空了
    farm = client.get("/v1/farm/state", headers=h).json()["data"]
    for t in targets[1:]:
        p = next(p for p in farm["plots"] if p["plot_id"] == t["plot_id"])
        assert p["crop"] is None, f"地块 {t['plot_id']} 作物应被摧毁"
    # 摧毁后可重新播种(部分唯一索引不阻挡)
    r = client.post(
        f"/v1/farm/plots/{targets[1]['plot_id']}/sow",
        json={"crop_id": "00000000-0000-0000-0000-000000000000"},
        headers=h,
    ).json()
    assert r["code"] == 21005  # 作物不存在 → 播种校验正常(说明地块已可再种)
    # 状态清空
    st = client.get("/v1/pest/state", headers=h).json()["data"]
    assert len(st["active_small"]) == 0


def test_big_pest_antitamper_and_reward(client):
    h = _reg(client, "pest_big_ok")
    _plant(client, h, n=1)

    r = client.post("/v1/debug/pest/trigger", json={"type": "big"}, headers=h).json()
    assert r["code"] == 0
    ev = r["data"]["payload"]
    assert ev["type"] == "big" and ev["duration_seconds"] == 30

    # 立即提交 → 防作弊拒绝
    r = client.post(
        f"/v1/farm/pest/{ev['pest_id']}/result",
        json={"score": 100, "max_score": 100, "miss_count": 0},
        headers=h,
    ).json()
    assert r["code"] == 28006  # PEST_RESULT_TOO_FAST

    # 回拨 30×0.6=18s 之后 → 通过 → 达标 → 奖励
    _backdate_event(client, h, ev["pest_id"], 20)
    before = client.get("/v1/player/me", headers=h).json()["data"]["coins"]
    r = client.post(
        f"/v1/farm/pest/{ev['pest_id']}/result",
        json={"score": 90, "max_score": 100, "miss_count": 0},
        headers=h,
    ).json()
    assert r["code"] == 0, r
    assert r["data"]["passed"] is True
    assert r["data"]["reward"]["coins"] == 20
    after = client.get("/v1/player/me", headers=h).json()["data"]["coins"]
    assert after == before + 20
    # 重复提交 → 已结束
    r = client.post(
        f"/v1/farm/pest/{ev['pest_id']}/result",
        json={"score": 100, "max_score": 100, "miss_count": 0},
        headers=h,
    ).json()
    assert r["code"] == 28005  # PEST_NOT_FOUND


def test_big_pest_penalty(client):
    h = _reg(client, "pest_big_fail")
    plots = _plant(client, h, n=4)

    r = client.post("/v1/debug/pest/trigger", json={"type": "big"}, headers=h).json()
    ev = r["data"]["payload"]
    _backdate_event(client, h, ev["pest_id"], 20)
    # miss=4 → 惩罚寄生 4//2=2 块
    r = client.post(
        f"/v1/farm/pest/{ev['pest_id']}/result",
        json={"score": 10, "max_score": 100, "miss_count": 4},
        headers=h,
    ).json()
    assert r["code"] == 0
    assert r["data"]["passed"] is False
    assert r["data"]["penalty"]["targets"] == 2
    assert r["data"]["pest_small"] is not None
    # 惩罚寄生出现在状态里
    st = client.get("/v1/pest/state", headers=h).json()["data"]
    assert len(st["active_small"]) == 2
    for t in st["active_small"]:
        assert t["plot_id"] in plots
