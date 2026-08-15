"""jieqi_backend 压测工具(Locust)。

用法(见 loadtest/README.md):

    cd server
    uv run --group loadtest locust -f loadtest/locustfile.py --host http://127.0.0.1:8000

浏览器打开 http://localhost:8089 填并发/生成速率,或 headless:

    uv run --group loadtest locust -f loadtest/locustfile.py --host http://127.0.0.1:8000 \\
        --headless --users 100 --spawn-rate 20 --run-time 5m

设计要点
--------
1. **预注册用户池**:test_start 阶段按 `LOADTEST_POOL_SIZE`(默认 100)顺序注册一批账号,
   后续 User 从池中领取 token(池空则现场注册)。避免"压测全卡在注册",也保证每账号隔离。
2. **请求归类**:本后端用 `{code, error_code, message}` 信封。业务拒绝(HTTP 4xx 且带
   error_code,如 CROP_NOT_MATURE / PLOT_OCCUPIED / NOT_ENOUGH_COINS)是**预期游戏状态**,
   不算服务器故障 —— 单独计数;5xx / 网络错误 / 401(有效 token 不应出现)才算失败。
3. **用户画像按 README §7.3.3.1 热点分层**:静态素材 > 动态只读 > 写操作 > 登录/WS,
   配比由 `LOADTEST_W_*` 环境变量控制。
4. **动态路径统一命名**:/v1/farm/plots/{id}/sow 之类带 UUID 的路径用静态 name 聚合,
   否则每个 UUID 一条统计,报表会爆炸。

环境变量(均可不设,有默认):
    LOADTEST_HOST        目标地址(等价 --host),默认 http://127.0.0.1:8000
    LOADTEST_POOL_SIZE   预注册用户数,默认 100(0 = 不预注册)
    LOADTEST_PASSWORD    压测账号密码,默认 loadtest123
    LOADTEST_W_*         各用户画像权重(见下)
"""

from __future__ import annotations

import collections
import os
import random
import string
import time as _time

import requests
from locust import HttpUser, User, between, events, task

# websocket-client 为可选依赖(仅 WsUser 需要);缺失则跳过 WS 画像
try:
    import websocket as _websocket  # noqa: F401
    _HAS_WEBSOCKET = True
except Exception:  # noqa: BLE001
    _HAS_WEBSOCKET = False


# ---------------------------------------------------------------------------
# 配置(环境变量可覆盖)
# ---------------------------------------------------------------------------
HOST = os.environ.get("LOADTEST_HOST", "http://127.0.0.1:8000")
POOL_SIZE = int(os.environ.get("LOADTEST_POOL_SIZE", "100"))
POOL_PASSWORD = os.environ.get("LOADTEST_PASSWORD", "loadtest123")
SEED_PREFIX = os.environ.get("LOADTEST_SEED_PREFIX", "lt")

# 用户画像配比(weight 越大 spawn 越多)
WEIGHT_STATIC = int(os.environ.get("LOADTEST_W_STATIC", "40"))
WEIGHT_READ = int(os.environ.get("LOADTEST_W_READ", "40"))
WEIGHT_WRITE = int(os.environ.get("LOADTEST_W_WRITE", "10"))
WEIGHT_AUTH = int(os.environ.get("LOADTEST_W_AUTH", "5"))
WEIGHT_WS = int(os.environ.get("LOADTEST_W_WS", "5"))

# 15 种作物 slug(与 server/data/crops 一致;压测静态素材用)
CROP_SLUGS = [
    "baicai", "dacong", "dadou", "gaoliang", "guzi", "hongshu", "huasheng",
    "luobo", "mianhua", "qiaomai", "shuidao", "xiaomai", "youcai", "yumi", "zhima",
]
ART_STAGES = ["seed", "1", "2", "3"]  # 种子图标 + 苗期/生长期/成熟 3 阶段
ART_SIZES = [32, 64, 128, 256]        # 预渲染四档
TERM_COUNT = 24

# 业务拒绝统计(进程内;test_stop 打印汇总)
_business_rejections: collections.Counter = collections.Counter()


def _random_suffix(n: int = 6) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


# ---------------------------------------------------------------------------
# 预注册用户池
# ---------------------------------------------------------------------------
_token_pool: collections.deque = collections.deque()


def _resolve_host(environment) -> str:
    """优先 --host,回退 LOADTEST_HOST。"""
    h = getattr(environment, "host", None) or HOST
    return (h or "").rstrip("/")


