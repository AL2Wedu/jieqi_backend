"""账号体系四件套测试:数字 ID / 注销留档冻结 / 改名限速 / 兑换码。"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c

PNG = b"x"  # 占位(本文件不涉及图片)


def _user_id_of(client, ah, player_id):
    """按 player_id 找 user_id(admin 端点用 user_id,注册响应只有 player_id)。"""
    from app.core.db import SessionLocal
    from app.models import Player

    with SessionLocal() as db:
        row = db.query(Player.user_id).filter(Player.id == uuid.UUID(player_id)).first()
    return str(row[0]) if row else None


def _reg(client, name, password="pass123456"):
    r = client.post("/v1/auth/register", json={"name": name, "password": password}).json()
    assert r["code"] == 0, r
    return {"Authorization": f"Bearer {r['data']['token']}"}, r["data"]


def _admin(client):
    r = client.post("/v1/admin/login", json={"username": "admin", "password": "admin123"}).json()
    assert r["code"] == 0, r
    return {"Authorization": f"Bearer {r['data']['token']}"}


def _set_cfg(client, ah, key, value):
    r = client.put(f"/v1/admin/config/{key}", json={"value": value}, headers=ah).json()
    assert r["code"] == 0, r


# ---------- ① 数字 ID ----------


def test_uid_num_generation_and_query(client):
    """注册带 7 位纯数字 ID;可按数字 ID 查任意玩家公开资料。"""
    hA, dA = _reg(client, "uid_a")
    hB, dB = _reg(client, "uid_b")
    uidA = dA["player"]["uid_num"]
    assert isinstance(uidA, int) and 1_000_000 <= uidA <= 99_999_999
    # 自己/他人资料卡都带 uid_num
    assert client.get("/v1/player/me", headers=hA).json()["data"]["uid_num"] == uidA
    r = client.get(f"/v1/player/uid/{uidA}", headers=hB).json()
    assert r["code"] == 0
    assert r["data"]["player_id"] == dA["player"]["player_id"]
    assert r["data"]["uid_num"] == uidA and r["data"]["name"] == "uid_a"
    # 社交公开资料也带 uid_num(一致性)
    r = client.get(f"/v1/social/players/{dA['player']['player_id']}", headers=hB).json()
    assert r["data"]["uid_num"] == uidA
    # 不存在 → 20013
    assert client.get("/v1/player/uid/99999999", headers=hB).json()["code"] == 20013


# ---------- ② 注销(留档冻结) ----------


def test_deactivate_flow(client):
    """注销:需密码+confirm;注销后登录/存量 token 被拒,数据保留,管理端可恢复。"""
    h, d = _reg(client, "deact_u", password="pass999999")
    pid = d["player"]["player_id"]
    # 密码错 → 20003;缺 confirm → 10001
    r = client.post(
        "/v1/auth/deactivate",
        json={"password": "wrongpass", "confirm": True},
        headers=h,
    ).json()
    assert r["code"] == 20003
    r = client.post(
        "/v1/auth/deactivate",
        json={"password": "pass999999", "confirm": False},
        headers=h,
    ).json()
    assert r["code"] == 10001
    # 正确注销
    r = client.post(
        "/v1/auth/deactivate",
        json={"password": "pass999999", "confirm": True},
        headers=h,
    ).json()
    assert r["code"] == 0 and r["data"]["status"] == 2
    # 登录被拒 20007;存量 token 被拒 20007
    assert (
        client.post(
            "/v1/auth/login", json={"name": "deact_u", "password": "pass999999"}
        ).json()["code"]
        == 20007
    )
    assert client.get("/v1/player/me", headers=h).json()["code"] == 20007
    # 数据留档:用户仍在管理列表且状态=2
    ah = _admin(client)
    uid = _user_id_of(client, ah, pid)
    users = client.get("/v1/admin/users?page_size=50", headers=ah).json()["data"]["items"]
    me = next(u for u in users if u["user_id"] == uid)
    assert me["status"] == 2
    # 世界冻结:注销后世界时间不再推进
    from app.core.db import SessionLocal
    from app.core.utils import ensure_aware
    from app.models import Player

    with SessionLocal() as db:
        p = db.query(Player).filter(Player.id == uuid.UUID(pid)).first()
        accum_before = p.world_accum
        p.world_last_sync = datetime.now(timezone.utc) - timedelta(minutes=5)
        db.commit()
    with SessionLocal() as db:
        from app.services.world_service import sync_world

        p = db.query(Player).filter(Player.id == uuid.UUID(pid)).first()
        sync_world(db, p)
        db.commit()
        assert p.world_accum == accum_before  # 冻结:不推进
    # 管理端恢复 → 登录恢复
    r = client.patch(f"/v1/admin/users/{uid}/status", json={"status": 1}, headers=ah).json()
    assert r["code"] == 0
    assert (
        client.post(
            "/v1/auth/login", json={"name": "deact_u", "password": "pass999999"}
        ).json()["code"]
        == 0
    )
    # 非法状态值 → 10001
    assert (
        client.patch(f"/v1/admin/users/{uid}/status", json={"status": 9}, headers=ah).json()["code"]
        == 10001
    )


# ---------- ③ 改名(限速) ----------


def test_rename_flow(client):
    """改名:成功同步双表;限速 20008;管理端无限速。"""
    h, d = _reg(client, "rn_old")
    ah = _admin(client)
    _set_cfg(client, ah, "rename.cooldown_seconds", 3600)  # 1 小时限速窗
    # 成功改名
    r = client.post("/v1/player/rename", json={"new_name": "rn_new"}, headers=h).json()
    assert r["code"] == 0 and r["data"]["name"] == "rn_new"
    assert client.get("/v1/player/me", headers=h).json()["data"]["name"] == "rn_new"
    # 改名后登录用新名字
    r = client.post("/v1/auth/login", json={"name": "rn_new", "password": "pass123456"}).json()
    assert r["code"] == 0
    # 限速窗内再改 → 20008
    r = client.post("/v1/player/rename", json={"new_name": "rn_new2"}, headers=h).json()
    assert r["code"] == 20008
    # 同名不改 → 10001
    r = client.post("/v1/player/rename", json={"new_name": "rn_new"}, headers=h).json()
    assert r["code"] == 10001
    # 管理端无限速改名
    pid = d["player"]["player_id"]
    uid = _user_id_of(client, ah, pid)
    r = client.put(
        f"/v1/admin/users/{uid}/rename", json={"new_name": "rn_admin"}, headers=ah
    ).json()
    assert r["code"] == 0 and r["data"]["name"] == "rn_admin"
    assert client.get("/v1/player/me", headers=h).json()["data"]["name"] == "rn_admin"
    # 还原配置
    _set_cfg(client, ah, "rename.cooldown_seconds", 604800)


# ---------- ④ 兑换码 ----------


def _redeem_code_helpers(client):
    h, d = _reg(client, "rc_user")
    ah = _admin(client)
    _set_cfg(client, ah, "redeem.cooldown_seconds", 0)  # 测试不限速
    return h, d, ah


def test_redeem_flow(client):
    """兑换码:发布→兑换入账(账本)→重复 20011→无效 20010→停用→次数用尽。"""
    h, d, ah = _redeem_code_helpers(client)
    pid = d["player"]["player_id"]
    # 发布单个指定码
    r = client.post(
        "/v1/admin/redeem/codes",
        json={
            "code": "TEST123456",
            "reward": {"coins": 100, "exp": 50},
            "batch_name": "测试批",
            "max_uses": 2,
            "per_player_limit": 1,
        },
        headers=ah,
    ).json()
    assert r["code"] == 0
    assert r["data"]["codes"] == ["TEST123456"]  # 明文仅此一次
    # 玩家兑换 → 金币 +100(账本),经验 +50
    coins0 = client.get("/v1/player/me", headers=h).json()["data"]["coins"]
    r = client.post("/v1/redeem", json={"code": "TEST123456"}, headers=h).json()
    assert r["code"] == 0, r
    assert r["data"]["reward"]["coins"] == 100
    assert client.get("/v1/player/me", headers=h).json()["data"]["coins"] == coins0 + 100
    # 账本留痕
    from app.core.db import SessionLocal
    from app.models import CoinTransaction

    with SessionLocal() as db:
        tx = (
            db.query(CoinTransaction)
            .filter(CoinTransaction.player_id == uuid.UUID(pid))
            .order_by(CoinTransaction.created_at.desc())
            .first()
        )
        assert tx.reason.startswith("redeem:") and tx.amount == 100
    # 重复兑换(每人限 1)→ 20011
    assert client.post("/v1/redeem", json={"code": "TEST123456"}, headers=h).json()["code"] == 20011
    # 无效码 → 20010(统一,不泄露存在性)
    assert client.post("/v1/redeem", json={"code": "NOEXIST123"}, headers=h).json()["code"] == 20010
    # 管理端列表:用量 1
    r = client.get("/v1/admin/redeem/codes", headers=ah).json()
    assert r["code"] == 0 and r["data"]["total"] >= 1
    item = next(i for i in r["data"]["items"] if i["code_hint"] == "TEST12")
    assert item["used_count"] == 1 and item["remaining"] == 1
    # 停用 → 再兑换 20010
    r = client.put(
        f"/v1/admin/redeem/codes/{item['code_id']}", json={"active": False}, headers=ah
    ).json()
    assert r["code"] == 0 and r["data"]["active"] is False
    assert client.post("/v1/redeem", json={"code": "TEST123456"}, headers=h).json()["code"] == 20010
    # 恢复启用 + 第二个玩家 → 次数用尽 20012
    client.put(
        f"/v1/admin/redeem/codes/{item['code_id']}", json={"active": True}, headers=ah
    )
    h2, _ = _reg(client, "rc_user2")
    r = client.post("/v1/redeem", json={"code": "TEST123456"}, headers=h2).json()
    assert r["code"] == 0
    h3, _ = _reg(client, "rc_user3")
    assert client.post("/v1/redeem", json={"code": "TEST123456"}, headers=h3).json()["code"] == 20012
    # 还原配置
    _set_cfg(client, ah, "redeem.cooldown_seconds", 60)


def test_redeem_rate_limit(client):
    """兑换尝试限速:窗口内(成功失败都算)再试 → 20009。"""
    h, d, ah = _redeem_code_helpers(client)
    _set_cfg(client, ah, "redeem.cooldown_seconds", 3600)
    # 第一次尝试(无效码)→ 20010,但已触发限速
    assert client.post("/v1/redeem", json={"code": "AAAAAA1111"}, headers=h).json()["code"] == 20010
    # 窗口内再试(任何码)→ 20009
    r = client.post("/v1/redeem", json={"code": "BBBBBB2222"}, headers=h).json()
    assert r["code"] == 20009
    _set_cfg(client, ah, "redeem.cooldown_seconds", 60)


def test_redeem_batch_and_custom_guard(client):
    """批量生成随机码;批量+指定码 → 10001;重复码 → 20015。"""
    h, d, ah = _redeem_code_helpers(client)
    # 批量 3 个随机码
    r = client.post(
        "/v1/admin/redeem/codes",
        json={"reward": {"coins": 10}, "count": 3},
        headers=ah,
    ).json()
    assert r["code"] == 0 and len(r["data"]["codes"]) == 3
    assert all(len(c) == 12 and c.isalnum() for c in r["data"]["codes"])
    # 批量+指定码 → 10001
    r = client.post(
        "/v1/admin/redeem/codes",
        json={"reward": {"coins": 10}, "count": 3, "code": "CUSTOM12345"},
        headers=ah,
    ).json()
    assert r["code"] == 10001
    # 重复发布相同码 → 20015
    r = client.post(
        "/v1/admin/redeem/codes",
        json={"reward": {"coins": 10}, "code": "CUSTOM12345"},
        headers=ah,
    ).json()
    assert r["code"] == 0
    r = client.post(
        "/v1/admin/redeem/codes",
        json={"reward": {"coins": 10}, "code": "CUSTOM12345"},
        headers=ah,
    ).json()
    assert r["code"] == 20015
    # 未登录玩家不能兑换
    assert client.post("/v1/redeem", json={"code": "CUSTOM12345"}).status_code == 401
