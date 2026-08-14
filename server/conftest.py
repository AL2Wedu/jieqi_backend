"""pytest 全局配置:统一测试数据库与管理员凭据(在 app 导入前生效)。"""
import os

os.environ["DATABASE_URL"] = "sqlite:///./test.db"
os.environ["ADMIN_PASSWORD"] = "admin123"
os.environ["ADMIN_ENABLED"] = "true"

# 每个测试进程启动前清空旧库(引擎尚未连接,可安全删除)
if os.path.exists("test.db"):
    os.remove("test.db")


# ---------- 美术素材隔离:测试写文件全部进临时副本,不污染真实素材 ----------
import shutil  # noqa: E402
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _isolate_art():
    from app.core import svg_art

    real = svg_art.ART_ROOT
    tmp = Path(tempfile.mkdtemp(prefix="hermes_test_art_"))
    shutil.copytree(real, tmp, dirs_exist_ok=True)

    import app.api.art as art_mod

    svg_art.ART_ROOT = tmp
    art_mod.ART_ROOT = tmp
    art_mod._VERSION_CACHE.update({"version": None, "mtime": 0, "updated_at": None})  # 重置缓存键(clear 会删键导致 KeyError)
    yield
    svg_art.ART_ROOT = real
    art_mod.ART_ROOT = real
    art_mod._VERSION_CACHE.update({"version": None, "mtime": 0, "updated_at": None})
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture(scope="session", autouse=True)
def _isolate_crops_data():
    """植物设定文件隔离:测试内管理后台增改作物写临时副本,不污染真实 data/crops/。"""
    from scripts import crop_loader

    real = crop_loader.CROPS_DIR
    tmp = Path(tempfile.mkdtemp(prefix="hermes_test_crops_"))
    shutil.copytree(real, tmp, dirs_exist_ok=True)
    crop_loader.CROPS_DIR = tmp
    yield
    shutil.rmtree(tmp, ignore_errors=True)
