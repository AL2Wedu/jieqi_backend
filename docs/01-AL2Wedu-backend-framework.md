# 后端总体框架(节气种田 · 教育+AI+模拟经营)

> 说明:本文档描述该项目的后端技术方案。配套文档:`02-数据库Schema设计.md`(数据库)、`03-API契约与扩展性设计.md`(API)。
> 版本:v1.3

---

## 1. 系统定位

本项目是一款面向未成年人的**教育类模拟经营游戏**:玩家经营农场,通过种植作物体验 24 节气传统文化。客户端使用 Godot 4,后端为独立部署的 API 服务(部署于服务器,通过 API 输出数据)。当前阶段为 demo,登录采用**名字 + 密码**,不接入第三方登录。

## 2. 总体架构

```
┌─────────────────────────────────────────────┐
│  Godot 4 客户端 (前端)                        │
│  HTTP(REST) + WebSocket(事件推送) + JSON     │
└──────────────────┬──────────────────────────┘
                   │
┌──────────────────▼──────────────────────────┐
│  API 网关层 (FastAPI, /v1, OpenAPI 契约)      │
│  JWT 鉴权 · 限流 · 请求校验 · 统一错误码       │
└──┬──────┬──────┬──────┬──────┬──────┬───────┘
   │      │      │      │      │      │
┌──▼─┐ ┌─▼───┐ ┌▼────┐ ┌▼────┐ ┌▼────┐ ┌▼─────┐
│auth│ │player│ │farm │ │calendar│ │content│ │shop/ │
│账号│ │玩家/ │ │农场 │ │节气服务│ │内容/  │ │inven │
│登录│ │资产/ │ │地块 │ │(轮转时钟)│ │题库   │ │商店  │
└──┬─┘ │背包  │ │作物 │ └──┬───┘ └──┬───┘ └──┬───┘
   │   └──┬───┘ └──┬──┘      │        │        │
   │      │        │         │        │        │
┌──▼──────▼────────▼─────────▼────────▼────────▼──┐
│               AI 网关 (ai-service)                │
│  意图识别 → RAG检索(pgvector) → LLM → 审核 → 回复  │
│  会话管理 · 缓存 · 限流 · 未成年人输出审核          │
└────────────────────┬────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────┐
│  数据层                                          │
│  PostgreSQL(+pgvector 知识库) · Redis(会话/排行) │
│  对象存储 OSS(头像/音频/素材) · 定时任务(节气广播) │
└─────────────────────────────────────────────────┘
```

后端为**模块化单体**(一个 FastAPI 应用,按业务域划分模块),模块边界清晰,后续可按需拆分微服务。

## 3. 核心领域设计

### 3.1 节气轮转时钟

- 节气**每 5 分钟切换一轮**(默认 300 秒,可由 `term_config.duration_seconds` 调整),24 节气约 2 小时完成一个完整循环。
- 当前节气由服务端游戏时钟**公式计算**(`epoch + time_scale + duration` 取模),不需要年份日历表,不依赖定时改库。
- 服务端为权威时钟;每轮切换时通过 WebSocket 广播 `solar_term_change` 事件。
- 时钟支持倍速与暂停(运营通过 `game_clock` / `game_config` 配置);预留真实日期模式,切换不改架构。

### 3.2 节气驱动的内容

作物、知识卡片、题目、任务均以 `term_index`(1–24)为业务键。作物播种窗口采用**精细节气窗**(term 类型)+ **grace 宽限期**(错过可延后 N 轮)。定价为**静态配置**(写死在配置表字段),通过调试端口热改,不做节气浮动价。

### 3.3 教学进度

- **学习不绑定节气轮转**:已解锁的节气随时可学。
- **答题与活动绑定当前轮转节气**。
- 进度由 `players.unlocked_term_index` 与 `term_progress` 表驱动:完成本节气的卡片学习与测验后,解锁下一节气。

## 4. 模块划分

