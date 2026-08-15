"""通用资源注册表:声明式定义每种资源类型(目录/扩展名/预渲染/URL 模板/命名空间)。

增改资源 = 放文件到对应 root + 改 data/assets.json,零代码。
"""
import json
from pathlib import Path

_REG = Path(__file__).resolve().parent.parent.parent / "data" / "assets.json"
_CACHE: dict | None = None


def load_registry() -> dict:
    """加载资源注册表(进程内缓存)。"""
    global _CACHE
    if _CACHE is None:
        _CACHE = json.loads(_REG.read_text(encoding="utf-8"))
    return _CACHE


def get_type(type_name: str) -> dict | None:
    """按类型名取配置;不存在返回 None。root 已解析为绝对 Path。"""
    reg = load_registry()
    t = reg.get(type_name)
    if t is None:
        return None
    # 解析 root 为绝对路径(相对 server/ 目录)
    base = Path(__file__).resolve().parent.parent.parent  # server/
    t = dict(t)
    t["root"] = (base / t["root"]).resolve()
    return t


def type_names() -> list[str]:
    return list(load_registry().keys())
