"""API 文档一致性校验 + 清单生成(以代码为唯一事实源)。

用法:
  uv run python -m scripts.verify_api_docs inventory   # 生成端点/错误码全量清单(文档编写底稿)
  uv run python -m scripts.verify_api_docs check       # 三查:端点双向核对 + 错误码核对 + 交叉引用

说明:
- 端点提取:app/api/*.py 的 @router 装饰器 + 各文件前缀
- 错误码提取:AppError("NAME", "msg", http_status=H, code=N) 全量
- check 模式需要 API.md 与 README.md 位于仓库根目录
"""
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
API_DIR = REPO / "server" / "app" / "api"

# 各 api 文件的路由前缀
PREFIX = {
    "auth.py": "/auth",
    "player.py": "/player",
    "calendar.py": "/calendar",
    "farm.py": "/farm",
    "shop.py": "/shop",
    "quests.py": "/quests",
    "social.py": "/social",
    "achievements.py": "/achievements",
    "ai.py": "/ai",
    "art.py": "/art",
    "pest.py": "",  # pest.py 的 router 无前缀,路径自带(/farm/pest/... 与 /pest/state)
    "debug.py": "/debug",
    "admin.py": "/admin",
}
WS_PREFIX = {"admin.py": "/admin"}  # admin.py 的 /logs WS

# 非 @router 的端点白名单(框架/挂载/页面)
WHITELIST = {"/docs", "/static/*", "/admin", "/ws"}


def extract_routes() -> list[tuple[str, str, str]]:
    """返回 [(method, full_path, file)]。"""
    routes = []
    for fname, prefix in PREFIX.items():
        text = (API_DIR / fname).read_text(encoding="utf-8")
        for m in re.finditer(
            r'@router\.(get|post|put|patch|delete)\("([^"]+)"\)', text
        ):
            routes.append((m.group(1).upper(), prefix + m.group(2), fname))
        for m in re.finditer(r'@router\.websocket\("([^"]+)"\)', text):
            routes.append(("WS", WS_PREFIX.get(fname, "") + m.group(1), fname))
    return routes


def extract_error_codes() -> dict[str, tuple[str, int]]:
    """返回 {code: (error_code, http_status)}。"""
    codes: dict[str, tuple[str, int]] = {}
    for f in (API_DIR / ".." / "services").glob("*.py"):
        text = f.read_text(encoding="utf-8")
        for m in re.finditer(
            r'AppError\(\s*"([A-Z_]+)"\s*,\s*"[^"]*"\s*,\s*(?:http_status=(\d+)\s*,\s*)?code=(\d+)',
            text,
        ):
            name, http, code = m.group(1), int(m.group(2) or 400), int(m.group(3))
            codes[code] = (name, http)
    for f in (API_DIR / ".." / "core").glob("*.py"):
        text = f.read_text(encoding="utf-8")
        for m in re.finditer(
            r'AppError\(\s*"([A-Z_]+)"\s*,\s*"[^"]*"\s*,\s*(?:http_status=(\d+)\s*,\s*)?code=(\d+)',
            text,
        ):
            name, http, code = m.group(1), int(m.group(2) or 400), int(m.group(3))
            codes[code] = (name, http)
    return codes


def inventory() -> None:
    routes = extract_routes()
    codes = extract_error_codes()
    print("=" * 60)
    print(f"REST/WS 端点总数: {len(routes)}")
    print("=" * 60)
    cur = None
    for method, path, fname in sorted(routes, key=lambda r: (r[2], r[1])):
        if fname != cur:
            print(f"\n── {fname}")
            cur = fname
        print(f"  {method:6s} {path}")
    print("\n" + "=" * 60)
    print(f"错误码总数: {len(codes)}")
    print("=" * 60)
    for code in sorted(codes):
        name, http = codes[code]
        print(f"  {code} | {name} | HTTP {http}")


def _doc_routes() -> set[str]:
    api_md = (REPO / "API.md").read_text(encoding="utf-8")
    found = set(
        re.findall(r"\|\s*\d+\s*\|\s*(?:GET|POST|PUT|PATCH|DELETE|WS)\s*\|\s*`(/[^`]+)`", api_md)
    )

    def norm(p: str) -> str:
        p = re.sub(r"\{[^}]+\}", "{}", p)
        p = re.sub(r"\?.*$", "", p)
        p = p.replace("/v1", "", 1) if p.startswith("/v1") else p
        return p

    return {norm(p) for p in found}


def check() -> int:
    ok = True
    routes = extract_routes()
    codes = extract_error_codes()

    # 1) 端点双向核对
    src = {re.sub(r"\{[^}]+\}", "{}", p) for _, p, _ in routes} | WHITELIST
    doc = _doc_routes()
    missing_in_doc = sorted(src - doc)
    missing_in_src = sorted(doc - src)
    if missing_in_doc:
        ok = False
        print(f"[FAIL] 源码有但文档缺失: {missing_in_doc}")
    if missing_in_src:
        ok = False
        print(f"[FAIL] 文档有但源码无: {missing_in_src}")
    if not missing_in_doc and not missing_in_src:
        print(f"[PASS] 端点双向核对({len(src)} 个端点)")

    # 2) 错误码核对
    api_md = (REPO / "API.md").read_text(encoding="utf-8")
    doc_codes = set(re.findall(r"\|\s*(\d{5})\s*\|\s*([A-Z_]+)\s*\|", api_md))
    doc_map = {int(c): n for c, n in doc_codes}
    doc_map[90000] = "INTERNAL_ERROR"  # 500 兜底行
    missing = {c for c in codes if c not in doc_map}
    if missing:
        ok = False
        print(f"[FAIL] 文档错误码表缺失: {sorted(missing)}")
    else:
        print(f"[PASS] 错误码核对({len(codes)} 个错误码)")

    # 3) 交叉引用:README 引用的 /v1/... 路径在 API.md 存在
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    refs = set(re.findall(r"`(/v1/[a-z0-9/{}_.\-]+)`", readme))
    missing_ref = sorted(r for r in refs if re.sub(r"\{[^}]+\}", "{}", r) not in doc)
    if missing_ref:
        ok = False
        print(f"[FAIL] README 引用了文档中不存在的路径: {missing_ref}")
    else:
        print(f"[PASS] README↔API.md 交叉引用({len(refs)} 处引用)")

    return 0 if ok else 1


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "inventory"
    if mode == "inventory":
        inventory()
        return 0
    if mode == "check":
        return check()
    print(f"未知模式: {mode}(可选 inventory / check)")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
