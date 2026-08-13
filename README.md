# jieqi_backend(节气种田 · 后端)

教育 + AI + 模拟经营游戏的后端仓库(元创S营项目)。客户端使用 Godot 4,后端为独立部署的 API 服务。

## 技术栈

| 层 | 选型 |
|---|---|
| Web 框架 | FastAPI |
| ORM | SQLAlchemy 2.0(开发 SQLite / 生产 PostgreSQL 16+) |
| 校验 | Pydantic v2 |
| 认证 | JWT(HS256):玩家 token + 管理员 token 双体系 |
| 依赖管理 | uv(uv.lock 锁定) |
| 管理后台终端 | xterm.js + pywinpty(ConPTY PowerShell) |
| 大模型(规划) | DeepSeek / 通义千问 / 智谱 + RAG |

## 设计文档

- [后端总体框架](docs/01-AL2Wedu-backend-framework.md)
- [数据库 Schema 说明](docs/02-数据库Schema设计.md)
- [API 契约与扩展性规范](docs/03-API契约与扩展性设计.md)

## 目录结构

```
server/
├── pyproject.toml        # uv 项目定义
├── uv.lock               # 依赖锁定
├── .env(.example)        # 环境配置
├── app/
│   ├── main.py           # 入口:FastAPI 实例 / CORS / 异常处理 / lifespan(建表+seed+节气广播)
│   ├── core/             # 横切基础设施(config/db/security/errors/deps/svg_art)
│   ├── models/           # SQLAlchemy 模型(13 张表)
│   ├── schemas/          # Pydantic 请求模型
│   ├── services/         # 业务逻辑(calendar/auth/player/farm/inventory/shop/admin)
│   ├── api/              # 路由层(auth/player/calendar/farm/shop/debug/admin + WS)
│   ├── ws/               # WebSocket:节气广播 + ConPTY 终端桥
│   └── static/           # 管理后台单页 admin.html + 植物美术 SVG
├── data/                 # 种子数据(24 节气 / 6 作物 / 9 道具)
├── scripts/seed.py       # 幂等种子导入(启动自动执行)
└── tests/                # pytest(10 用例)
```

## 本地开发

**环境要求**:Python 3.11+、uv

```bash
cd server
uv sync --default-index https://mirrors.aliyun.com/pypi/simple/   # 安装依赖(国内镜像)
cp .env.example .env        # 按需修改(默认值可直接开发)

uv run uvicorn app.main:app --reload        # 启动开发服务器(端口 8000)
uv run python -m pytest -v                  # 跑测试
```

> 注:若在 Hermes 等带 `PYTHONPATH` 污染的环境运行,命令前加 `env -u PYTHONPATH`。

**管理后台**:http://127.0.0.1:8000/admin(账号见 `.env` 的 `ADMIN_USERNAME/ADMIN_PASSWORD`,开发默认 `admin/admin123`)

**调试接口**(`DEBUG_ENABLED=true` 时可用,均需玩家登录):
- `POST /v1/debug/config` — 热改全局配置(价格/节气时长等,不发版)
- `POST /v1/debug/term/advance` — 手动推进节气(测播种窗/事件)
- `POST /v1/debug/grow` — 催熟指定地块作物(测收获)

---

# 部署指南

## 1. 架构总览

```
客户端(Godot / 浏览器)
        │ HTTPS
        ▼
    Nginx 反向代理    ← TLS 证书 / 静态资源缓存 / 限流 / WebSocket 升级
        │
        ▼
  uvicorn(FastAPI)   ← systemd 托管,多 worker
        │
   ┌────┼─────┐
   ▼    ▼     ▼
PostgreSQL  Redis    对象存储
 16+    (缓存/广播)  (美术大图,后续)
```

## 2. 快速演示部署(单机直跑)

适合内网/演示环境,一条命令起服务:

