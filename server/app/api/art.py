"""美术素材下发:统一资源接口。

一个端点取全部素材(作物图 / 节气图):

    GET /v1/art/{kind}/{key}/{name}.png?w=<目标像素>
    - kind=crops:key=slug,name∈{seed,1,2,3}(种子图标与阶段图是不同素材,绝不互退)
    - kind=terms:key=节气序号 1-24(与 calendar 一致),name=main
    - w:服务端从预渲染集(32/64/128/256)取 最小不小于 w 的分辨率,没有则取最大;请求零渲染开销

辅助端点:
    GET /v1/art/version  :素材版本(内容哈希),客户端判断是否需要刷新本地缓存
    GET /v1/art/manifest :完整素材清单(作物×4 + 节气×1 + 版本 + URL 模板),客户端一次拉全量

兼容:旧路径 GET /v1/art/terms/{term_index}.png 保留为别名(等价 terms/{index}/main.png)。
"""
import hashlib
import json
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
from scripts.crop_loader import load_crops

router = APIRouter(prefix="/art", tags=["art"])

_ALLOWED_NAMES = {"seed", "1", "2", "3"}
_KINDS = {"crops", "terms"}

# 节气中文名(清单用;term_config.json 为事实源,读不到则回退拼音)
_TERM_NAMES: dict[int, str] = {}
try:
    _tc = Path(__file__).resolve().parent.parent.parent / "data" / "term_config.json"
    _TERM_NAMES = {t["term_index"]: t["name"] for t in json.loads(_tc.read_text(encoding="utf-8"))}
except Exception:
    pass

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


def _versions() -> dict:
    latest = _latest_mtime()
    if _VERSION_CACHE["version"] is None or latest > _VERSION_CACHE["mtime"]:
        _VERSION_CACHE.update(_compute_versions())
        _VERSION_CACHE["mtime"] = latest
    return _VERSION_CACHE


def _pick_size(w: int) -> int:
    return next((sz for sz in sorted(PRERENDER_SIZES) if sz >= w), max(PRERENDER_SIZES))


def _serve_asset(kind: str, key: str, name: str, w: int) -> FileResponse:
    """统一资源分发:校验 + 选档 + 返回(全素材共用一条路径)。"""
    if kind not in _KINDS:
        raise AppError("ART_NOT_FOUND", "资源类型不存在", http_status=404, code=28001)
    chosen = _pick_size(w)
    if kind == "crops":
        if name not in _ALLOWED_NAMES:
            raise AppError("ART_NOT_FOUND", "美术素材不存在", http_status=404, code=28001)
        d = ART_ROOT / key
        # 素材来源:同名 PNG(真实美术)→ 同名 SVG(程序生成);seed 与阶段图绝不互退
        src = d / f"{name}.png"
        if not src.exists():
            src = d / f"{name}.svg"
        if not src.exists():
            raise AppError("ART_NOT_FOUND", "作物美术不存在", http_status=404, code=28001)
        ensure_prerendered(key)  # 幂等:缺档自动补渲染
        f = d / f"{name}_{chosen}.png"
    else:  # terms
        try:
            term_index = int(key)
        except (TypeError, ValueError):
            raise AppError("ART_NOT_FOUND", "节气不存在", http_status=404, code=28001)
        slug = TERM_SLUGS.get(term_index)
        if slug is None or name != "main":
            raise AppError("ART_NOT_FOUND", "节气不存在", http_status=404, code=28001)
        ensure_terms_prerendered()  # 幂等:缺档自动补渲染
        f = TERM_ART_ROOT / slug / f"main_{chosen}.png"
    if not f.exists():
        raise AppError("ART_NOT_FOUND", "美术档缺失", http_status=404, code=28001)
    return FileResponse(
        f,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/{kind}/{key}/{name}.png")
def asset(
    kind: str,
    key: str,
    name: str,
    w: int = Query(default=128, ge=8, le=1024, description="目标宽度像素,服务端选最近预渲染档"),
):
    """统一资源接口:GET /v1/art/{kind}/{key}/{name}.png?w=

    kind=crops → 作物素材(seed/1/2/3);kind=terms → 24 节气图(main)。
    """
    return _serve_asset(kind, key, name, w)


@router.get("/terms/{term_index}.png")
def term_art_alias(
    term_index: int,
    w: int = Query(default=128, ge=8, le=1024, description="目标宽度像素,服务端选最近预渲染档"),
):
    """兼容别名:旧路径 GET /v1/art/terms/{term_index}.png(等价 terms/{index}/main.png)。"""
    return _serve_asset("terms", str(term_index), "main", w)


@router.get("/version")
def art_version():
    """素材版本(内容哈希)。客户端缓存素材时先对比:version 变 → 全量刷新;crops[slug] 变 → 只刷新该作物。"""
    v = _versions()
    return ok(
        {
            "version": v["version"],
            "crops": v["crops"],
            "terms": v["terms"],  # 节气图版本(前端缓存刷新用)
            "sizes": list(PRERENDER_SIZES),
            "updated_at": v["updated_at"],
        }
    )


@router.get("/manifest")
def art_manifest():
    """完整素材清单:全部作物(4 素材)+ 24 节气(1 素材)+ 版本 + URL 模板。

    客户端启动时拉一次,即可知道所有资源的调用路径与当前版本。
    """
    v = _versions()
    crops = []
    for c in sorted(load_crops(), key=lambda x: int(x.get("sort_order") or 999)):
        slug = c.get("slug")
        if slug and (ART_ROOT / slug).is_dir():
            crops.append(
                {
                    "slug": slug,
                    "name": c.get("name") or slug,
                    "assets": sorted(_ALLOWED_NAMES),
                }
            )
    terms = [
        {"index": i, "slug": TERM_SLUGS[i], "name": _TERM_NAMES.get(i, TERM_SLUGS[i])}
        for i in sorted(TERM_SLUGS)
    ]
    return ok(
        {
            "version": v["version"],
            "sizes": list(PRERENDER_SIZES),
            "crops": crops,
            "terms": terms,
            "url_templates": {
                "crop": "/v1/art/crops/{slug}/{name}.png?w={w}",
                "term": "/v1/art/terms/{index}/main.png?w={w}",
            },
            "updated_at": v["updated_at"],
        }
    )
