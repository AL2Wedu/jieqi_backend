"""开发辅助接口(仅开发环境,DEV_TOKEN 门控)。

    GET /v1/dev/assets  :完整资源清单(遍历 app/static/assets 目录树,返回全部文件
                         及其可访问 URL),开发/联调用。

安全:必须带 `Authorization: Bearer <DEV_TOKEN>`;token 配在 .env 的 DEV_TOKEN,
为空时接口整体禁用(403 DEV_DISABLED)。上线应保持为空。
"""
from pathlib import Path

from fastapi import APIRouter, Depends, Header

from app.core.config import settings
from app.core.errors import AppError, ok

router = APIRouter(prefix="/dev", tags=["dev"])

STATIC_ASSETS = Path(__file__).resolve().parent.parent / "static" / "assets"


def _require_dev_token(authorization: str | None = Header(default=None)) -> str:
    """开发接口守卫:校验 Bearer <DEV_TOKEN>;token 未配置则整体禁用。"""
    if not settings.dev_token:
        raise AppError("DEV_DISABLED", "开发接口未启用(DEV_TOKEN 未配置)", http_status=403, code=90001)
    if not authorization or not authorization.startswith("Bearer "):
        raise AppError("UNAUTHORIZED", "缺少开发 token", http_status=401, code=10002)
    token = authorization.removeprefix("Bearer ").strip()
    if token != settings.dev_token:
        raise AppError("UNAUTHORIZED", "开发 token 无效", http_status=401, code=10002)
    return token


@router.get("/assets")
def dev_assets(_: str = Depends(_require_dev_token)):
    """完整资源清单:遍历 assets 目录树,列出所有文件及访问 URL。

    URL 规则:注册表中已有类型 → /v1/assets/{type}/{rel};未注册目录(如 animals)→ /static/assets/{rel}。
    """
    if not STATIC_ASSETS.exists():
        raise AppError("ASSET_NOT_FOUND", "资源目录不存在", http_status=404, code=28001)

    from app.core.assets_registry import load_registry

    reg = load_registry()
    tree: dict[str, dict] = {}
    files: list[dict] = []

    def walk(d: Path, prefix: str = "") -> None:
        for entry in sorted(d.iterdir()):
            if entry.is_dir():
                walk(entry, f"{prefix}{entry.name}/")
            else:
                rel = f"{prefix}{entry.name}"
                rel_static = f"assets/{rel}"
                top = rel.split("/")[0]
                # 注册表类型名(images 的素材实际在 crops/terms/animals 子目录)
                if top in reg:
                    url = f"/v1/assets/{rel}"
                elif top in ("crops", "terms", "animals"):
                    url = f"/v1/assets/images/{rel}"
                else:
                    url = f"/static/{rel_static}"
                files.append(
                    {
                        "path": rel,
                        "url": url,
                        "size": entry.stat().st_size,
                        "ext": entry.suffix.lstrip("."),
                    }
                )
                parts = rel.split("/")
                node = tree
                for p in parts[:-1]:
                    node = node.setdefault(p, {})
                node.setdefault(parts[-1], None)

    walk(STATIC_ASSETS)
    return ok(
        {
            "root": "app/static/assets",
            "count": len(files),
            "tree": tree,
            "files": files,
            "registry": {t: reg[t].get("url_template", "") for t in reg},
        }
    )