| 模块 | 职责 | 优先级 |
|---|---|---|
| auth | 注册/登录(demo:名字+密码)、JWT | P0 |
| player | 玩家档案、资产摘要、背包、头衔 | P0 |
| calendar | 节气服务:轮转时钟、当前节气、倒计时、节气轮换广播 | P0 |
| farm | 地块、作物实例、播种/浇水/收获、加成结算 | P0 |
| shop/inventory | 商店(静态价,调试可改)、道具目录、背包、购买/使用 | P0 |
| content | 节气知识(卡片/农谚/诗词/习俗)、题库、运营 CMS 接口 | P0(基础)/P2(CMS) |
| ai | 对话 NPC、RAG 知识问答、每日一题、个性化推荐、审核 | P1 |
| social | 排行榜、好友互助、班级/学校组织 | P1/P2 |
| event | 节气主题活动、任务、成就 | P2 |

## 5. 关键技术设计

### 5.1 节气时钟服务

- 当前节气 = `((now - epoch) × time_scale / duration_seconds) % 24 + 1`(暂停期间时钟冻结)。
- `game_clock` 单行表保存 epoch、time_scale、暂停点;`term_config` 24 行定义节气名与停留时长。
- 切换广播:`{"type":"solar_term_change","term":"白露","term_index":15,"cycle":42}`,由推送网关每轮发送。
- 接口:`GET /v1/calendar/current` 返回当前节气、本轮剩余秒、轮次 cycle、内容入口。
- 客户端兜底:WebSocket 断开时轮询(每 5 分钟)拉取状态,保证节气切换不丢。
- 玩法联动:播种窗口 `sow_window` 按节气轮次判定,支持宽限期。

### 5.2 数据模型

> 完整 DDL 见 `02-数据库Schema设计.md`(v0.3:UUID 主键、轮转节气时钟、静态定价、道具/头衔/成就表)

核心表:users(名字+密码,记录 IP)/ players(等级/学识值/钱财/佩戴头衔)/ farms+plots(农田 list)/ crops(精细节气窗+宽限期)/ crop_instances(每株种植状态机)/ term_config+game_clock(轮转时钟)/ items+user_items(道具背包)/ knowledge_items+quiz_questions+term_progress(教育内容与进度)/ ai_sessions+ai_messages(审核留痕)

要点:
- 播种窗口 `sow_window` 按精细节气窗表达,可配宽限期。
- 奖励结算在**服务端**执行(加成按播种快照结算),客户端只展示;定价为静态配置,调试端口可热改。

### 5.3 AI 教育链路

```
玩家提问 ─→ 意图识别(闲聊/知识问答/游戏帮助)
              │
              ├─ 知识问答 → 向量检索节气知识库(top-k, bge-m3 → pgvector)
              ├─ 拼接 prompt(角色:节气小老师 + 检索片段 + 会话上下文)
              ├─ LLM(DeepSeek / 通义千问 / 智谱,国内直连)
              ├─ 审核管线(敏感词 + 云内容安全 API)
              └─ 结构化回复 → 客户端
```

- 知识库内容整理自古籍/百科,标注来源;同一份语料同时用于游戏卡片与 RAG 检索。
- 成本控制:相似问题结果缓存(Redis)、每玩家限流、会话窗口只保留最近 N 轮。
- 未成年人安全:AI 输出全链路过审并留痕(`ai_messages.review_result`)。
- LLM provider 采用可插拔配置,当前接入一家,后续可切换。

### 5.4 实时推送与离线容忍

- Godot 内置 `WebSocketPeer`,协议 JSON。
- 事件:`solar_term_change` / `crop_ready` / `inventory_change` / `coins_change` / `quest_progress` / `broadcast`。
- 离线可玩:客户端本地存档 + 上线增量合并(事件流),适用于学校网络不稳定的场景。

### 5.5 API 契约

契约先行,前后端按 OpenAPI 并行开发:

