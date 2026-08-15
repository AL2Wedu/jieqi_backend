"""资源清单接口(玩家登录 token 门控)。

    GET /v1/dev/assets  :完整资源清单(遍历 app/static/assets 目录树,返回全部文件
                         及其可访问 URL),开发联调与用户客户端共用。

认证:必须带 `Authorization: Bearer <玩家登录 JWT>`(与其余玩家端接口一致,
经 get_current_player 校验;无效/过期返回 401)。
"""
from pathlib import Path

from fastapi import APIRouter, Depends

from app.core.deps import get_current_player
from app.core.errors import AppError, ok
from app.models import Player

router = APIRouter(prefix="/dev", tags=["dev"])

STATIC_ASSETS = Path(__file__).resolve().parent.parent / "static" / "assets"


@router.get("/assets")
def dev_assets(_: Player = Depends(get_current_player)):
    """完整资源清单:遍历 assets 目录树,列出所有文件及访问 URL。

    URL 规则:注册表类型(images/audio/config)→ /v1/assets/{type}/{rel};
    crops/terms/animals 属 images 子目录 → /v1/assets/images/{rel};
    未注册目录 → /static/assets/{rel}。
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
