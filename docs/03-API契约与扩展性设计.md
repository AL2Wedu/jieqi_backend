# API 契约与扩展性规范(节气种田)

> 说明:本文档说明 API 设计规范与端点契约。配套文档:`01-AL2Wedu-backend-framework.md` / `02-数据库Schema设计.md`
> 版本:v0.2;FastAPI 实现后自动导出 OpenAPI 到 `docs/api/openapi.json`

---

## 1. 扩展性规范(团队约定)

1. **响应统一信封**:`{"code":0,"message":"ok","data":{...}}`,后续新增字段不影响旧客户端。
2. **列表统一分页信封**:`{"items":[],"page":1,"page_size":20,"total":42}`;新增筛选参数不破坏旧调用。
3. **版本路径前缀 `/v1/`**:破坏性变更开 `/v2/`;v1 只废弃不修改(3 个月过渡期)。
4. **只做加法不做减法**:新增字段/端点不破坏旧客户端;删字段或改语义属于破坏性变更,必须升版本。
5. **稳定字符串标识**:业务码(items.code)、事件名、error_code 使用字符串常量,不使用裸数字。
6. **契约先行**:后端先出 OpenAPI,客户端按契约并行开发。
7. **JSONB 兜底扩展**:开放结构配置(道具效果、加成、进度、payload)使用 JSONB。
8. **变更操作幂等**:支持 `Idempotency-Key` 头,网络重试不会重复扣道具/结算。
9. **配置热更新**:读 `game_config` 的接口每次请求实时取配置,运营改动不发版。
10. **错误码一经发布含义不变**:客户端按 `error_code` 字符串分支;新错误只新增,不复用。

## 2. 通用约定

| 项 | 约定 |
|---|---|
| Base URL | `https://api.<domain>/v1`(demo 阶段本机 `http://127.0.0.1:8000/v1`) |
| 认证 | `Authorization: Bearer <JWT>`(demo 登录即发) |
| 时间 | ISO8601 UTC(带 Z);客户端本地化展示 |
| ID | UUID |
| 分页 | `page`(从 1 起)、`page_size`(默认 20,最大 100) |
| 内容类型 | `application/json` |
| 客户端 IP | 注册/登录时服务端记录(`users.register_ip` / `last_login_ip`),用于审计、风控、限流 |

成功信封:

```json
{ "code": 0, "message": "ok", "data": { ... } }
```

列表信封:

```json
{ "code": 0, "message": "ok", "data": { "items": [], "page": 1, "page_size": 20, "total": 0 } }
```

错误信封:

```json
{ "code": 40001, "error_code": "NOT_ENOUGH_ITEM", "message": "种子不足" }
```

错误码段:`0` 成功 / `1xxx` 通用(参数校验、鉴权)/ `2xxx` 业务域 / `9xxx` 服务端异常。

## 3. 端点总览(v1)

| 域 | 方法 & 路径 | 说明 |
|---|---|---|
| auth | `POST /v1/auth/register` | 注册 `{name, password}` |
| | `POST /v1/auth/login` | 登录 → `{token, player}` |
| player | `GET /v1/player/me` | 档案 + 资产摘要(等级/学识值/钱财/头衔) |
| | `GET /v1/player/inventory` | 用户道具列表(分页,含数量) |
| | `POST /v1/player/inventory/{item_id}/use` | 使用道具 `{target?}`(按 effect.type 分发) |
| calendar | `GET /v1/calendar/current` | 当前节气 + 本轮剩余秒 + cycle + 内容入口 |
| farm | `GET /v1/farm/state` | 农田全量:plots 列表,每格独立状态 |
| | `POST /v1/farm/plots/{plot_id}/sow` | 播种 `{crop_id}`(消耗种子,校验节气窗) |
| | `POST /v1/farm/plots/{plot_id}/water` | 浇水 |
| | `POST /v1/farm/plots/{plot_id}/harvest` | 收获(服务端结算加成) |
| | `POST /v1/farm/plots/{plot_id}/clear` | 铲除 |
| shop | `GET /v1/shop/items` | 商品列表(静态价) |
| | `POST /v1/shop/items/{item_id}/buy` | 购买 `{quantity}`(扣钱+入包) |
| content | `GET /v1/content/terms/{term_index}/knowledge` | 节气知识卡片列表 |
| | `GET /v1/content/quiz/today` | 每日一题 |
| | `POST /v1/content/quiz/{question_id}/answer` | 答题 `{answer}` |
| ai | `POST /v1/ai/chat` | 会话式对话 `{session_id?, message}` |
| rank | `GET /v1/rankings` | 排行榜 `{type: level\|terms}` |
| ws | `WS /v1/ws` | 事件订阅(见 §6) |
| debug | `POST /v1/debug/config` · `POST /v1/debug/term/advance` | 调试端口:热改配置/推进节气(demo 专用,上线关闭) |

