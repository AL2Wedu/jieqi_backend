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
