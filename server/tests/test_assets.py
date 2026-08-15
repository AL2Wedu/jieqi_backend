"""通用资源分发系统测试:注册表 / 通用接口 / manifest / version / asset_update 事件。"""
from fastapi.testclient import TestClient

from app.main import app

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


# ---------- Task 1: 资源注册表 ----------

def test_registry_loads_types():
    from app.core.assets_registry import load_registry

    reg = load_registry()
    assert "images" in reg and "audio" in reg and "config" in reg
    assert reg["images"]["prerender"] == [32, 64, 128, 256]
    assert "crops" in reg["images"]["namespaces"]
    assert "terms" in reg["images"]["namespaces"]
    assert reg["images"]["namespaces"]["crops"]["names"] == ["seed", "1", "2", "3"]


def test_registry_type_lookup():
    from app.core.assets_registry import get_type

    img = get_type("images")
    assert img["root"].name == "assets"
    assert get_type("nope") is None


# ---------- Task 2: 通用资源接口 ----------

def test_assets_image_serves():
    with TestClient(app) as c:
        r = c.get("/v1/assets/images/crops/shuidao/2.png?w=128")
        assert r.status_code == 200
        assert r.headers["content-type"] == "image/png"
        assert r.content[:8] == PNG_MAGIC


def test_assets_audio_serves():
    with TestClient(app) as c:
        r = c.get("/v1/assets/audio/bgm/main.ogg")
        assert r.status_code == 200
        assert r.headers["content-type"] == "audio/ogg"
        assert r.content[:4] == b"OggS"


def test_assets_config_serves():
    with TestClient(app) as c:
        r = c.get("/v1/assets/config/terms/welcome.json")
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/json"
        assert b"welcome" in r.content


def test_assets_unknown_type_404():
    with TestClient(app) as c:
        r = c.get("/v1/assets/video/x/y.mp4")
        assert r.status_code == 404
        assert r.json()["code"] == 28001


def test_assets_missing_file_404():
    with TestClient(app) as c:
        assert c.get("/v1/assets/audio/bgm/nope.ogg").status_code == 404
        assert c.get("/v1/assets/images/crops/nope/2.png?w=64").status_code == 404
        assert c.get("/v1/assets/config/terms/nope.json").status_code == 404


# ---------- Task 3: /v1/art 保留为 images 别名(向后兼容) ----------

def test_art_alias_still_works():
    """旧 /v1/art 端点仍可用(向后兼容),且与 /v1/assets/images 返回同一张图。"""
    with TestClient(app) as c:
        # 旧路径仍 200
        old = c.get("/v1/art/crops/shuidao/2.png?w=128")
        assert old.status_code == 200
        assert old.headers["content-type"] == "image/png"
        # 新路径返回同一张图(内容一致)
        new = c.get("/v1/assets/images/crops/shuidao/2.png?w=128")
        assert new.status_code == 200
        assert old.content == new.content
        # 旧节气别名仍可用
        assert c.get("/v1/art/terms/1.png?w=64").status_code == 200


# ---------- Task 4: 泛化 manifest/version ----------

def test_assets_manifest_lists_types():
    with TestClient(app) as c:
        r = c.get("/v1/assets/manifest").json()
        assert r["code"] == 0
        d = r["data"]
        assert "images" in d["types"] and "audio" in d["types"] and "config" in d["types"]
        assert d["types"]["images"]["prerender"] == [32, 64, 128, 256]
        assert d["types"]["audio"]["url_template"] == "/v1/assets/audio/{key}/{name}.{ext}"
        assert d["version"] and d["sizes"] == [32, 64, 128, 256]


def test_assets_version_covers_types():
    with TestClient(app) as c:
        r = c.get("/v1/assets/version").json()
        assert r["code"] == 0
        d = r["data"]
        assert "images" in d["types"] and "audio" in d["types"] and "config" in d["types"]
        assert len(d["version"]) == 12
        # 确定性:两次一致
        r2 = c.get("/v1/assets/version").json()
        assert r2["data"]["version"] == d["version"]
        # 音频/配置资源有哈希
        assert "bgm" in d["types"]["audio"]
        assert "terms" in d["types"]["config"]


# ---------- Task 5: 通用 WS 事件 asset_update ----------

def _admin_token(client) -> str:
    r = client.post("/v1/admin/login", json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200
    return r.json()["data"]["token"]


def test_assets_notify_requires_admin():
    with TestClient(app) as c:
        # 无 admin token → 401
        r = c.post("/v1/assets/notify?asset_type=audio&key=bgm&name=main")
        assert r.status_code == 401


def test_assets_notify_broadcasts_asset_update():
    with TestClient(app) as c:
        tok = _admin_token(c)
        # 注册一个玩家并连 WS
        reg = c.post("/v1/auth/register", json={"name": "asset_ws", "password": "pass123"})
        player_token = reg.json()["data"]["token"]
        with c.websocket_connect(f"/v1/ws?token={player_token}") as ws:
            first = ws.receive_json()  # 首帧 solar_term_change
            assert first["type"] == "solar_term_change"
            # 管理端触发资源更新广播
            r = c.post(
                "/v1/assets/notify?asset_type=audio&key=bgm&name=main",
                headers={"Authorization": f"Bearer {tok}"},
            )
            assert r.status_code == 200
            assert r.json()["data"]["broadcast"] is True
            # 玩家 WS 收到 asset_update
            msg = ws.receive_json()
            assert msg["type"] == "asset_update"
            assert msg["payload"]["asset_type"] == "audio"
            assert msg["payload"]["key"] == "bgm"
            assert "url" in msg["payload"] and "version" in msg["payload"]


def test_assets_notify_unknown_type_404():
    with TestClient(app) as c:
        tok = _admin_token(c)
        r = c.post(
            "/v1/assets/notify?asset_type=video&key=x&name=y",
            headers={"Authorization": f"Bearer {tok}"},
        )
        assert r.status_code == 404
        assert r.json()["code"] == 28001