def _register_one(host: str, idx: int) -> dict | None:
    """注册一个账号,返回 {name, password, token};失败返回 None。"""
    name = f"{SEED_PREFIX}_{os.getpid()}_{idx}_{_random_suffix()}"
    try:
        r = requests.post(
            f"{host}/v1/auth/register",
            json={"name": name, "password": POOL_PASSWORD},
            timeout=30,
        )
        if r.status_code == 200 and r.json().get("code") == 0:
            return {"name": name, "password": POOL_PASSWORD, "token": r.json()["data"]["token"]}
    except Exception:  # noqa: BLE001 注册失败不阻塞压测
        pass
    return None


@events.test_start.add_listener
def _seed_users(environment, **kwargs) -> None:
    """预注册账号池(顺序执行:单个连接复用 + 避免 gevent 线程池隐患)。"""
    if POOL_SIZE <= 0:
        return
    host = _resolve_host(environment)
    print(f"[loadtest] 预注册 {POOL_SIZE} 个用户到 {host} ...")
    s = requests.Session()
    ok = 0
    for i in range(POOL_SIZE):
        name = f"{SEED_PREFIX}_{os.getpid()}_{i}_{_random_suffix()}"
        try:
            r = s.post(
                f"{host}/v1/auth/register",
                json={"name": name, "password": POOL_PASSWORD},
                timeout=30,
            )
            if r.status_code == 200 and r.json().get("code") == 0:
                _token_pool.append(
                    {"name": name, "password": POOL_PASSWORD, "token": r.json()["data"]["token"]}
                )
                ok += 1
        except Exception:  # noqa: BLE001
            pass
        if (i + 1) % 50 == 0:
            print(f"[loadtest]   已注册 {i + 1}/{POOL_SIZE}")
    print(f"[loadtest] 预注册完成:成功 {ok}/{POOL_SIZE}")


def _acquire_credential(host: str) -> dict | None:
    """从池中领取一个 token;池空则现场注册(顺带压测注册接口)。"""
    if _token_pool:
        return _token_pool.popleft()
    return _register_one(host, random.randint(0, 10**9))


# ---------------------------------------------------------------------------
# 请求归类:业务拒绝不算服务器故障
# ---------------------------------------------------------------------------
def _classify_response(r) -> None:
    """把 4xx 业务拒绝重新归类为成功(预期游戏状态),单独计数。

    - 5xx / 网络错误(HTTP 0)/ 401(有效 token 不应出现) → 失败
    - 400/403/404 且带 error_code → 业务拒绝 → 成功(计入 _business_rejections)
    """
    if getattr(r, "status_code", 0) == 0:
        r.failure(f"network error: {getattr(r, 'error', None) or 'unknown'}")
        return
    body = None
    try:
        body = r.json()
    except Exception:  # noqa: BLE001 非 JSON(PNG/HTML)跳过
        body = None
    if r.status_code < 400:
        # 成功信封 code 恒为 0;非 0 属异常,记失败便于排查
        if body is not None and body.get("code") != 0:
            r.failure(f"unexpected code={body.get('code')} {body.get('message')}")
        return
    if r.status_code >= 500:
        r.failure(f"HTTP {r.status_code}: {body}")
        return
    if r.status_code == 401:
        r.failure(f"HTTP 401 auth failed: {body}")
        return
    if body and body.get("error_code"):
        _business_rejections[body["error_code"]] += 1
        r.success()
        return
    r.failure(f"HTTP {r.status_code}: {body}")


@events.test_stop.add_listener
def _report_business(environment, **kwargs) -> None:
    if _business_rejections:
        print("\n===== 业务拒绝统计(非服务器故障,预期游戏状态)=====")
        for code, n in _business_rejections.most_common():
            print(f"  {code}: {n}")
        print("=======================================================\n")


class _ApiMixin:
    """统一 GET/POST:catch_response=True + 业务拒绝归类。"""

    def api_get(self, path: str, *, name: str | None = None, params: dict | None = None):
        with self.client.get(path, name=name or path, params=params, catch_response=True) as r:
            _classify_response(r)
            return r

    def api_post(self, path: str, *, json=None, name: str | None = None):
        with self.client.post(path, name=name or path, json=json, catch_response=True) as r:
            _classify_response(r)
            return r


def _apply_token(self, host: str) -> None:
    """领取账号并装配 Bearer 头(供各认证画像 on_start 复用)。"""
    cred = _acquire_credential(host)
    if cred and cred.get("token"):
        self.client.headers["Authorization"] = f"Bearer {cred['token']}"
    return cred


