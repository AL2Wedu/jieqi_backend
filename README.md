# jieqi_backend(节气种田 · 后端)

教育 + AI + 模拟经营游戏的后端仓库(元创S营项目)。客户端使用 Godot 4,后端为独立部署的 API 服务。

## 技术栈

- FastAPI + SQLAlchemy 2 + SQLite(开发)/ PostgreSQL+pgvector(生产)
- Redis(缓存/会话,规划中)
- 大模型 LLM(DeepSeek / 通义千问 / 智谱)+ RAG 知识库(规划中)

## 设计文档

- [后端总体框架](docs/01-AL2Wedu-backend-framework.md)
- [数据库 Schema 说明](docs/02-数据库Schema设计.md)
- [API 契约与扩展性规范](docs/03-API契约与扩展性设计.md)

## 开发

### 环境要求

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)(依赖管理;国内网络可用 `uv sync --default-index https://mirrors.aliyun.com/pypi/simple/`)

### 安装与启动

```bash
cd server
uv sync                     # 安装依赖(国内镜像见上)
cp .env.example .env        # 按需修改配置

uv run uvicorn app.main:app --reload    # 启动开发服务,默认 http://127.0.0.1:8000
```

启动时自动建表 + 导入种子数据(24 节气 / 6 作物 / 9 道具),幂等。

### 测试

```bash
uv run python -m pytest -v
```

覆盖完整闭环:注册 → 登录 → 日历 → 节气推进 → 商店 → 买种子 → 播种(节气窗校验)→ 浇水 → 收获 → 道具使用 → 调试接口。

### 目录结构

```
server/
├── app/
│   ├── api/            # v1 路由(auth/player/calendar/farm/shop/debug)+ WS
│   ├── core/           # 配置 / 安全(JWT+PBKDF2) / 错误 / 依赖
│   ├── models/         # SQLAlchemy 模型(P0 全部表)
│   ├── schemas/        # Pydantic 请求模型
│   ├── services/       # 业务逻辑(calendar/auth/player/farm/inventory/shop)
│   ├── ws/             # WebSocket 连接管理与节气广播
│   └── main.py         # 应用入口
├── data/               # 种子数据 JSON
├── scripts/            # seed 脚本
└── tests/              # pytest 冒烟测试
```

### 调试接口(demo 专用)

由 `DEBUG_ENABLED` 控制,上线必须关闭:

| 接口 | 用途 |
|---|---|
| `POST /v1/debug/config` | 热改 game_config(价格、节气时长、活动开关) |
| `POST /v1/debug/term/advance` | 手动推进节气(测试播种窗/事件) |
| `POST /v1/debug/grow` | 催熟指定地块作物(测试收获结算) |

### 备注

- 节气为**轮转制**:默认每节气 300 秒(5 分钟),24 节气 ≈ 2 小时一轮,由服务端时钟公式计算,切换时 WebSocket 广播。
- 在 Hermes 等带自定义 PYTHONPATH 的环境下运行,请先 `env -u PYTHONPATH` 再执行命令,避免依赖被环境污染。