## 4. 扩展方式说明

**新增道具**(如"时光沙漏:作物立即成熟"):
1. `items` 配置新增一行:`{"code":"hourglass","effect":{"type":"instant_harvest"}}`。
2. 道具使用分发器按 `effect.type` 路由;新增 effect 类型 = 新增一个 handler。
3. 零迁移、零改动旧接口。

**新增玩法**(如"钓鱼"):
1. 新增 `GET/POST /v1/fishing/*` 独立域,旧接口零改动。
2. 需要持久化的状态新增表,或复用 `game_config` / JSONB。
3. 道具联动:鱼饵 = `items` 新增一行,复用 `use` 接口。

**新增事件类型**:事件注册表新增一个字符串,payload 只增字段。

**新增字段**(如玩家档案加"节气收藏数"):响应增加可选字段,旧客户端自动忽略。

**破坏性变更**(如登录协议更换):开 `/v2/auth/*`,v1 过渡期并存。

## 5. 关键响应示例(节选)

`GET /v1/farm/state`:

```json
{
  "code": 0, "message": "ok",
  "data": {
    "farm": { "id": "…", "name": "我的农场", "plot_count": 6 },
    "current_term": { "term_index": 6, "name": "谷雨", "cycle": 42, "remaining_sec": 128 },
    "plots": [
      { "idx": 1, "soil_quality": 1, "locked": false,
        "crop": { "crop_id": "…", "name": "水稻", "stage": 2, "growth_progress": 60,
                  "water_level": 80, "predicted_harvest_at": "…" } },
      { "idx": 2, "soil_quality": 1, "locked": false, "crop": null }
    ]
  }
}
```

`GET /v1/player/inventory`:

```json
{
  "code": 0, "message": "ok",
  "data": {
    "items": [
      { "item_id": "…", "code": "seed_rice", "name": "水稻种子", "category": "seed", "quantity": 12 },
      { "item_id": "…", "code": "fertilizer", "name": "农家肥", "category": "fertilizer", "quantity": 5 }
    ],
    "page": 1, "page_size": 20, "total": 2
  }
}
```

`POST /v1/player/inventory/{item_id}/use`:

```json
{ "target": { "plot_id": "…" } }
→ { "code": 0, "message": "ok", "data": { "effect_applied": { "growth_pct": 50 } } }
```

## 6. 事件协议(WS)

事件信封:

```json
{ "type": "solar_term_change", "payload": { "term_index": 15, "name": "白露", "cycle": 43 }, "ts": 1780000000 }
```

事件注册表:

| type | payload 要点 | 触发 |
|---|---|---|
| `solar_term_change` | term_index / name / cycle | 每轮节气切换(默认 5 分钟) |
| `crop_ready` | plot_id / crop_id | 作物成熟 |
| `inventory_change` | item_id / delta / quantity | 道具获得/消耗 |
| `coins_change` | delta / balance | 货币变动 |
| `quest_progress` | quest_id / progress | 任务进度变化 |
| `broadcast` | content | 运营广播 |

客户端规则:未知事件类型一律忽略(向前兼容);payload 字段只增不删;断线重连后先拉全量状态(`GET /v1/farm/state` 等),再订阅增量。

## 7. 调试接口(demo 专用,上线必须关闭)

| 方法 & 路径 | 说明 |
|---|---|
| `POST /v1/debug/config` | 热改 `game_config` KV(价格、节气时长、活动开关)—— 改价格通过此接口,不发版 |
| `POST /v1/debug/term/advance` | 手动推进节气(测试播种窗/事件/结算) |

安全:`DEBUG_ENABLED` 环境变量控制;上线置 false 或加管理 JWT,不允许公网开放。

## 8. 后续任务

- [ ] 后端骨架落地后,导出 `docs/api/openapi.json`,同步给 Godot 端。
- [ ] 确定 Godot 端对接方式:手写轻量 HTTP/WS client(推荐,demo 可控)或 openapi-generator 生成。
- [ ] 错误码清单随实现补充(1xxx/2xxx 段按域分配)。
- [ ] 调试接口开关(DEBUG_ENABLED)纳入部署配置,demo 后默认关闭。
