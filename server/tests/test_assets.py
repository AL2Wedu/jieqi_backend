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
