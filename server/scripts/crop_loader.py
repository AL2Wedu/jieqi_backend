"""植物设定 JSONC 加载器。

数据源:server/data/crops/<slug>.json —— 每株植物一个文件,支持 // 注释(方便策划直接改)。
- 下划线开头的文件(如 _template.json)跳过,不导入
- 返回按 sort_order 排序的植物字典列表
- dump_crop_file():管理后台新增/修改作物时把完整设定写回文件(字段齐全,不保留注释)
"""
import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
CROPS_DIR = DATA_DIR / "crops"


def strip_jsonc(text: str) -> str:
    """去掉 // 行注释(字符串字面量内部的 // 保留)。"""
    out = []
    i, n = 0, len(text)
    in_str = False
    while i < n:
        ch = text[i]
        if in_str:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if ch == '"':
                in_str = False
            i += 1
            continue
        if ch == '"':
            in_str = True
            out.append(ch)
            i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def load_crops() -> list[dict]:
    """读取全部植物设定(跳过 _ 开头文件),按 sort_order 排序。"""
    plants = []
    for f in sorted(CROPS_DIR.glob("*.json")):
        if f.name.startswith("_"):
            continue
        data = json.loads(strip_jsonc(f.read_text(encoding="utf-8")))
        data["_file"] = f.name
        plants.append(data)
    plants.sort(key=lambda c: c.get("sort_order", 0))
    return plants


def dump_crop_file(crop: dict, file_name: str | None = None) -> Path:
    """把作物设定写回 JSON 文件(管理后台增改用;无注释,字段完整)。"""
    data = {k: v for k, v in crop.items() if not k.startswith("_")}
    path = CROPS_DIR / (file_name or f"{crop['slug']}.json")
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return path
