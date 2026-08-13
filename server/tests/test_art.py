"""美术素材下发端点测试:分辨率选择 / 内容类型 / 404。"""
from fastapi.testclient import TestClient

from app.main import app

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def test_art_endpoint():
    with TestClient(app) as c:
        # 成熟图 w=128 → 200 + PNG
        r = c.get("/v1/art/crops/rice/3.png?w=128")
        assert r.status_code == 200
        assert r.headers["content-type"] == "image/png"
        assert r.content[:8] == PNG_MAGIC
        assert len(r.content) > 100

        # 分辨率选择:不同 w 下发不同档(文件大小应不同)
        small = c.get("/v1/art/crops/rice/3.png?w=32")
        large = c.get("/v1/art/crops/rice/3.png?w=256")
        assert small.status_code == 200 and large.status_code == 200
        assert len(large.content) > len(small.content)

        # w 超出档位 → 取最大档,仍 200
        assert c.get("/v1/art/crops/rice/3.png?w=1024").status_code == 200

        # 全部阶段可用
        for name in ("seed", "1", "2", "3"):
            assert c.get(f"/v1/art/crops/rice/{name}.png?w=64").status_code == 200

        # 未知 slug / 未知素材 → 404
        assert c.get("/v1/art/crops/nope/3.png?w=128").status_code == 404
        assert c.get("/v1/art/crops/rice/9.png?w=128").status_code == 404
        assert c.get("/v1/art/crops/rice/seed.png?w=5").status_code == 422  # 参数越界
