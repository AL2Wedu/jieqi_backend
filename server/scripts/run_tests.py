"""板块化测试运行器:按功能板块分组跑测试,记录耗时,超时提醒。

用法:
    python -m scripts.run_tests [板块名...]     # 跑指定板块(默认全部)
    python -m scripts.run_tests list            # 列出板块
    python -m scripts.run_tests --all           # 跑全部板块(串行,避免共享 dev.db 污染)

板块划分(改什么测什么):
    auth      : 注册/登录/注销/改名/兑换码      test_account_features, test_iploc
    farm      : 播种/浇水/收获/枯萎/杂草        test_api, test_crop_settings, test_weed
    shop      : 商店/收成仓/出售               test_shop
    guest     : AI 客人议价                     test_guest
    pest      : 虫害系统                       test_pest
    world     : 每用户世界时钟/节气            test_world
    social    : 好友/社交/成就/任务/AI 转发     test_quests_social_ai
    admin     : 管理后台                       test_admin, test_admin_control
    assets    : 资源/美术/开发接口             test_assets, test_art, test_dev

超时提醒:单板块超过 60s 打印警告(板块太大,建议拆分)。
"""
import os
import subprocess
import sys
import time
from pathlib import Path

SERVER = Path(__file__).resolve().parent.parent
TESTS = SERVER / "tests"

# 板块 → 测试文件
BOARDS = {
    "auth": ["test_account_features", "test_iploc"],
    "farm": ["test_api", "test_crop_settings", "test_weed"],
    "shop": ["test_shop"],
    "guest": ["test_guest"],
    "pest": ["test_pest"],
    "world": ["test_world"],
    "social": ["test_quests_social_ai"],
    "admin": ["test_admin", "test_admin_control"],
    "assets": ["test_assets", "test_art", "test_dev"],
}
# 单板块超时阈值(秒)
TIMEOUT = 60


def _run_board(name: str, files: list[str]) -> tuple[float, str]:
    """跑一个板块,返回 (耗时, 结果摘要)。"""
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    t0 = time.time()
    r = subprocess.run(
        ["uv", "run", "python", "-m", "pytest", *[f"tests/{f}.py" for f in files], "-q"],
        capture_output=True, text=True, env=env, cwd=str(SERVER),
    )
    dt = time.time() - t0
    last = [l for l in r.stdout.strip().splitlines() if "passed" in l or "failed" in l]
    summary = last[-1] if last else "?"
    flag = " ⚠️超时" if dt > TIMEOUT else ""
    print(f"[{name}] {dt:.1f}s{flag}  {summary}")
    if dt > TIMEOUT:
        print(f"  ⚠️ 板块 {name} 超过 {TIMEOUT}s,建议拆分为更小的测试文件")
    return dt, summary


def main() -> int:
    args = sys.argv[1:]
    if not args or args[0] == "list":
        print("可用板块:")
        for name, files in BOARDS.items():
            print(f"  {name:8s}: {', '.join(files)}")
        return 0
    if args[0] == "--all":
        targets = list(BOARDS.items())
    else:
        targets = [(a, BOARDS[a]) for a in args if a in BOARDS]
        missing = [a for a in args if a not in BOARDS]
        if missing:
            print(f"未知板块: {missing}(可用: {', '.join(BOARDS)})")
            return 1
    total = 0.0
    failed = 0
    for name, files in targets:
        dt, summary = _run_board(name, files)
        total += dt
        if "failed" in summary:
            failed += 1
    print(f"\n共 {len(targets)} 板块,总耗时 {total:.1f}s,失败板块 {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
