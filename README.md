# jieqi_backend(节气种田 · 后端)

教育 + AI + 模拟经营游戏的后端仓库(元创S营项目)。客户端使用 Godot 4,后端为独立部署的 API 服务。

---

# 1. 功能总览(实现状态)

> 状态标记:✅ 已实现 · ⚠️ 部分实现 · ❌ 未实现 · 📋 计划中
> 当前为 **P0 demo 阶段**,核心玩法闭环已跑通,教育内容与 AI 为 P1。

## 1.1 已实现 ✅

### 账号与玩家
- **注册 / 登录**:名字 + 密码(demo 形态),PBKDF2 密码哈希,JWT 签发(7 天)
- **IP 记录**:注册 IP / 最近登录 IP(`users.register_ip / last_login_ip`)
- **封禁 / 解封**:管理后台操作,封禁后无法登录
- **玩家资产**:等级 / 经验 / 金币 / 农场(4×5=20 地块)/ 背包

### 节气轮转时钟(核心)
- **24 节气轮转**:每节气默认 300 秒(可配置),约 2 小时一个完整循环,**纯公式计算,无日历表**
- **时钟控制**:倍速 / 暂停 / 纪元重置(管理后台可操作)
- **节气切换广播**:WebSocket 推送 `solar_term_change` 事件(单进程有效,见 ⚠️)
- **调试推进**:`/v1/debug/term/advance` 手动切换节气

### 农场玩法(服务器权威)
- **播种**:每格独立选择作物,校验节气窗(精细节气窗 + grace 宽限期)+ 消耗对应种子道具
- **浇水**:`water_level` 置 100(衰减机制未实现,见 ⚠️)
- **收获结算**:产量 × 单价 → 金币,走账本(`coin_transactions`);丰收记录保留,可再播种
- **生长状态**:阶段(苗期/生长期/成熟)与进度由**服务器时间权威推导**,客户端只展示
- **全服种植状态**:管理后台实时查看每株植物的阶段/进度/水分/播种节气(🌱 种植状态板块)

### 作物 / 道具 / 商店
- **6 种作物**:水稻/小麦/大豆/白菜/番茄/菊花(节气窗/生长时长/产量/单价全配置化)
- **9 种道具**:6 种子 + 肥料(生长加速 50%)+ 水壶 + 节气卡;效果用 JSONB 定义,**加道具不改代码**
- **商店**:商品列表、购买(扣金币 + 道具账本 `item_transactions`)
- **道具使用**:按 `effect.type` 分发(肥料加速 / 水壶浇水)
- **美术资产**:每作物 4 张 SVG(种子 + 苗期/生长期/成熟),路径存服务器;新建作物自动生成占位图

### 任务 / 社交 / 成就 / AI
- **任务系统**:5 个种子任务,自动跟踪(无需接取),进度由服务器实时计算,奖励走账本
- **社交**:好友申请 / 接受 / 拒绝 / 列表 / 删除
- **成就(通用版)**:配置驱动(通用条件格式),自动达成 + 领奖;**加新成就 = 配置加一行**
- **AI 大模型转发**:OpenAI 兼容接口(`POST /v1/ai/chat` 透传),支持 DeepSeek/通义/智谱等任意兼容上游
- **AI 用量追踪**:每用户每次请求的 tokens 自动记录(按玩家×模型×日聚合),玩家可查自己的,管理端可看全服
- **管理后台 AI 设置**:服务器地址 / API Key(脱敏)/ 模型 / 开关 + 一键测试连接 + 每用户用量表

### 管理后台(/admin)
- **8 大板块**:仪表盘 / 用户列表 / 全局配置(`game_config` 热更新 + 环境变量只读打码)/ 作物管理(新增植物可自动建种子)/ 种植状态 / 道具管理 / 定价 / 节气设置
- **底部 PowerShell 终端**:xterm.js + ConPTY,可启动/中断后端服务、执行任意命令
- **安全**:独立 admin JWT(2 小时过期)、`ADMIN_ENABLED` 总开关

