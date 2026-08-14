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
    """返回 {code: (error_code, http_status)}。

    解析器按引号状态跳过字符串内容(含 f-string),再按括号深度截取每个
    AppError(...) 调用,提取 name / code= / http_status=。
    """
    codes: dict[str, tuple[str, int]] = {}

    def _parse(text: str) -> None:
        for m in re.finditer(r"AppError\(", text):
            i = m.end()
            depth, in_str, j = 1, False, i
            while j < len(text) and depth > 0:
                ch = text[j]
                if in_str:
                    if ch == "\\":
                        j += 2
                        continue
                    if ch == '"':
                        in_str = False
                    j += 1
                    continue
                if ch == '"':
                    in_str = True
                    j += 1
                    continue
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                j += 1
            call = text[m.start():j]
            name_m = re.search(r'AppError\(\s*"([A-Z_]+)"', call)
            code_m = re.search(r"code=(\d+)", call)
            http_m = re.search(r"http_status=(\d+)", call)
            if name_m and code_m:
                codes[int(code_m.group(1))] = (
                    name_m.group(1),
                    int(http_m.group(1)) if http_m else 400,
                )

    for folder in ("services", "core", "api"):
        base = Path(__file__).resolve().parent.parent / "app" / folder
        for f in sorted(base.glob("*.py")):
            _parse(f.read_text(encoding="utf-8"))
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


def _norm_path(p: str) -> str:
    """路径归一化:{param}→{}、去查询串、去 /v1 前缀、去反斜杠转义。"""
    p = re.sub(r"\{[^}]+\}", "{}", p)
    p = re.sub(r"\?.*$", "", p)
    p = p.replace("\\", "")
    p = p.replace("/v1", "", 1) if p.startswith("/v1") else p
    return p


def _doc_routes() -> set[str]:
    api_md = (REPO / "API.md").read_text(encoding="utf-8")
    found = set(
        re.findall(
            r"\|\s*(?:\d+|—)\s*\|\s*(?:GET|POST|PUT|PATCH|DELETE|WS)\s*\|\s*`(/[^`]+)`",
            api_md,
        )
    )
    return {_norm_path(p) for p in found}


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
    refs = set()
    for m in re.finditer(r"`([^`]*/v1/[^`]*)`", readme):
        for part in re.split(r"[|｜]", m.group(1)):
            part = re.sub(r"^(GET|POST|PUT|PATCH|DELETE|WS)\s*", "", part.strip())
            if part.startswith("/v1"):
                refs.add(part)

    missing_ref = sorted(r for r in refs if _norm_path(r) not in doc)
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
