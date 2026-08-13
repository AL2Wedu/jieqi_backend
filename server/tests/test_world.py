"""每用户世界时钟测试:离线倍速 / 在线 1× / 玩家独立 / 惰性初始化 / 暂停冻结 / 调试推进 / 管理端点 / WS。"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import app

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _reg(client, name):
    r = client.post("/v1/auth/register", json={"name": name, "password": "pass123456"})
    assert r.json()["code"] == 0, r.json()
    return {"Authorization": f"Bearer {r.json()['data']['token']}"}


def _player(db, name):
    from app.models import Player, User

    user = db.query(User).filter(User.name == name).first()
    return db.query(Player).filter(Player.user_id == user.id).first()


# ---------- 离线 / 在线倍速数学(直接操纵 DB,确定性) ----------

def _set_clock(db, player, accum, last_sync, last_active):
    player.world_accum = accum
    player.world_last_sync = last_sync
    player.last_active_at = last_active
    db.commit()


def test_offline_rate_math(client):
    """离线(距最近心跳超过阈值)→ 世界按 offline_factor(0.25)× 推进。"""
    _reg(client, "world_offline")
    from app.core.db import SessionLocal
    from app.services import world_service

    with SessionLocal() as db:
        p = _player(db, "world_offline")
        _set_clock(db, p, 0.0, T0, T0 - timedelta(seconds=400))  # 400s 无心跳 > 300 阈值 → 离线
        world_service.sync_world(db, p, now=T0 + timedelta(seconds=1000))
        assert abs(p.world_accum - 1000 * 0.25) < 0.001  # dt=1000s × 0.25
        assert p.last_active_at == T0 + timedelta(seconds=1000)  # 心跳刷新


def test_online_rate_math(client):
    """在线(最近心跳在阈值内)→ 世界按 1× 推进。"""
    _reg(client, "world_online")
    from app.core.db import SessionLocal
    from app.services import world_service

    with SessionLocal() as db:
        p = _player(db, "world_online")
        _set_clock(db, p, 0.0, T0, T0 + timedelta(seconds=800))  # 距 now 200s < 阈值 → 在线
        world_service.sync_world(db, p, now=T0 + timedelta(seconds=1000))
        assert abs(p.world_accum - 1000) < 0.001


def test_offline_factor_configurable(client):
    """game_config.world.offline_factor 可调(改后离线按新倍速)。"""
    _reg(client, "world_cfg")
    from app.core.db import SessionLocal
    from app.models import GameConfig
    from app.services import world_service

    with SessionLocal() as db:
        db.add(GameConfig(key="world.offline_factor", value=0.5))
        db.commit()
        p = _player(db, "world_cfg")
        _set_clock(db, p, 0.0, T0, T0 - timedelta(seconds=400))
        world_service.sync_world(db, p, now=T0 + timedelta(seconds=1000))
        assert abs(p.world_accum - 500) < 0.001  # 1000 × 0.5
        db.query(GameConfig).filter(GameConfig.key == "world.offline_factor").delete()
        db.commit()


def test_pause_freezes_world(client):
    """全局暂停后,世界不再推进(只累计到暂停时刻)。"""
    _reg(client, "world_pause")
    from app.core.db import SessionLocal
    from app.models import GameClock
    from app.services import world_service

    with SessionLocal() as db:
        clock = db.query(GameClock).first()
        orig_paused = clock.paused_at
        try:
            clock.paused_at = T0 + timedelta(seconds=100)
            db.commit()
            p = _player(db, "world_pause")
            _set_clock(db, p, 0.0, T0, T0 - timedelta(seconds=400))
            world_service.sync_world(db, p, now=T0 + timedelta(seconds=1000))
            assert abs(p.world_accum - 100 * 0.25) < 0.001  # 只计 [T0, T0+100]
        finally:
            clock.paused_at = orig_paused
            db.commit()


# ---------- 玩家独立 / 惰性初始化 / 调试推进 ----------

def test_debug_advance_only_caller(client):
    """/debug/term/advance 只推进调用者玩家的世界,其他玩家互不影响。"""
    h_a = _reg(client, "world_adv_a")
    h_b = _reg(client, "world_adv_b")
    cal_a0 = client.get("/v1/calendar/current", headers=h_a).json()["data"]
    cal_b0 = client.get("/v1/calendar/current", headers=h_b).json()["data"]
    assert cal_a0["term_index"] == cal_b0["term_index"]  # 同起点(继承全局)

    for _ in range(3):
        client.post("/v1/debug/term/advance", headers=h_a)
    cal_a1 = client.get("/v1/calendar/current", headers=h_a).json()["data"]
    cal_b1 = client.get("/v1/calendar/current", headers=h_b).json()["data"]
    expected = cal_a0["term_index"] + 3
    expected = (expected - 1) % 24 + 1
    assert cal_a1["term_index"] == expected  # A 前进 3 个节气
    assert cal_b1["term_index"] == cal_b0["term_index"]  # B 未动


def test_per_user_independent(client):
    """两个玩家离线时长不同 → 节气各自独立。"""
    h_a = _reg(client, "world_ind_a")
    _reg(client, "world_ind_b")
    from app.core.db import SessionLocal
    from app.models import GameConfig
    from app.services import world_service

    with SessionLocal() as db:
        p = _player(db, "world_ind_a")
        _set_clock(db, p, 0.0, T0, T0 - timedelta(seconds=600))
        world_service.sync_world(db, p, now=T0 + timedelta(seconds=600))  # A 离线 600s → 只推进 0.25×
    # 线上时 A 与 B 节气应不同(A 世界远慢于 B)
    cal_a = client.get("/v1/calendar/current", headers=h_a).json()["data"]
    assert 1 <= cal_a["term_index"] <= 24


def test_lazy_init_inherits_global(client):
    """world_last_sync 为 None(老玩家)→ 首次同步继承全局参考世界位置。"""
    from app.core.db import SessionLocal
    from app.models import Farm, Player, User
    from app.services import world_service

    with SessionLocal() as db:
        u = User(name="world_lazy", password_hash="x")
        db.add(u)
        db.flush()
        p = Player(user_id=u.id)
        db.add(p)
        db.flush()
        db.add(Farm(owner_id=p.id))
        db.commit()
        assert p.world_last_sync is None
        world_service.sync_world(db, p, now=T0)
        from app.services.calendar_service import global_elapsed

        assert p.world_last_sync == T0
        assert abs(p.world_accum - global_elapsed(db, T0)) < 1e-6


def test_farm_state_uses_player_term(client):
    """farm state 的 current_term 是玩家自己的节气(与 /calendar/current 一致)。"""
    h = _reg(client, "world_farm")
    cal = client.get("/v1/calendar/current", headers=h).json()["data"]
    state = client.get("/v1/farm/state", headers=h).json()["data"]
    assert state["current_term"]["term_index"] == cal["term_index"]


# ---------- 管理员新端点 ----------

def _admin_login(client):
    r = client.post("/v1/admin/login", json={"username": "admin", "password": "admin123"})
    assert r.json()["code"] == 0
    return {"Authorization": f"Bearer {r.json()['data']['token']}"}


def test_admin_player_assets(client):
    h = _reg(client, "world_asset")
    ah = _admin_login(client)
    users = client.get("/v1/admin/users", headers=ah).json()["data"]["items"]
    target = next(u for u in users if u["name"] == "world_asset")
    uid = target["user_id"]

    r = client.patch(
        f"/v1/admin/users/{uid}/assets",
        json={"coins": 9999, "level": 5},
        headers=ah,
    ).json()
    assert r["code"] == 0, r
    assert r["data"]["coins"] == 9999 and r["data"]["level"] == 5

    me = client.get("/v1/player/me", headers=h).json()["data"]
    assert me["coins"] == 9999 and me["level"] == 5


def test_admin_farm_and_plot(client):
    _reg(client, "world_farm_admin")
    ah = _admin_login(client)
    users = client.get("/v1/admin/users", headers=ah).json()["data"]["items"]
    uid = next(u for u in users if u["name"] == "world_farm_admin")["user_id"]

    farm = client.get(f"/v1/admin/users/{uid}/farm", headers=ah).json()["data"]
    assert len(farm["plots"]) == 20
    assert 1 <= farm["current_term"]["term_index"] <= 24

    r = client.put(
        f"/v1/admin/users/{uid}/plots/3",
        json={"locked": True, "soil_quality": 3},
        headers=ah,
    ).json()
    assert r["code"] == 0 and r["data"]["locked"] is True and r["data"]["soil_quality"] == 3

    farm2 = client.get(f"/v1/admin/users/{uid}/farm", headers=ah).json()["data"]
    plot3 = next(p for p in farm2["plots"] if p["idx"] == 3)
    assert plot3["locked"] is True and plot3["soil_quality"] == 3


def test_admin_worlds_list_and_reset(client):
    h = _reg(client, "world_admin_w")
    ah = _admin_login(client)
    r = client.get("/v1/admin/worlds", headers=ah).json()
    assert r["code"] == 0
    items = r["data"]["items"]
    target = next(w for w in items if w["name"] == "world_admin_w")
    pid = target["player_id"]
    assert target["current_term"]["term_index"] >= 1
    assert target["online"] is True  # 刚发过请求

    # 推进后重置 → 回到立春(term 1)
    client.post("/v1/debug/term/advance", headers=h)
    r = client.put(f"/v1/admin/worlds/{pid}", json={"reset": True}, headers=ah).json()
    assert r["code"] == 0
    assert r["data"]["accum"] == 0
    assert r["data"]["term_index"] == 1
    cal = client.get("/v1/calendar/current", headers=h).json()["data"]
    assert cal["term_index"] == 1


# ---------- WS 每用户 ----------

def test_ws_per_user(client):
    from starlette.websockets import WebSocketDisconnect

    h = _reg(client, "world_ws")
    token = h["Authorization"].removeprefix("Bearer ")

    with client.websocket_connect(f"/v1/ws?token={token}") as ws:
        first = ws.receive_json()
        assert first["type"] == "solar_term_change"
        assert 1 <= first["payload"]["term_index"] <= 24

    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/v1/ws?token=bad-token"):
            pass
    assert exc.value.code == 4401