# ---------------------------------------------------------------------------
# 画像 1:匿名静态素材(全服最高频:作物图/节气图/版本/清单)
# ---------------------------------------------------------------------------
class AnonymousAssetUser(HttpUser, _ApiMixin):
    weight = WEIGHT_STATIC
    wait_time = between(0.05, 0.5)  # 素材拉取最频繁

    @task(50)
    def crop_art(self):
        slug = random.choice(CROP_SLUGS)
        name = random.choice(ART_STAGES)
        w = random.choice(ART_SIZES)
        self.api_get(
            f"/v1/art/crops/{slug}/{name}.png",
            name="/v1/art/crops/{slug}/{name}.png",
            params={"w": w},
        )

    @task(25)
    def term_art(self):
        i = random.randint(1, TERM_COUNT)
        w = random.choice(ART_SIZES)
        self.api_get(
            f"/v1/art/terms/{i}/main.png",
            name="/v1/art/terms/{i}/main.png",
            params={"w": w},
        )

    @task(10)
    def art_version(self):
        self.api_get("/v1/art/version")

    @task(5)
    def art_manifest(self):
        self.api_get("/v1/art/manifest")

    @task(2)
    def openapi_docs(self):
        self.api_get("/docs")


# ---------------------------------------------------------------------------
# 画像 2:已登录动态只读(me / 节气 / 农场 / 商店 / 虫害 / 任务 / 成就 ...)
# ---------------------------------------------------------------------------
class PlayerReadUser(HttpUser, _ApiMixin):
    weight = WEIGHT_READ
    wait_time = between(1, 3)

    def on_start(self):
        _apply_token(self, _resolve_host(self.environment))

    @task(30)
    def me(self):
        self.api_get("/v1/player/me")

    @task(25)
    def calendar(self):
        self.api_get("/v1/calendar/current")

    @task(25)
    def farm_state(self):
        self.api_get("/v1/farm/state")

    @task(10)
    def shop_state(self):
        self.api_get("/v1/shop/state")

    @task(8)
    def pest_state(self):
        self.api_get("/v1/pest/state")

    @task(8)
    def quests(self):
        self.api_get("/v1/quests")

    @task(6)
    def achievements(self):
        self.api_get("/v1/achievements")

    @task(5)
    def friends(self):
        self.api_get("/v1/social/friends")

    @task(3)
    def storage(self):
        self.api_get("/v1/shop/storage")

    @task(2)
    def inventory(self):
        self.api_get("/v1/player/inventory")


# ---------------------------------------------------------------------------
# 画像 3:写操作生命周期(买种子 → 播种 → 浇水 → 收割 → 铲除 → 出售)
# ---------------------------------------------------------------------------
class FarmerUser(HttpUser, _ApiMixin):
    weight = WEIGHT_WRITE
    wait_time = between(2, 5)

    def on_start(self):
        _apply_token(self, _resolve_host(self.environment))
        self.plots: list[dict] = []       # [{plot_id, idx, crop}]
        self.seed_items: list[dict] = []  # [{item_id, crop_id, buy_price}]
        self._refresh()

    def _refresh(self):
        """拉取地块 + 商店种子道具,供后续写操作按需选目标(幂等可重入)。"""
        with self.client.get("/v1/farm/state", catch_response=True) as r:
            _classify_response(r)
            if r.status_code == 200:
                data = (r.json() or {}).get("data") or {}
                self.plots = [
                    {"plot_id": p.get("plot_id"), "idx": p.get("idx"), "crop": p.get("crop")}
                    for p in (data.get("plots") or [])
                ]
        with self.client.get("/v1/shop/state", catch_response=True) as r:
            _classify_response(r)
            if r.status_code == 200:
                data = (r.json() or {}).get("data") or {}
                self.seed_items = [
                    {
                        "item_id": it.get("item_id"),
                        "crop_id": (it.get("effect") or {}).get("crop_id"),
                        "buy_price": it.get("buy_price"),
                    }
                    for it in (data.get("items") or [])
                    if (it.get("effect") or {}).get("type") == "seed"
                ]

    @task(20)
    def buy_seed(self):
        if not self.seed_items:
            self._refresh()
        if not self.seed_items:
            return
        it = random.choice(self.seed_items)
        self.api_post(
            f"/v1/shop/items/{it['item_id']}/buy",
            name="/v1/shop/items/{item_id}/buy",
            json={"quantity": 1},
        )

    @task(15)
    def sow(self):
        if not self.seed_items:
            self._refresh()
        free = [p for p in self.plots if not p.get("crop")]
        if not free or not self.seed_items:
            return
        plot = random.choice(free)
        seed = random.choice(self.seed_items)
        if not seed.get("crop_id"):
            return
        r = self.api_post(
            f"/v1/farm/plots/{plot['plot_id']}/sow",
            name="/v1/farm/plots/{plot_id}/sow",
            json={"crop_id": seed["crop_id"]},
        )
        if r.status_code == 200:
            plot["crop"] = True  # 本地快照标记已占用

    @task(10)
    def water(self):
        occupied = [p for p in self.plots if p.get("crop")]
        if not occupied:
            return
        plot = random.choice(occupied)
        self.api_post(
            f"/v1/farm/plots/{plot['plot_id']}/water",
            name="/v1/farm/plots/{plot_id}/water",
        )

    @task(8)
    def harvest(self):
        occupied = [p for p in self.plots if p.get("crop")]
        if not occupied:
            return
        plot = random.choice(occupied)
        self.api_post(
            f"/v1/farm/plots/{plot['plot_id']}/harvest",
            name="/v1/farm/plots/{plot_id}/harvest",
        )

    @task(5)
    def clear_plot(self):
        occupied = [p for p in self.plots if p.get("crop")]
        if not occupied:
            return
        plot = random.choice(occupied)
        self.api_post(
            f"/v1/farm/plots/{plot['plot_id']}/clear",
            name="/v1/farm/plots/{plot_id}/clear",
        )

    @task(5)
    def weed_clear(self):
        if not self.plots:
            return
        plot = random.choice(self.plots)
        self.api_post(
            f"/v1/farm/plots/{plot['plot_id']}/weed-clear",
            name="/v1/farm/plots/{plot_id}/weed-clear",
        )

    @task(5)
    def sell_crop(self):
        with self.client.get("/v1/shop/storage", catch_response=True) as r:
            _classify_response(r)
            if r.status_code != 200:
                return
            items = ((r.json() or {}).get("data") or {}).get("items") or []
        if not items:
            return
        it = random.choice(items)
        if not it.get("crop_id"):
            return
        self.api_post(
            f"/v1/shop/crops/{it['crop_id']}/sell",
            name="/v1/shop/crops/{crop_id}/sell",
            json={"quantity": 1},
        )


