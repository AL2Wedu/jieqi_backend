# 压测工具(Locust)

对 jieqi_backend 的 HTTP + WebSocket 接口做负载测试。基于 [Locust](https://locust.io/),Python 生态,与后端同一 `uv` 工程管理。

> 目标:测出**瓶颈**(SQLite 写并发、PBKDF2 登录 CPU、农场状态读放大、WS 长连接数),不是测游戏玩法成功与否 —— 业务拒绝(作物未成熟、地块占用、金币不足)是**预期状态**,本工具已单独归类、不计入失败。

---

## 1. 安装依赖

依赖已在 `pyproject.toml` 的 `loadtest` dependency group 里:

```bash
cd server
uv sync --group loadtest   # 安装 locust + websocket-client(以及基础依赖)
```

无需改动后端代码;压测是纯黑盒 HTTP/WS 客户端。

## 2. 启动被测服务

压测前先把后端跑起来(推荐用**一次性/演示数据库**,别打生产库):

```bash
cd server
# 方式一:前台直跑
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000

# 方式二:独立进程(推荐,Windows)
powershell -File server/scripts/run_server.ps1
```

> 建议压测前先 `DEBUG_ENABLED=true`(默认已开),便于需要时用调试接口催熟/推进节气。

## 3. 运行

> **Windows 必读**:locust 启动时会读当前目录的 `pyproject.toml`,而本工程的 `pyproject.toml` 含中文 UTF-8 注释,Windows 默认 GBK 解码会直接报 `Couldn't parse TOML file: 'gbk' codec can't decode ...`。
> 解决:bash(Git Bash)在命令前加 `PYTHONUTF8=1`(见下方命令);PowerShell 先执行 `$env:PYTHONUTF8=1` 再运行。

### 3.1 Web UI(可视化)

```bash
cd server
PYTHONUTF8=1 uv run --group loadtest locust -f loadtest/locustfile.py --host http://127.0.0.1:8000
```

浏览器打开 <http://localhost:8089>,填 **并发用户数(Users)** 与 **生成速率(Spawn rate)**,Start 即压。

### 3.2 Headless(命令行 / CI)

```bash
cd server
PYTHONUTF8=1 uv run --group loadtest locust -f loadtest/locustfile.py --host http://127.0.0.1:8000 \
    --headless --users 200 --spawn-rate 20 --run-time 5m --csv=loadtest/result
```

- `--users`:峰值并发;**首次 spawn 会先预注册账号**(见下),耐心等日志。
- `--csv=loadtest/result`:产出 `result_stats.csv`(分接口聚合)、`result_stats_history.csv`(时间序列)、`result_failures.csv`(失败明细)。
- 产出 CSV 后可用 <https://github.com/matthieu-trouve/locust_csv_plotter> 等画图。

### 3.3 分布式(打高并发用)

```bash
# master
uv run --group loadtest locust -f loadtest/locustfile.py --host http://127.0.0.1:8000 --master

# 每台 worker
uv run --group loadtest locust -f loadtest/locustfile.py --host http://127.0.0.1:8000 --worker --master-host <master_ip>
```

多 worker 各自预注册 `LOADTEST_POOL_SIZE` 个账号(用户名含 pid,不冲突)。

## 4. 用户画像与配比

| 画像 | 类 | 行为 | 默认权重 |
|---|---|---|---|
| **静态素材** | `AnonymousAssetUser` | 作物图/节气图 PNG、`/v1/art/version`、`/v1/art/manifest`、`/docs` | 40 |
| **动态只读** | `PlayerReadUser` | `me` / `calendar/current` / `farm/state` / `shop/state` / `pest/state` / `quests` / `achievements` / `social/friends` / `storage` / `inventory` | 40 |
| **写操作** | `FarmerUser` | 买种子 → 播种 → 浇水 → 收割 → 铲除 → 除杂草 → 出售 | 10 |
| **注册/登录** | `AuthUser` | 登录(成功 + 错误密码失败路径) | 5 |
| **WebSocket** | `WsUser` | 长连接 + `ping`/`pong` + 节气推送 | 5 |

权重 = 各画像被 spawn 的比例(50 用户 → 静态约 20、只读约 20、写约 5 …)。

## 5. 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `LOADTEST_HOST` | `http://127.0.0.1:8000` | 目标地址(等价 `--host`,优先用 CLI) |
| `LOADTEST_POOL_SIZE` | `100` | 预注册账号数(0 = 不预注册,全靠现场注册) |
| `LOADTEST_PASSWORD` | `loadtest123` | 压测账号密码 |
| `LOADTEST_SEED_PREFIX` | `lt` | 压测账号名前缀(便于事后清理) |
| `LOADTEST_W_STATIC` | `40` | 静态素材画像权重 |
| `LOADTEST_W_READ` | `40` | 动态只读画像权重 |
| `LOADTEST_W_WRITE` | `10` | 写操作画像权重 |
| `LOADTEST_W_AUTH` | `5` | 注册/登录画像权重 |
| `LOADTEST_W_WS` | `5` | WebSocket 画像权重 |

例:只压读接口,不要写操作:

```bash
LOADTEST_W_WRITE=0 LOADTEST_W_AUTH=0 LOADTEST_W_WS=0 \
  uv run --group loadtest locust -f loadtest/locustfile.py --host http://127.0.0.1:8000 --headless -u 300 -r 30 -t 3m
```

## 6. 怎么看结果

Web UI 的 **Statistics** 表按接口聚合,关键列:

- **Request Count / Failures**:失败只看 `5xx`、网络错误、`401`(有效 token 不应出现)。`400/403/404` 带 `error_code` 的业务拒绝已被归为成功,不污染失败率。
- **Average / P95 / Max**:延迟分位。热点先看 `GET /v1/farm/state`、`GET /v1/player/me`、`GET /v1/art/version`。
- **RPS**:吞吐。SQLite 单机写并发是天然瓶颈,`FarmerUser` 的写接口会先到顶(报 `database is locked` → 500)。

压测结束时(或 headless 结束)会在控制台打印**业务拒绝统计**(各 `error_code` 计数),用于确认"写接口确实在按预期产生玩法级拒绝"而非服务崩溃。

## 7. 已知限制 / 预期现象

1. **SQLite 写并发差**:开发库是 SQLite,写操作并发到一定程度会 `database is locked`(表现为 5xx)。这是 SQLite 特性,不是 bug —— 生产切 PostgreSQL 后重测即可。压测写接口时建议降低写画像权重,或只压读。
2. **预注册耗时**:`LOADTEST_POOL_SIZE=100` 顺序注册约 10s(PBKDF2 10 万次迭代),`--headless` 首跑请耐心。账号随机命名,不会重名冲突;每次压测都会新增一批账号(测试后可用管理后台或重开一次性库清理)。
3. **业务拒绝会大量出现**:`FarmerUser` 的 `sow/harvest/buy/sell` 因节气窗、金币、库存、成熟度等,多数请求会返回 `CROP_NOT_AVAILABLE / NOT_ENOUGH_COINS / CROP_NOT_MATURE` 等 —— 这正是压测写路径的目的(打写锁与账本),已归为成功并单独统计。
4. **WS 画像**:需要 `websocket-client`(已含在 loadtest group);连不上时 WS 操作记为失败,不影响其他画像。
5. **AI 接口未纳入**:`/v1/ai/chat` 会转发到外部大模型(慢 + 计费),默认不压;如需压,自行加一个 `@task` 即可。

## 8. 清理压测账号

压测账号名前缀默认 `lt_`(可经 `LOADTEST_SEED_PREFIX` 改)。对一次性演示库直接删库重启即可;对长期库,可用管理后台按名字筛选删除,或直接保留(不影响正常玩家)。
