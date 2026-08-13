"""IP 地理位置解析(ip2region 离线 xdb,零外部依赖、零网络请求)。

- 数据文件:server/data/ip2region.xdb(v4,约 11MB,已入库,国内 gitee/GitHub 官方源)
- 进程内单例 + 只读内存缓冲,线程安全
- 格式:中国 → "江苏省 南京市 移动";国外 → "United States California Google LLC";内网 → "内网"
- 任何失败都降级为 None(业务侧优雅处理),绝不抛异常
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path

from app.core.ip2region import searcher as _ip2r_searcher
from app.core.ip2region import util as _ip2r_util

_XDB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "ip2region.xdb"

_lock = threading.Lock()
_searcher = None
_load_failed = False
logger = logging.getLogger(__name__)


def _get_searcher():
    global _searcher, _load_failed
    if _searcher is not None or _load_failed:
        return _searcher
    with _lock:
        if _searcher is not None or _load_failed:
            return _searcher
        try:
            if not _XDB_PATH.exists():
                raise FileNotFoundError(_XDB_PATH)
            _searcher = _ip2r_searcher.new_with_buffer(
                _ip2r_util.IPv4, _XDB_PATH.read_bytes()
            )
        except Exception as e:  # noqa: BLE001
            _load_failed = True
            logger.warning("ip2region 库加载失败,IP 地理解析降级为 None: %s", e)
    return _searcher


def resolve(ip: str | None) -> str | None:
    """解析 IP → 人类可读地理位置;解析失败/库缺失返回 None(不抛异常)。"""
    if not ip:
        return None
    ip = ip.strip()
    if ip in ("127.0.0.1", "::1", "localhost", "testclient", "0.0.0.0"):
        return "内网"
    searcher = _get_searcher()
    if searcher is None:
        return None
    try:
        raw = searcher.search(ip) or ""
    except Exception:  # noqa: BLE001
        return None
    if not raw or raw.startswith("Reserved"):
        return "内网"
    parts = [p for p in raw.split("|") if p and p != "0"]
    if not parts:
        return None
    if parts[0] == "中国":
        return " ".join(parts[1:4]) or "中国"
    return " ".join(parts[:4])
