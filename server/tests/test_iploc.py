"""IP 地理位置解析测试(ip2region 离线库)。"""
from fastapi.testclient import TestClient

from app.core import iploc
from app.main import app


def test_resolve_known_public_ips():
    assert iploc.resolve("223.5.5.5") and "杭州" in iploc.resolve("223.5.5.5")
    assert iploc.resolve("114.114.114.114") and "南京" in iploc.resolve("114.114.114.114")
    assert iploc.resolve("8.8.8.8")  # 国外 IP 也有结果


def test_resolve_private_invalid():
    assert iploc.resolve("127.0.0.1") == "内网"
    assert iploc.resolve("testclient") == "内网"
    assert iploc.resolve("999.999.1.1") is None
    assert iploc.resolve(None) is None
    assert iploc.resolve("") is None
    assert iploc.resolve("  ") is None


def test_register_stores_location_via_xff():
    with TestClient(app) as c:
        r = c.post(
            "/v1/auth/register",
            json={"name": "iploc_user", "password": "pass123456"},
            headers={"X-Forwarded-For": "223.5.5.5"},
        ).json()
        assert r["code"] == 0
        loc = r["data"]["player"]["register_location"]
        assert loc and "杭州" in loc
        # 登录也更新 last_login_location
        r2 = c.post(
            "/v1/auth/login",
            json={"name": "iploc_user", "password": "pass123456"},
            headers={"X-Forwarded-For": "114.114.114.114"},
        ).json()
        assert r2["code"] == 0
        assert "南京" in r2["data"]["player"]["last_login_location"]


def test_admin_users_show_location():
    admin = TestClient(app).post(
        "/v1/admin/login", json={"username": "admin", "password": "admin123"}
    ).json()
    ah = {"Authorization": f"Bearer {admin['data']['token']}"}
    with TestClient(app) as c:
        r = c.get("/v1/admin/users", headers=ah).json()
        assert r["code"] == 0
        target = next(u for u in r["data"]["items"] if u["name"] == "iploc_user")
        assert "register_location" in target and "last_login_location" in target
