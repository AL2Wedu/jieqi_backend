"""虫害系统测试:配置 / 大虫害对抗(防作弊+奖惩) / 小虫害寄生(驱赶+到点摧毁)。"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.core.db import SessionLocal
from app.core.utils import ensure_aware
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
    # 先推进节气到水稻宜种窗(5清明~8小满):每次 authed 请求会同步玩家世界
    for _ in range(30):
        cal = client.get("/v1/calendar/current", headers=h).json()["data"]
        if 5 <= cal["term_index"] <= 8:
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


def _player(db, name):
    from app.models import Player as P
    from app.models import User

    u = db.query(User).filter(User.name == name).first()
    return db.query(P).filter(P.user_id == u.id).first()


def _set_world_term(client, h, name, term_idx):
    """把玩家世界推到指定节气起点(虫害季节/窗口测试用)。"""
    from app.core.db import SessionLocal
    from app.models import TermConfig
    from app.services import world_service

    with SessionLocal() as db:
        terms = db.query(TermConfig).order_by(TermConfig.term_index).all()
        accum = sum(t.duration_seconds for t in terms if t.term_index < term_idx)
        player = _player(db, name)
        world_service.set_world(db, player, accum=accum)
    client.get("/v1/calendar/current", headers=h)  # 触发一次同步,刷新世界


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
    # 节气/季节驱动配置默认值
    at = cfg["pest.active_terms"]
    assert int(at["start"]) == 3 and int(at["end"]) == 18  # 惊蛰~霜降
    assert cfg["pest.season_frequency"]["summer"] == 1.5  # 盛夏最频繁
    assert cfg["pest.season_big_ratio"]["summer"] == 0.5  # 盛夏大虫灾最多
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


# ---------- 节气/季节驱动 + 离线补偿 ----------

def test_no_pest_in_winter(client):
    """冬季(立冬~大寒)不排虫:is_due 恒 False,状态标记非活跃,回归补偿清空排程。"""
    h = _reg(client, "pest_winter")
    _plant(client, h, n=2)
    _set_world_term(client, h, "pest_winter", 19)  # 立冬

    with SessionLocal() as db:
        player = _player(db, "pest_winter")
        # 即便排程已过期也不触发(冬天没有虫子)
        player.next_pest_at = datetime.now(timezone.utc) - timedelta(hours=1)
        db.commit()
        assert pest_service.is_due(db, player) is False
        st = pest_service.player_state(db, player)
        assert st["season"] == "winter" and st["pest_active"] is False
        # 离线回归:非活跃窗口 → 清空排程
        pest_service.sync_offline(db, player)
        assert player.next_pest_at is None


def test_no_pest_early_spring_boundary(client):
    """活跃窗口边界:雨水(2)无虫,惊蛰(3)起有虫。"""
    h = _reg(client, "pest_boundary")
    _plant(client, h, n=1)
    _set_world_term(client, h, "pest_boundary", 2)  # 雨水(惊蛰前,未复苏)
    with SessionLocal() as db:
        player = _player(db, "pest_boundary")
        player.next_pest_at = datetime.now(timezone.utc) - timedelta(hours=1)
        db.commit()
        assert pest_service.is_due(db, player) is False
    _set_world_term(client, h, "pest_boundary", 3)  # 惊蛰(万物复苏,虫害开始)
    with SessionLocal() as db:
        player = _player(db, "pest_boundary")
        player.next_pest_at = datetime.now(timezone.utc) - timedelta(hours=1)
        db.commit()
        assert pest_service.is_due(db, player) is True
        st = pest_service.player_state(db, player)
        assert st["season"] == "spring" and st["pest_active"] is True


def test_offline_return_defers_pest(client):
    """离线回归:错过排程顺延到未来,不立即触发。"""
    h = _reg(client, "pest_offline")
    _plant(client, h, n=1)
    _set_world_term(client, h, "pest_offline", 9)  # 芒种(夏季活跃窗)

    with SessionLocal() as db:
        player = _player(db, "pest_offline")
        player.next_pest_at = datetime.now(timezone.utc) - timedelta(hours=3)
        db.commit()
        # 未补偿:会立即触发(离线期间错过)
        assert pest_service.is_due(db, player) is True
        # 回归补偿:顺延到未来完整间隔,不再立即突袭
        pest_service.sync_offline(db, player)
        assert player.next_pest_at is not None
        assert ensure_aware(player.next_pest_at) > datetime.now(timezone.utc) + timedelta(seconds=1)
        assert pest_service.is_due(db, player) is False


def test_season_frequency_interval(client, monkeypatch):
    """夏季触发间隔短于春季(频率倍率 1.5 vs 0.6)。"""
    h = _reg(client, "pest_season")
    _plant(client, h, n=1)
    monkeypatch.setattr("app.services.pest_service.random.uniform", lambda a, b: 1.0)

    from app.core.utils import ensure_aware

    def _interval(term_idx):
        _set_world_term(client, h, "pest_season", term_idx)
        with SessionLocal() as db:
            player = _player(db, "pest_season")
            now = datetime.now(timezone.utc)
            pest_service.schedule_next(db, player, now)
            return (ensure_aware(player.next_pest_at) - now).total_seconds()

    spring = _interval(4)  # 春分 spring 0.6 → 间隔拉长
    summer = _interval(9)  # 芒种 summer 1.5 → 间隔缩短
    assert summer < spring  # 盛夏更频繁


def test_season_big_ratio(client, monkeypatch):
    """盛夏大虫害比例最高,春秋低;行为:同随机数在夏季出大虫、春季出小虫。"""
    h = _reg(client, "pest_bigratio")
    _plant(client, h, n=1)

    def _ratio(term_idx):
        _set_world_term(client, h, "pest_bigratio", term_idx)
        with SessionLocal() as db:
            return pest_service.season_big_ratio(db, _player(db, "pest_bigratio"))

    summer_r = _ratio(9)   # 芒种 summer 0.5
    spring_r = _ratio(4)   # 春分 spring 0.3
    autumn_r = _ratio(15)  # 白露 autumn 0.2
    assert summer_r > spring_r > autumn_r

    # 行为验证:random()=0.4 → 夏季(0.5)出大虫,春季(0.3)出小虫
    monkeypatch.setattr("app.services.pest_service.random.random", lambda: 0.4)
    _set_world_term(client, h, "pest_bigratio", 9)
    with SessionLocal() as db:
        ev = pest_service.fire_pest(db, _player(db, "pest_bigratio"))  # forced_type=None → 按季节比例
        assert ev["type"] == "pest_big", ev
    client.post("/v1/debug/pest/clear", headers=h)
    _set_world_term(client, h, "pest_bigratio", 4)
    with SessionLocal() as db:
        ev = pest_service.fire_pest(db, _player(db, "pest_bigratio"))
        assert ev["type"] == "pest_small", ev
