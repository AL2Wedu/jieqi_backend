"""植物美术资产生成:扁平风 SVG 占位图(种子 + 苗期/生长期/成熟三阶段)。

- 每个作物一个目录:static/assets/crops/<slug>/{seed,1,2,3}.svg
- 6 种初始作物用各自配色;管理员新建作物时生成通用绿色模板
- 美术路径存 crops.art JSON:{"seed":path, "stages":[3 个阶段图]}
"""
from pathlib import Path

ART_ROOT = Path(__file__).resolve().parent.parent / "static" / "assets" / "crops"


def _wrap(inner: str) -> str:
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128" width="128" height="128">'
        f"<rect width=\"128\" height=\"128\" rx=\"18\" fill=\"#1f2937\"/>"
        f"{inner}</svg>"
    )


def _soil() -> str:
    return (
        '<ellipse cx="64" cy="108" rx="40" ry="12" fill="#6b4f3a"/>'
        '<ellipse cx="64" cy="105" rx="40" ry="12" fill="#8a6a4b"/>'
        '<ellipse cx="64" cy="102" rx="30" ry="8" fill="#a07850"/>'
    )


def svg_seed(color: str) -> str:
    return _wrap(
        f'<ellipse cx="64" cy="82" rx="17" ry="11" fill="{color}" transform="rotate(-24 64 82)"/>'
        f'<path d="M64 72c-2-8 4-16 12-18 8-2 14 4 12 12-2 8-10 12-12 12s-9-2-12-6z" fill="#e8f5e9"/>'
        '<path d="M58 66c-1-6 3-12 9-14 6-2 11 2 9 8" stroke="#81c784" stroke-width="3" fill="none" stroke-linecap="round"/>'
    )


def svg_stage1(color: str) -> str:
    return _wrap(
        _soil()
        + f'<path d="M64 102c0-16-6-26-14-30" stroke="{color}" stroke-width="5" fill="none" stroke-linecap="round"/>'
        + f'<path d="M50 76c-8-4-13-12-12-20 8-2 15 3 17 11z" fill="{color}"/>'
        + f'<path d="M50 76c-8-4-13-12-12-20 8-2 15 3 17 11z" fill="{color}" transform="scale(-1 1) translate(-128 0)"/>'
        + f'<circle cx="64" cy="58" r="4" fill="{color}"/>'
    )


def svg_stage2(color: str) -> str:
    return _wrap(
        _soil()
        + f'<path d="M64 102c0-26-4-40-12-48" stroke="{color}" stroke-width="6" fill="none" stroke-linecap="round"/>'
        + f'<path d="M64 102c0-26 4-40 12-48" stroke="{color}" stroke-width="6" fill="none" stroke-linecap="round"/>'
        + f'<path d="M52 62c-10-3-16-11-15-20 10-1 17 5 19 13z" fill="{color}"/>'
        + f'<path d="M76 62c10-3 16-11 15-20-10-1-17 5-19 13z" fill="{color}"/>'
        + f'<path d="M54 44c-9-4-14-12-12-20 9 0 15 6 16 14z" fill="{color}" opacity=".85"/>'
        + f'<path d="M74 44c9-4 14-12 12-20-9 0-15 6-16 14z" fill="{color}" opacity=".85"/>'
        + '<path d="M59 92c0-10 3-16 5-16s5 6 5 16-2 8-5 8-5-2-5-8z" fill="#e8f5e9"/>'
    )


def svg_stage3(color: str, produce: str, kind: str) -> str:
    parts = [
        _soil(),
        f'<path d="M64 102c0-34-6-52-16-62" stroke="{color}" stroke-width="7" fill="none" stroke-linecap="round"/>',
        f'<path d="M64 102c0-34 6-52 16-62" stroke="{color}" stroke-width="7" fill="none" stroke-linecap="round"/>',
        f'<path d="M48 56c-12-3-19-12-18-22 12-1 20 6 22 15z" fill="{color}"/>',
        f'<path d="M80 56c12-3 19-12 18-22-12-1-20 6-22 15z" fill="{color}"/>',
        f'<path d="M50 34c-10-4-15-13-13-22 10 0 16 7 17 16z" fill="{color}" opacity=".8"/>',
        f'<path d="M78 34c10-4 15-13 13-22-10 0-16 7-17 16z" fill="{color}" opacity=".8"/>',
        f'<path d="M64 40v-8" stroke="{color}" stroke-width="3" stroke-linecap="round"/>',
    ]
    if kind == "grains":  # 稻/麦:穗状
        for dx in (-10, 0, 10):
            parts.append(
                f'<path d="M64 34c{dx}-8 {dx+3}-14 {dx+3}-14s{dx+11} 4 {dx+9} 12c-1 7-8 10-12 2z" fill="{produce}"/>'
            )
    elif kind == "pods":  # 豆荚
        for dx in (-9, 9):
            parts.append(
                f'<ellipse cx="{64+dx}" cy="48" rx="6" ry="12" fill="{produce}" transform="rotate({20 if dx>0 else -20} {64+dx} 48)"/>'
            )
    elif kind == "fruits":  # 番茄
        for cx, cy in ((56, 46), (72, 46), (64, 56), (50, 56), (78, 56)):
            parts.append(f'<circle cx="{cx}" cy="{cy}" r="7" fill="{produce}"/>')
        parts.append('<path d="M64 36c-4-8 4-12 8-8 0 0 1 3-2 4z" fill="#81c784"/>')
    elif kind == "flower":  # 菊花
        for i in range(8):
            import math

            a = math.pi * 2 * i / 8
            cx, cy = 64 + 14 * math.cos(a), 42 + 14 * math.sin(a)
            parts.append(
                f'<ellipse cx="{cx:.1f}" cy="{cy:.1f}" rx="5" ry="9" fill="{produce}" transform="rotate({i*45} {cx:.1f} {cy:.1f})"/>'
            )
        parts.append('<circle cx="64" cy="42" r="7" fill="#ffd54f"/>')
    elif kind == "head":  # 白菜:包心
        parts.append(
            f'<ellipse cx="64" cy="52" rx="14" ry="20" fill="{produce}"/>'
            f'<path d="M52 44c-6-4-8-10-6-16 8 0 13 5 14 12z" fill="{produce}"/>'
            f'<path d="M76 44c6-4 8-10 6-16-8 0-13 5-14 12z" fill="{produce}"/>'
        )
    return _wrap("".join(parts))


def generate_crop_art(slug: str, color: str, produce: str, kind: str) -> dict:
    """生成一个作物的美术:SVG(矢量源)+ 多分辨率预渲染 PNG。返回 art JSON。"""
    d = ART_ROOT / slug
    d.mkdir(parents=True, exist_ok=True)
    files = {
        "seed.svg": svg_seed(color),
        "1.svg": svg_stage1(color),
        "2.svg": svg_stage2(color),
        "3.svg": svg_stage3(color, produce, kind),
    }
    for name, body in files.items():
        (d / name).write_text(body, encoding="utf-8")
    # 预渲染 PNG:每个素材 × 多个分辨率(客户端按请求分辨率取图)
    for stage, svg_name in (("seed", "seed.svg"), ("1", "1.svg"), ("2", "2.svg"), ("3", "3.svg")):
        for size in PRERENDER_SIZES:
            (d / f"{svg_name.removesuffix('.svg')}_{size}.png").write_bytes(
                render_png(slug, stage, size)
            )
    return default_art(slug)


def default_art(slug: str) -> dict:
    return {
        "seed": f"/static/assets/crops/{slug}/seed.svg",
        "stages": [f"/static/assets/crops/{slug}/{i}.svg" for i in (1, 2, 3)],
    }


# ---------- Pillow 预渲染(多分辨率 PNG,与 SVG 同款形状) ----------

from PIL import Image  # noqa: E402

PRERENDER_SIZES = (32, 64, 128, 256)

_LEAF = "#7cb342"
_BG = (31, 41, 55, 255)  # #1f2937
_SOIL = ((107, 79, 58, 255), (138, 106, 75, 255), (160, 120, 80, 255))


def _hex(c: str) -> tuple:
    c = c.lstrip("#")
    return (int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16), 255)


def _rot_ellipse(d, cx, cy, rx, ry, angle, fill, n=24):
    """旋转椭圆(多边形近似,角度制)。"""
    import math

    ra = math.radians(angle)
    pts = []
    for i in range(n):
        a = math.radians(i * 360 / n)
        x = cx + rx * math.cos(a)
        y = cy + ry * math.sin(a)
        pts.append((cx + (x - cx) * math.cos(ra) - (y - cy) * math.sin(ra),
                    cy + (x - cx) * math.sin(ra) + (y - cy) * math.cos(ra)))
    d.polygon(pts, fill=fill)


def render_png(slug: str, stage: str, size: int) -> bytes:
    """按 slug 配色渲染指定阶段(stage: seed/1/2/3)的 PNG。"""
    from io import BytesIO

    from PIL import Image, ImageDraw

    spec = CROP_SPECS.get(slug, (_LEAF, "#f0c040", "grains"))
    leaf = _hex(spec[0])
    produce = _hex(spec[1])
    kind = spec[2]
    s = size / 128.0
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=max(2, int(18 * s)), fill=_BG)

    def soil():
        for i, c in enumerate(_SOIL):
            d.ellipse([24 * s, (96 + i * 1.5) * s, 104 * s, (120 + i * 1.5) * s], fill=c)

    def stem(x1, y1, x2, y2, w):
        d.line([x1 * s, y1 * s, x2 * s, y2 * s], fill=leaf, width=max(2, int(w * s)))

    if stage == "seed":
        _rot_ellipse(d, 64 * s, 82 * s, 17 * s, 11 * s, -24, leaf)
        _rot_ellipse(d, 64 * s, 70 * s, 12 * s, 9 * s, 8, _hex("#e8f5e9"))
        stem(62 * s, 76 * s, 60 * s, 60 * s, 3)
    elif stage == "1":
        soil()
        stem(64, 102, 64, 72, 5)
        _rot_ellipse(d, 50 * s, 72 * s, 9 * s, 5 * s, -20, leaf)
        _rot_ellipse(d, 78 * s, 72 * s, 9 * s, 5 * s, 20, leaf)
        d.ellipse([60 * s, 54 * s, 68 * s, 62 * s], fill=leaf)
    elif stage == "2":
        soil()
        stem(64, 102, 64, 54, 6)
        stem(64, 102, 64, 60, 6)
        _rot_ellipse(d, 50 * s, 62 * s, 11 * s, 6 * s, -28, leaf)
        _rot_ellipse(d, 78 * s, 62 * s, 11 * s, 6 * s, 28, leaf)
        _rot_ellipse(d, 54 * s, 44 * s, 9 * s, 5 * s, -40, leaf)
        _rot_ellipse(d, 74 * s, 44 * s, 9 * s, 5 * s, 40, leaf)
        _rot_ellipse(d, 64 * s, 92 * s, 5 * s, 8 * s, 0, _hex("#e8f5e9"))
    else:  # stage 3 成熟
        soil()
        stem(64, 102, 64, 40, 7)
        stem(64, 102, 64, 46, 7)
        _rot_ellipse(d, 48 * s, 56 * s, 12 * s, 7 * s, -30, leaf)
        _rot_ellipse(d, 80 * s, 56 * s, 12 * s, 7 * s, 30, leaf)
        _rot_ellipse(d, 50 * s, 34 * s, 10 * s, 6 * s, -45, leaf)
        _rot_ellipse(d, 78 * s, 34 * s, 10 * s, 6 * s, 45, leaf)
        stem(64, 40, 64, 32, 3)
        if kind == "grains":  # 稻/麦:三簇穗
            for dx in (-10, 0, 10):
                _rot_ellipse(d, (64 + dx) * s, 32 * s, 6 * s, 9 * s, dx, produce)
        elif kind == "pods":  # 豆荚
            _rot_ellipse(d, 55 * s, 48 * s, 4 * s, 10 * s, -20, produce)
            _rot_ellipse(d, 73 * s, 48 * s, 4 * s, 10 * s, 20, produce)
        elif kind == "fruits":  # 番茄
            for cx, cy in ((56, 46), (72, 46), (64, 56), (50, 56), (78, 56)):
                d.ellipse([(cx - 7) * s, (cy - 7) * s, (cx + 7) * s, (cy + 7) * s], fill=produce)
            _rot_ellipse(d, 64 * s, 36 * s, 4 * s, 2 * s, 0, _hex("#81c784"))
        elif kind == "flower":  # 菊花
            import math

            for i in range(8):
                a = math.pi * 2 * i / 8
                cx = 64 + 14 * math.cos(a)
                cy = 42 + 14 * math.sin(a)
                _rot_ellipse(d, cx * s, cy * s, 5 * s, 9 * s, i * 45, produce)
            d.ellipse([57 * s, 35 * s, 71 * s, 49 * s], fill=_hex("#ffd54f"))
        elif kind == "head":  # 白菜
            d.ellipse([50 * s, 32 * s, 78 * s, 72 * s], fill=produce)
            _rot_ellipse(d, 54 * s, 44 * s, 8 * s, 14 * s, -18, produce)
            _rot_ellipse(d, 74 * s, 44 * s, 8 * s, 14 * s, 18, produce)

    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def ensure_prerendered(slug: str) -> None:
    """确保某个作物的多分辨率 PNG 已预渲染(无则补渲染)。

    素材来源优先级:同名 PNG(真实美术素材,按目标宽度等比缩放)→ SVG(程序生成,方形渲染)。
    """
    d = ART_ROOT / slug
    for stage in ("seed", "1", "2", "3"):
        src_png = d / f"{stage}.png"
        src_svg = d / f"{stage}.svg"
        if not src_png.exists() and not src_svg.exists() and stage == "seed":
            # seed 无独立素材时用阶段 1 兼作种子图
            src_png = d / "1.png" if (d / "1.png").exists() else d / "1.svg"
        for size in PRERENDER_SIZES:
            out = d / f"{stage}_{size}.png"
            if out.exists():
                continue
            if src_png.exists():
                img = Image.open(src_png).convert("RGBA")
                w, h = img.size
                target_h = max(1, round(h * size / w))
                img.resize((size, target_h), Image.LANCZOS).save(out, "PNG")
            elif src_svg.exists():
                out.write_bytes(render_png(slug, stage, size))


def prerender_all() -> dict:
    """预渲染全部作物美术,返回 {slug: art}。"""
    arts = generate_all()
    for slug in arts:
        ensure_prerendered(slug)
    return arts


# 6 种初始作物配色:slug -> (叶色, 果实色, 形态)
CROP_SPECS = {
    "rice": ("#7cb342", "#f0c040", "grains"),
    "wheat": ("#a4b040", "#e3b341", "grains"),
    "soybean": ("#66bb6a", "#4caf50", "pods"),
    "cabbage": ("#9ccc65", "#c5e1a5", "head"),
    "tomato": ("#4caf50", "#ef5350", "fruits"),
    "chrysanthemum": ("#66bb6a", "#ff9800", "flower"),
}


def generate_all() -> dict:
    """生成全部初始作物美术,返回 {slug: art}。"""
    return {slug: generate_crop_art(slug, *spec) for slug, spec in CROP_SPECS.items()}


if __name__ == "__main__":
    for slug, art in generate_all().items():
        print(f"{slug}: {art['seed']}")