### 工程基础
- **API 规范**:统一响应信封 `{code,message,data}`、分页信封、稳定错误码、OpenAPI 自动文档(`/docs`)
- **测试**:10 个 pytest 用例全绿(注册→买种子→播种→浇水→催熟→收获 全闭环 + 管理后台全链路)
- **种子数据幂等**:24 节气 / 6 作物 / 9 道具,启动自动导入,可重建

## 1.2 部分实现 ⚠️

| 功能 | 现状 | 缺口 |
|---|---|---|
| 节气卡道具 | 商店可购买 | `term_lock`(锁定节气)效果未实现,使用返回"功能开发中" |
| 水壶/浇水 | 可设置为 100 | 水分**随时间衰减**机制未实现(不浇水不影响生长) |
| 游戏时钟暂停 | 公式与后台均支持 `paused` | 未与玩法联动(如节气卡冻结时钟) |
| 管理终端 | Windows 完整可用 | Linux 生产环境无 ConPTY,自动降级为不可用 |
| 多 worker 部署 | 单进程正常 | 节气广播为进程内任务,多 worker 会重复推送(需 Redis pub/sub) |

## 1.3 未实现 ❌(表已建 / 接口未做)

- **头衔佩戴**:`titles` / `user_titles` 表已建,佩戴/展示逻辑未做(成就解锁头衔的联动未接)
- **教育内容**:知识卡片(`knowledge_items`)/ 每日一题(`quiz_questions`)无数据、无接口
- **AI 教育链路**:LLM 转发已通,但 pgvector RAG 知识库检索、AI 输出审核 + 留痕管线(`ai_messages`)未做
- **学习进度**:`term_progress` / `user_quiz_records` 表已建,解锁逻辑未实现
- **排行榜**、**活动任务**(quests 的 story 类)、**埋点分析**(`event_logs` / `play_sessions` 未采集)
- **数据库迁移链**:Alembic 未初始化(开发用 `create_all` 建表)
- **正式部署落地**:PostgreSQL 实机、Nginx、systemd 未实际配置(部署指南已写好,见第 7 节)

## 1.4 计划中 📋(路线图)

### P1(下一步)
- 教育内容模块:节气知识卡片 + 每日一题 + "学完本节气 → 解锁下一节气"教学闭环
- AI 教育链路:pgvector 检索知识库 + 输出过审 + 全链路留痕(未成年人合规);AI 流式输出(SSE)
- 头衔佩戴联动(成就解锁)、排行榜;Redis pub/sub 改造节气广播;Alembic 迁移链

### P2(后续)
- 班级 / 学校组织、教师后台、活动运营 CMS、埋点分析
- 正式版登录扩展:手机号(家长绑定)、昵称/真名分离
- 应季溢价定价(若做"应季 vs 反季"教育玩法,再引入节气价格系数)

---

# 2. 技术栈

| 层 | 选型 |
|---|---|
| Web 框架 | FastAPI |
| ORM | SQLAlchemy 2.0(开发 SQLite / 生产 PostgreSQL 16+) |
| 校验 | Pydantic v2 |
| 认证 | JWT(HS256):玩家 token + 管理员 token 双体系 |
| 依赖管理 | uv(uv.lock 锁定) |
| 管理后台终端 | xterm.js + pywinpty(ConPTY PowerShell) |
| 大模型(规划) | DeepSeek / 通义千问 / 智谱 + RAG |

# 3. 设计文档

- [API 文档(完整端点/请求响应/错误码/示例)](API.md)
- [后端总体框架](docs/01-AL2Wedu-backend-framework.md)
- [数据库 Schema 说明](docs/02-数据库Schema设计.md)
- [API 契约与扩展性规范](docs/03-API契约与扩展性设计.md)

# 4. 目录结构

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

# 5. 本地开发

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

# 6. 管理后台(/admin)

