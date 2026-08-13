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


def test_art_version():
    from app.core.svg_art import ART_ROOT

    with TestClient(app) as c:
        # 版本信息完整
        v1 = c.get("/v1/art/version").json()["data"]
        assert len(v1["version"]) == 12
        assert "rice" in v1["crops"] and len(v1["crops"]["rice"]) == 12
        assert v1["sizes"] == [32, 64, 128, 256]
        # 确定性:两次调用一致(缓存生效)
        v2 = c.get("/v1/art/version").json()["data"]
        assert v2["version"] == v1["version"] and v2["crops"] == v1["crops"]
        # 内容变更 → 版本变化(临时作物目录,测完清理)
        tmp = ART_ROOT / "version_test_crop"
        tmp.mkdir(exist_ok=True)
        try:
            (tmp / "1.svg").write_text("<svg/>", encoding="utf-8")
            v3 = c.get("/v1/art/version").json()["data"]
            assert v3["version"] != v1["version"]
            assert len(v3["crops"]["version_test_crop"]) == 12
            # 再次修改内容 → 该作物版本变化,其他作物不变
            (tmp / "1.svg").write_text("<svg>changed</svg>", encoding="utf-8")
            v4 = c.get("/v1/art/version").json()["data"]
            assert v4["crops"]["version_test_crop"] != v3["crops"]["version_test_crop"]
            assert v4["crops"]["rice"] == v1["crops"]["rice"]
            assert v4["version"] != v3["version"]
        finally:
            import shutil

            shutil.rmtree(tmp, ignore_errors=True)
        # 删除作物 → 版本回落(缓存能感知目录删除)
        v5 = c.get("/v1/art/version").json()["data"]
        assert "version_test_crop" not in v5["crops"]
        assert v5["version"] == v1["version"]