- `POST /v1/auth/register | /login`(demo:名字+密码)
- `GET /v1/player/me`
- `GET /v1/calendar/current`(当前节气 + 倒计时)
- `GET /v1/farm/state` · `POST /v1/farm/plots/{id}/sow` · `POST /v1/farm/plots/{id}/harvest`
- `GET /v1/player/inventory` · `POST /v1/player/inventory/{item_id}/use`
- `GET /v1/shop/items` · `POST /v1/shop/items/{item_id}/buy`
- `GET /v1/content/terms/{term}/knowledge` · `GET /v1/content/quiz/today`
- `POST /v1/ai/chat`(会话) · `GET /v1/rankings`
- `WS /v1/ws`(事件订阅)

完整约定见 `03-API契约与扩展性设计.md`。

## 6. 技术选型

| 层 | 选型 | 说明 |
|---|---|---|
| API 框架 | Python **FastAPI** | AI 生态完整、开发效率高;自动生成 OpenAPI |
| 数据库 | **PostgreSQL + pgvector** | 关系数据 + 向量检索统一存储 |
| 缓存/会话 | **Redis** | 会话、排行榜、AI 缓存、pub/sub |
| 对象存储 | 阿里云 OSS / 腾讯 COS | 头像、节气语音、素材 |
| LLM | DeepSeek / 通义千问 / 智谱 | 国内可用、直连 |
| 向量模型 | bge-m3 / text-embedding-v3 | 中文效果良好 |
| 部署 | Docker + 阿里云/腾讯云轻量服务器 | 域名需 ICP 备案 |
| 认证 | 名字+密码(demo);正式版扩展手机号/班级 | 快速起步 |

## 7. 仓库结构

```
repo/
├── client/                  # Godot 4.x 工程(前端)
├── server/                  # 后端
│   ├── app/
│   │   ├── api/             # 路由 v1(auth/player/farm/calendar/content/ai/social/shop)
│   │   ├── services/        # 业务逻辑
│   │   ├── models/          # SQLAlchemy 模型
│   │   ├── schemas/         # Pydantic(API 契约,导出 OpenAPI)
│   │   ├── core/            # 配置/中间件/JWT/日志/限流
│   │   └── ws/              # WebSocket 事件总线
│   ├── data/                # 种子数据 JSON:节气/作物/知识库/题库/道具
│   ├── tests/
│   └── pyproject.toml       # uv 管理依赖
├── docs/                    # 设计文档(本框架 + OpenAPI 契约)
└── README.md
```

## 8. 路线图

- **P0 · MVP 可玩闭环(2–3 周)**:auth + player + farm + calendar + 6 种作物×节气窗 + 知识卡片(无 AI)。验收:客户端完成"播种→节气变化→收获→看节气知识"完整闭环。
- **P1 · AI 教育闭环(4–6 周)**:ai-service(对话 NPC + RAG 问答 + 每日一题)+ 节气事件推送 + 排行榜。
- **P2 · 教育场景化**:班级/学校组织、教师后台、主题活动运营、CMS、埋点分析(教育类定位,不做防沉迷)。

## 9. 合规说明

1. **未成年人保护**:按教育类应用定位,暂不做防沉迷;个人信息最小化收集(昵称/真名分离);若未来以"网络游戏"形态发行(需版号),防沉迷为硬性要求。
2. **AI 生成内容审核**:面向未成年人的输出必须过审,全链路留痕。
3. **内容版权**:节气知识整理自古籍/百科,标注来源,不搬运有版权的书籍。
4. **备案**:域名需 ICP 备案;正式发行需版号(训练营阶段使用测试版)。

## 10. 后端实施步骤

1. 仓库初始化,建立 `server/` 骨架(FastAPI + uv + SQLite 起步,后换 PostgreSQL)。
2. 落 `term_config`(24 行)与首批作物种子数据(6 种,精细节气窗 + 宽限期)。
3. 定 API 契约,导出 OpenAPI,同步给 Godot 端。
4. 实现 auth(demo 名字+密码)、player、farm 状态接口。
5. 实现 calendar 服务(轮转时钟公式 + 节气切换广播)。
6. 实现 shop/inventory(道具购买/使用,账本记录)。
7. 实现 ai-service:接入一家 LLM + 简单 RAG,跑通问答闭环。
8. 每步配置接口测试,README 写明启动方式。
