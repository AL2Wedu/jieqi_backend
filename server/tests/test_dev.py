"""开发资源清单接口测试:玩家登录 token 门控 + 资源清单。"""
import uuid

from fastapi.testclient import TestClient

from app.main import app

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _reg(client) -> str:
    """注册新玩家,返回登录 token。"""
    name = f"dev_{uuid.uuid4().hex[:8]}"
    r = client.post("/v1/auth/register", json={"name": name, "password": "pass123456"})
    assert r.status_code == 200
    return r.json()["data"]["token"]


def test_dev_assets_requires_login():
    with TestClient(app) as c:
        # 无 token → 401
        r = c.get("/v1/dev/assets")
        assert r.status_code == 401
        # 错误 token → 401
        r = c.get("/v1/dev/assets", headers={"Authorization": "Bearer wrong"})
        assert r.status_code == 401


def test_dev_assets_lists_all_resources():
    with TestClient(app) as c:
        token = _reg(c)
        r = c.get("/v1/dev/assets", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        d = r.json()["data"]
        assert d["count"] > 0
        # 包含 animals(新上传)与 crops/terms
        paths = {f["path"] for f in d["files"]}
        assert any(p.startswith("animals/") for p in paths)
        assert any(p.startswith("crops/") for p in paths)
        assert any(p.startswith("terms/") for p in paths)
        # URL 规则:注册表内 → /v1/assets/;animals 属于 images → /v1/assets/images/
        animal = next(f for f in d["files"] if f["path"].startswith("animals/"))
        assert animal["url"].startswith("/v1/assets/images/animals/")
        crop = next(f for f in d["files"] if f["path"].startswith("crops/"))
        assert crop["url"].startswith("/v1/assets/images/crops/")
        # tree 结构存在
        assert "animals" in d["tree"]


def test_animals_asset_serves():
    """新上传的表情素材:animals/{emotion}/{animal}.png 可经 /v1/assets 取,走预渲染选档。"""
    with TestClient(app) as c:
        # 默认 w=128 → 返回 128 档预渲染图
        r = c.get("/v1/assets/images/animals/happy/dog.png")
        assert r.status_code == 200
        assert r.headers["content-type"] == "image/png"
        assert r.content[:8] == PNG_MAGIC
        # 显式 w=64 → 64 档
        r64 = c.get("/v1/assets/images/animals/happy/dog.png?w=64")
        assert r64.status_code == 200
        assert r64.content[:8] == PNG_MAGIC
        assert c.get("/v1/assets/images/animals/sad/cat.png?w=64").status_code == 200
        assert c.get("/v1/assets/images/animals/angry/dog.png").status_code == 404  # 情绪不存在
