"""通用资源分发接口:任意类型资源(图片/音频/配置…)统一分发。

    GET /v1/assets/{type}/{key}/{name}.{ext}[?w=<目标像素>]
    - type: 资源类型(images/audio/config…),由 data/assets.json 注册表声明
    - key:  资源子目录(如 crops/shuidao、bgm)
    - name: 素材名(如 seed/1/2/3、main、welcome)
    - ext:  扩展名(须在注册表允许列表内)
    - w:    仅图片类型;服务端从预渲染集取最小不小于 w 的分辨率

辅助端点:
    GET /v1/assets/version  :全局资源版本(内容哈希),客户端判断缓存刷新
    GET /v1/assets/manifest :完整资源清单(按类型分组 + URL 模板 + 版本)

兼容:旧 /v1/art 保留为 images 别名(见 art.py)。
"""
import hashlib
import json
import mimetypes
import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse

from app.core.assets_registry import get_type, load_registry, type_names
from app.core.deps import get_current_admin
from app.core.errors import AppError, ok
from app.core.svg_art import PRERENDER_SIZES, ensure_prerendered, ensure_terms_prerendered
from app.ws import manager

router = APIRouter(prefix="/assets", tags=["assets"])

# 版本缓存:文件 mtime 未变则复用,避免每次请求全量哈希
_VERSION_CACHE: dict = {"version": None, "mtime": 0, "updated_at": None}


def _latest_mtime() -> int:
    """所有资源类型目录的最新修改时间(ns);含子目录(捕捉增删资源)。"""
    m = 0
    for tname in type_names():
        t = get_type(tname)
        root = t["root"]
        if not root.exists():
            continue
        m = max(m, root.stat().st_mtime_ns)
        for entry in os.scandir(root):
            m = max(m, entry.stat().st_mtime_ns)
            if entry.is_dir():
                for f in os.scandir(entry.path):
                    m = max(m, f.stat().st_mtime_ns)
    return m


def _file_hash(p: Path) -> str:
    h = hashlib.md5()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _dir_hashes(root: Path) -> dict:
    """逐子目录内容哈希(资源 key → 哈希)。"""
    out = {}
    if not root.exists():
        return out
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


def _compute_versions() -> dict:
    """逐类型/逐资源内容哈希 + 全局版本。"""
    per_type: dict[str, dict] = {}
    global_h = hashlib.md5()
    for tname in type_names():
        t = get_type(tname)
        hashes = _dir_hashes(t["root"])
        per_type[tname] = hashes
        for key in sorted(hashes):
            global_h.update(f"{tname}:{key}".encode("utf-8"))
            global_h.update(hashes[key].encode("ascii"))
    return {
        "version": global_h.hexdigest()[:12],
        "types": per_type,
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


def _media_type(ext: str) -> str:
    mt = mimetypes.guess_type(f"x.{ext}")[0]
    return mt or "application/octet-stream"


def _serve(type_name: str, key: str, name: str, ext: str, w: int) -> FileResponse:
    """通用资源分发:按注册表校验 + 选档 + 返回。"""
    t = get_type(type_name)
    if t is None:
        raise AppError("ASSET_NOT_FOUND", "资源类型不存在", http_status=404, code=28001)
    if ext not in t["ext"]:
        raise AppError("ASSET_NOT_FOUND", "资源扩展名不允许", http_status=404, code=28001)
    # 路径安全:key 可多级(如 crops/shuidao),但拒绝 .. 与绝对路径
    if ".." in key or ".." in name or key.startswith("/") or name.startswith("/"):
        raise AppError("ASSET_NOT_FOUND", "非法资源路径", http_status=404, code=28001)
    d = t["root"] / key
    src = d / f"{name}.{ext}"
    if not src.exists():
        raise AppError("ASSET_NOT_FOUND", "资源不存在", http_status=404, code=28001)

    # 图片类型:预渲染选档(复用 svg_art 的作物/节气预渲染)
    if type_name == "images":
        # animals(表情图)无预渲染,直接返回原图;crops/terms 走预渲染选档
        if key.startswith("animals/"):
            return FileResponse(
                src, media_type="image/png",
                headers={"Cache-Control": "public, max-age=86400"},
            )
        chosen = _pick_size(w)
        if key.startswith("crops/"):
            ensure_prerendered(key.split("/", 1)[1])  # 幂等:缺档自动补渲染
        elif key.startswith("terms/"):
            ensure_terms_prerendered()
        f = d / f"{name}_{chosen}.png"
        if not f.exists():
            raise AppError("ASSET_NOT_FOUND", "资源档缺失", http_status=404, code=28001)
        return FileResponse(
            f, media_type="image/png",
            headers={"Cache-Control": "public, max-age=86400"},
        )

    # 非图片:直接返回
    return FileResponse(
        src, media_type=_media_type(ext),
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/{type_name}/{key:path}/{name}.{ext}")
def asset(
    type_name: str,
    key: str,
    name: str,
    ext: str,
    w: int = Query(default=128, ge=8, le=1024, description="目标宽度像素(仅图片类型)"),
):
    """通用资源接口:GET /v1/assets/{type}/{key}/{name}.{ext}?w="""
    return _serve(type_name, key, name, ext, w)


@router.get("/version")
def assets_version():
    """全局资源版本(内容哈希)。客户端缓存资源时先对比:version 变 → 全量刷新;types[type][key] 变 → 只刷新该资源。"""
    v = _versions()
    return ok(
        {
            "version": v["version"],
            "types": v["types"],
            "sizes": list(PRERENDER_SIZES),
            "updated_at": v["updated_at"],
        }
    )


@router.get("/manifest")
def assets_manifest():
    """完整资源清单:按类型分组 + 版本 + URL 模板。客户端启动时拉一次即可知道所有资源怎么取。"""
    v = _versions()
    types = {}
    for tname in type_names():
        t = get_type(tname)
        types[tname] = {
            "ext": t["ext"],
            "prerender": t["prerender"],
            "url_template": t["url_template"],
            "namespaces": t.get("namespaces", {}),
        }
    return ok(
        {
            "version": v["version"],
            "sizes": list(PRERENDER_SIZES),
            "types": types,
            "updated_at": v["updated_at"],
        }
    )


@router.post("/notify")
def assets_notify(
    asset_type: str = Query(..., description="资源类型(images/audio/config…)"),
    key: str = Query(..., description="资源 key(如 crops/shuidao、bgm)"),
    name: str = Query(..., description="素材名(如 2、main、welcome)"),
    admin: str = Depends(get_current_admin),
):
    """管理端:资源更新后向全服广播 asset_update(客户端按 url 拉取强制更新)。

    触发场景:管理后台替换/新增资源文件后调用,客户端收到后按 url 拉取,
    若 version 与本地缓存不同则强制更新该资源。
    """
    t = get_type(asset_type)
    if t is None:
        raise AppError("ASSET_NOT_FOUND", "资源类型不存在", http_status=404, code=28001)
    url = t["url_template"].format(key=key, name=name, ext=t["ext"][0], w=128)
    v = _versions()
    per_type = v["types"].get(asset_type, {})
    version = per_type.get(key.split("/")[-1], v["version"])
    manager.broadcast_sync(
        {
            "type": "asset_update",
            "payload": {
                "asset_type": asset_type,
                "key": key,
                "name": name,
                "url": url,
                "version": version,
            },
            "ts": int(datetime.now(timezone.utc).timestamp()),
        }
    )
    return ok({"broadcast": True, "url": url, "version": version})