- 访问:启动服务后浏览器打开 `http://127.0.0.1:8000/admin`
- 账号:`.env` 中的 `ADMIN_USERNAME` / `ADMIN_PASSWORD`(开发默认 `admin` / `admin123`,上线必须修改)
- 板块:
  - **仪表盘**:服务状态 / 当前节气 / 用户数 / 金币总量
  - **用户列表**:分页、封禁/解封(封禁后无法登录)
  - **全局配置**:`game_config` KV 热更新(改配置即时生效,不发版)+ 系统环境变量只读(敏感值打码)
  - **作物管理**:新增植物(可自动创建种子道具)、编辑节气窗/生长时长/产量/价格/美术、软删除
  - **种植状态**:全服每株植物的服务器权威实时状态(阶段/进度/水分/播种节气)
  - **道具管理**:增删改,effect JSON 定义效果
  - **定价**:作物售价与道具价格内联编辑
  - **节气设置**:24 节气时长、游戏时钟倍速/暂停/纪元重置
  - **底部终端栏**:内嵌 PowerShell(xterm.js + ConPTY),可启动/中断后端服务、执行任意命令
- 安全:`ADMIN_ENABLED=false` 整体关闭;admin token 2 小时过期;终端为最高权限,**生产环境禁止开放**

# 7. 部署指南

## 7.1 架构总览

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

## 7.2 快速演示部署(单机直跑)

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

## 7.3 正式部署(生产)

### 7.3.1 数据库:PostgreSQL 16+

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

### 7.3.2 环境变量清单

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

### 7.3.3 Nginx 反向代理 + HTTPS

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

### 7.3.4 多 worker 与节气广播(重要)

- 生产可 `--workers 4` 提升并发;
- ⚠️ **节气切换广播任务当前为进程内任务**,多 worker 下每个 worker 各广播一份,会导致客户端收到重复事件;
- 解决方案(规划中,P1):广播改用 **Redis pub/sub**(`jieqi:term_change` 频道),各 worker 订阅、推送自己的 WS 连接。

### 7.3.5 安全清单

- [ ] `JWT_SECRET` 强随机,不落代码仓库
- [ ] `ADMIN_ENABLED=false` 或管理后台仅内网/跳板机可达
- [ ] `DEBUG_ENABLED=false`
- [ ] 云安全组/防火墙只放行 80/443(及 SSH)
- [ ] 管理终端是最高权限,公网**禁止**开放
- [ ] 未成年人合规:AI 输出审核 + 留痕(见设计文档)

### 7.3.6 数据备份与恢复

```bash
# PostgreSQL 每日备份(crontab)
0 3 * * * pg_dump -U jieqi -d jieqi | gzip > /backup/jieqi_$(date +\%F).sql.gz

# 恢复
gunzip -c /backup/jieqi_2026-08-14.sql.gz | psql -U jieqi -d jieqi
```

- 配置类数据(节气/作物/道具)在 `server/data/*.json`,**幂等可重建**,不依赖备份;
- 玩家资产(金币/作物实例)是账本制(`coin_transactions`/`item_transactions`),余额可对账重建。

### 7.3.7 上线检查清单

- [ ] PostgreSQL 连接串正确,迁移已执行
- [ ] 环境变量全部注入,无默认弱密钥
- [ ] `DEBUG_ENABLED=false`、`ADMIN_ENABLED=false`
- [ ] Nginx HTTPS 生效,WS 升级正常
- [ ] systemd 服务 `Restart=always` 已启用
- [ ] 备份定时任务已配置
- [ ] 域名 ICP 备案完成(国内服务器)

# 8. 备注

- 开发默认账号:`admin / admin123`(仅本地开发,生产必须修改)
- 测试库与开发库分离:测试用 `test.db`(conftest 自动重建),开发用 `dev.db`
- Windows 开发注意:终端桥依赖 pywinpty(仅 Windows 提供 ConPTY);Linux 生产环境管理终端自动降级为不可用,不影响业务接口
