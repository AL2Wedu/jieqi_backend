"""美术素材下发:按客户端请求的分辨率(w)下发预渲染 PNG。

协议:GET /v1/art/crops/{slug}/{seed|1|2|3}.png?w=<目标像素>
- 服务端从预渲染集(32/64/128/256)选取 最小不小于 w 的分辨率,没有则取最大
- 全部素材启动/创建时预渲染,请求零渲染开销
"""
from fastapi import APIRouter, Query
from fastapi.responses import FileResponse

from app.core.errors import AppError
from app.core.svg_art import ART_ROOT, PRERENDER_SIZES, ensure_prerendered

router = APIRouter(prefix="/art", tags=["art"])

_ALLOWED_NAMES = {"seed", "1", "2", "3"}


@router.get("/crops/{slug}/{name}.png")
def crop_art(
    slug: str,
    name: str,
    w: int = Query(default=128, ge=8, le=1024, description="目标宽度像素,服务端选最近预渲染档"),
):
    if name not in _ALLOWED_NAMES:
        raise AppError("ART_NOT_FOUND", "美术素材不存在", http_status=404, code=28001)
    svg = ART_ROOT / slug / f"{name}.svg"
    if not svg.exists():
        raise AppError("ART_NOT_FOUND", "作物美术不存在", http_status=404, code=28001)
    ensure_prerendered(slug)  # 幂等:缺档自动补渲染
    chosen = next((sz for sz in sorted(PRERENDER_SIZES) if sz >= w), max(PRERENDER_SIZES))
    f = ART_ROOT / slug / f"{name}_{chosen}.png"
    if not f.exists():
        raise AppError("ART_NOT_FOUND", "美术档缺失", http_status=404, code=28001)
    return FileResponse(
        f,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )
