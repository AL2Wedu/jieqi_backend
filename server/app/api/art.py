"""美术素材下发:按客户端请求的分辨率(w)下发预渲染 PNG。

协议:GET /v1/art/crops/{slug}/{seed|1|2|3}.png?w=<目标像素>
- 服务端从预渲染集(32/64/128/256)选取 最小不小于 w 的分辨率,没有则取最大
- 全部素材启动/创建时预渲染,请求零渲染开销
- GET /v1/art/version:素材版本(内容哈希),客户端据此判断是否需要更新本地缓存
"""
import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse

from app.core.errors import AppError, ok
from app.core.svg_art import (
    ART_ROOT,
    PRERENDER_SIZES,
    TERM_ART_ROOT,
    TERM_SLUGS,
    ensure_prerendered,
    ensure_terms_prerendered,
)

router = APIRouter(prefix="/art", tags=["art"])

_ALLOWED_NAMES = {"seed", "1", "2", "3"}

# 版本缓存:文件 mtime 未变则复用,避免每次请求全量哈希
_VERSION_CACHE: dict = {"version": None, "mtime": 0, "updated_at": None}


def _latest_mtime() -> int:
    """素材目录最新修改时间(ns);含根目录与子目录条目(捕捉增删作物/节气图)。"""

    def _scan(root: Path) -> int:
        m = root.stat().st_mtime_ns
        for entry in os.scandir(root):
            m = max(m, entry.stat().st_mtime_ns)
            if entry.is_dir():
                for f in os.scandir(entry.path):
                    m = max(m, f.stat().st_mtime_ns)
        return m

    return max(_scan(ART_ROOT), _scan(TERM_ART_ROOT))


def _file_hash(p: Path) -> str:
    h = hashlib.md5()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _compute_versions() -> dict:
    """逐作物/逐节气内容哈希 + 全局版本。"""

    def _dir_hashes(root: Path) -> dict:
        out = {}
        for entry in sorted(root.iterdir()):
            if not entry.is_dir():
                continue
            h = hashlib.md5()
            for f in sorted(entry.glob("*")):
                if f.is_file():
                    h.update(f.name.encode("utf-8"))
                    h.update(_file_hash(f).encode("ascii"))
            out[entry.name] = h.hexdigest()[:12]
        return out

    crops = _dir_hashes(ART_ROOT)
    terms = _dir_hashes(TERM_ART_ROOT)
    global_h = hashlib.md5()
    for slug in sorted(crops):
        global_h.update(slug.encode("utf-8"))
        global_h.update(crops[slug].encode("ascii"))
    for slug in sorted(terms):
        global_h.update(("term:" + slug).encode("utf-8"))
        global_h.update(terms[slug].encode("ascii"))
    return {
        "version": global_h.hexdigest()[:12],
        "crops": crops,
        "terms": terms,
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


@router.get("/version")
def art_version():
    """素材版本(内容哈希)。客户端缓存素材时先对比:version 变 → 全量刷新;crops[slug] 变 → 只刷新该作物。"""
    latest = _latest_mtime()
    if _VERSION_CACHE["version"] is None or latest > _VERSION_CACHE["mtime"]:
        _VERSION_CACHE.update(_compute_versions())
        _VERSION_CACHE["mtime"] = latest
    return ok(
        {
            "version": _VERSION_CACHE["version"],
            "crops": _VERSION_CACHE["crops"],
            "terms": _VERSION_CACHE["terms"],  # 节气图版本(前端缓存刷新用)
            "sizes": list(PRERENDER_SIZES),
            "updated_at": _VERSION_CACHE["updated_at"],
        }
    )


@router.get("/crops/{slug}/{name}.png")
def crop_art(
    slug: str,
    name: str,
    w: int = Query(default=128, ge=8, le=1024, description="目标宽度像素,服务端选最近预渲染档"),
):
    if name not in _ALLOWED_NAMES:
        raise AppError("ART_NOT_FOUND", "美术素材不存在", http_status=404, code=28001)
    d = ART_ROOT / slug
    # 素材来源:同名 PNG(真实美术)→ 同名 SVG(程序生成)
    # 注意:seed 与阶段图(1/2/3)是不同素材,绝不互相回退
    src = d / f"{name}.png"
    if not src.exists():
        src = d / f"{name}.svg"
    if not src.exists():
        raise AppError("ART_NOT_FOUND", "作物美术不存在", http_status=404, code=28001)
    ensure_prerendered(slug)  # 幂等:缺档自动补渲染
    chosen = next((sz for sz in sorted(PRERENDER_SIZES) if sz >= w), max(PRERENDER_SIZES))
    f = d / f"{name}_{chosen}.png"
    if not f.exists():
        raise AppError("ART_NOT_FOUND", "美术档缺失", http_status=404, code=28001)
    return FileResponse(
        f,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/terms/{term_index}.png")
def term_art(
    term_index: int,
    w: int = Query(default=128, ge=8, le=1024, description="目标宽度像素,服务端选最近预渲染档"),
):
    """24 节气图:term_index 1-24(与 calendar 返回一致),同一预渲染管线。"""
    slug = TERM_SLUGS.get(term_index)
    if slug is None:
        raise AppError("ART_NOT_FOUND", "节气不存在", http_status=404, code=28001)
    ensure_terms_prerendered()  # 幂等:缺档自动补渲染
    chosen = next((sz for sz in sorted(PRERENDER_SIZES) if sz >= w), max(PRERENDER_SIZES))
    f = TERM_ART_ROOT / slug / f"main_{chosen}.png"
    if not f.exists():
        raise AppError("ART_NOT_FOUND", "节气图缺失", http_status=404, code=28001)
    return FileResponse(
        f,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )
