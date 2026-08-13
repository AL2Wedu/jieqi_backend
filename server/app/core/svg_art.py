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
    """生成一个作物的 4 张美术,返回 art JSON。"""
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
    return default_art(slug)


def default_art(slug: str) -> dict:
    return {
        "seed": f"/static/assets/crops/{slug}/seed.svg",
        "stages": [f"/static/assets/crops/{slug}/{i}.svg" for i in (1, 2, 3)],
    }


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
