"""导入 24 节气图片:桌面《二十四节气》→ static/assets/terms/<slug>/main.png + 预渲染 4 档。

用法:uv run python -m scripts.import_term_images [源目录]
默认源:C:\\Users\\YsyTom\\Desktop\\二十四节气
"""
import shutil
import sys
from pathlib import Path

from app.core.svg_art import TERM_ART_ROOT, TERM_SLUGS, ensure_terms_prerendered

_DEFAULT_SRC = Path(r"C:\Users\YsyTom\Desktop\二十四节气")

# 节气名 → slug(与 TERM_SLUGS 顺序对应)
_NAME_TO_SLUG = {
    "立春": "lichun", "雨水": "yushui", "惊蛰": "jingzhe", "春分": "chunfen",
    "清明": "qingming", "谷雨": "guyu", "立夏": "lixia", "小满": "xiaoman",
    "芒种": "mangzhong", "夏至": "xiazhi", "小暑": "xiaoshu", "大暑": "dashu",
    "立秋": "liqiu", "处暑": "chushu", "白露": "bailu", "秋分": "qiufen",
    "寒露": "hanlu", "霜降": "shuangjiang", "立冬": "lidong", "小雪": "xiaoxue",
    "大雪": "daxue", "冬至": "dongzhi", "小寒": "xiaohan", "大寒": "dahan",
}


def main() -> int:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else _DEFAULT_SRC
    if not src.is_dir():
        print(f"✗ 源目录不存在: {src}")
        return 1
    imported = 0
    for name, slug in _NAME_TO_SLUG.items():
        f = src / f"{name}.png"
        if not f.exists():
            print(f"✗ 缺图:{name}")
            continue
        out_dir = TERM_ART_ROOT / slug
        out_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, out_dir / "main.png")
        imported += 1
    ensure_terms_prerendered()
    print(f"✓ 已导入 {imported}/24 张节气图并预渲染(static/assets/terms/<slug>/main_*_128.png 等)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