```bash
cd /opt/jieqi_backend/server
uv sync --default-index https://mirrors.aliyun.com/pypi/simple/
cp .env.example .env
# 编辑 .env:改 JWT_SECRET(强随机)和 ADMIN_PASSWORD
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

以 systemd 方式常驻(推荐):

```ini
# /etc/systemd/system/jieqi.service
[Unit]
Description=jieqi_backend API server
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/jieqi_backend/server
ExecStart=/opt/jieqi_backend/server/.venv/Scripts/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=3
Environment=PYTHONPATH=

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now jieqi
```

## 3. 正式部署(生产)

### 3.1 数据库:PostgreSQL 16+

```bash
# 云服务器上(以 Ubuntu 为例)
sudo apt install postgresql-16
sudo -u postgres psql -c "CREATE USER jieqi WITH PASSWORD '强密码';"
sudo -u postgres psql -c "CREATE DATABASE jieqi OWNER jieqi;"
```

`.env` 配置:

```
DATABASE_URL=postgresql://jieqi:强密码@127.0.0.1:5432/jieqi
```

模型已按 PostgreSQL 友好设计(UUID 原生 / JSON / INET),SQLite → PG 切换只需改连接串。

**数据库迁移**:开发阶段用 `create_all`(启动自动建表 + 幂等种子导入);上线前补 Alembic:

```bash
uv add alembic
uv run alembic init alembic
# alembic/env.py 指向 app.core.db 的 Base.metadata,autogenerate 生成迁移
uv run alembic revision --autogenerate -m "init"
uv run alembic upgrade head
```

### 3.2 环境变量清单

| 变量 | 默认 | 生产要求 |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./dev.db` | PostgreSQL 连接串 |
| `JWT_SECRET` | 开发占位 | **强随机**(`openssl rand -hex 32`) |
| `JWT_EXPIRE_DAYS` | 7 | 按需 |
| `DEBUG_ENABLED` | true | **false**(关闭调试接口) |
| `ADMIN_ENABLED` | true | **false 或仅内网** |
| `ADMIN_USERNAME` | admin | 改 |
| `ADMIN_PASSWORD` | 空(必须设置) | **强密码** |
| `TERM_DEFAULT_DURATION` | 300 | 按玩法配置 |

### 3.3 Nginx 反向代理 + HTTPS

```nginx
# /etc/nginx/sites-available/jieqi
server {
    listen 80;
    server_name api.your-domain.com;
    return 301 https://$host$request_uri;   # HTTP → HTTPS
}

server {
    listen 443 ssl http2;
    server_name api.your-domain.com;

    ssl_certificate     /etc/letsencrypt/live/api.your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.your-domain.com/privkey.pem;

    client_max_body_size 20m;

    location /static/ {                      # 静态资源(管理后台/美术)
        proxy_pass http://127.0.0.1:8000;
        expires 7d;
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # WebSocket(节气广播 / 管理终端)
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 3600s;
    }
}
```

证书用 certbot 免费签发:`sudo certbot --nginx -d api.your-domain.com`

### 3.4 多 worker 与节气广播(重要)

- 生产可 `--workers 4` 提升并发;
- ⚠️ **节气切换广播任务当前为进程内任务**,多 worker 下每个 worker 各广播一份,会导致客户端收到重复事件;
- 解决方案(规划中,P1):广播改用 **Redis pub/sub**(`jieqi:term_change` 频道),各 worker 订阅、推送自己的 WS 连接。

### 3.5 安全清单

- [ ] `JWT_SECRET` 强随机,不落代码仓库
- [ ] `ADMIN_ENABLED=false` 或管理后台仅内网/跳板机可达
- [ ] `DEBUG_ENABLED=false`
- [ ] 云安全组/防火墙只放行 80/443(及 SSH)
- [ ] 管理终端是最高权限,公网**禁止**开放
- [ ] 未成年人合规:AI 输出审核 + 留痕(见设计文档)

### 3.6 数据备份与恢复

```bash
# PostgreSQL 每日备份(crontab)
0 3 * * * pg_dump -U jieqi -d jieqi | gzip > /backup/jieqi_$(date +\%F).sql.gz

# 恢复
gunzip -c /backup/jieqi_2026-08-14.sql.gz | psql -U jieqi -d jieqi
```

- 配置类数据(节气/作物/道具)在 `server/data/*.json`,**幂等可重建**,不依赖备份;
- 玩家资产(金币/作物实例)是账本制(`coin_transactions`/`item_transactions`),余额可对账重建。

### 3.7 上线检查清单

- [ ] PostgreSQL 连接串正确,迁移已执行
- [ ] 环境变量全部注入,无默认弱密钥
- [ ] `DEBUG_ENABLED=false`、`ADMIN_ENABLED=false`
- [ ] Nginx HTTPS 生效,WS 升级正常
- [ ] systemd 服务 `Restart=always` 已启用
- [ ] 备份定时任务已配置
- [ ] 域名 ICP 备案完成(国内服务器)

## 备注

- 开发默认账号:`admin / admin123`(仅本地开发,生产必须修改)
- 测试库与开发库分离:测试用 `test.db`(conftest 自动重建),开发用 `dev.db`
- Windows 开发注意:终端桥依赖 pywinpty(仅 Windows 提供 ConPTY);Linux 生产环境管理终端自动降级为不可用,不影响业务接口