# ---------------------------------------------------------------------------
# 画像 4:注册 / 登录(PBKDF2 10 万次迭代 = CPU 热点)
# ---------------------------------------------------------------------------
class AuthUser(HttpUser, _ApiMixin):
    weight = WEIGHT_AUTH
    wait_time = between(2, 5)

    def on_start(self):
        self._name = f"{SEED_PREFIX}_a_{os.getpid()}_{random.randint(0, 10**9)}_{_random_suffix()}"
        self.api_post("/v1/auth/register", json={"name": self._name, "password": POOL_PASSWORD})

    @task(8)
    def login(self):
        self.api_post(
            "/v1/auth/login", json={"name": self._name, "password": POOL_PASSWORD}
        )

    @task(1)
    def bad_login(self):
        # 错误密码:测失败路径开销(哈希校验成本)
        self.api_post(
            "/v1/auth/login", json={"name": self._name, "password": "wrongpass"}
        )


# ---------------------------------------------------------------------------
# 画像 5:WebSocket 长连接(节气推送 + 心跳 ping/pong)
# ---------------------------------------------------------------------------
if _HAS_WEBSOCKET:

    class WsUser(User):
        weight = WEIGHT_WS
        wait_time = between(3, 6)

        def on_start(self):
            host = _resolve_host(self.environment)
            cred = _acquire_credential(host)
            token = (cred or {}).get("token")
            self._ws = None
            if not token:
                return
            ws_url = host.replace("https://", "wss://").replace("http://", "ws://")
            try:
                self._ws = _websocket.create_connection(
                    f"{ws_url}/v1/ws?token={token}", timeout=10
                )
                self._ws.settimeout(10)
                self._ws.recv()  # 首帧 solar_term_change
            except Exception as e:  # noqa: BLE001
                _fire_ws(self, "connect", 0, None, exc=e)
                self._close_ws()

        def _close_ws(self):
            if self._ws:
                try:
                    self._ws.close()
                except Exception:  # noqa: BLE001
                    pass
                self._ws = None

        def on_stop(self):
            self._close_ws()

        @task
        def ping_pong(self):
            if not self._ws:
                return
            start = _time.perf_counter()
            try:
                self._ws.send("ping")
                self._ws.recv()  # pong 或 solar_term_change
                _fire_ws(self, "ping", start, None)
            except Exception as e:  # noqa: BLE001
                _fire_ws(self, "ping", start, None, exc=e)
                self._close_ws()


def _fire_ws(user, name: str, start, response_len, exc=None):
    """把 WS 操作计入 locust 统计(统一 request_type=WS)。"""
    ms = int((_time.perf_counter() - start) * 1000) if start else 0
    user.environment.events.request.fire(
        request_type="WS",
        name=name,
        response_time=ms,
        response_length=response_len or 0,
        exception=exc,
    )
