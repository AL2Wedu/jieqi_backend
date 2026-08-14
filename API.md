# 节气种田后端 API 文档

> **本文档供开发与 AI Agent 使用**:所有端点、请求/响应格式、错误码均以当前代码为准(2026-08 实测)。
> 配套:OpenAPI 交互文档(服务启动后 `http://<host>:8000/docs`)、`docs/03-API契约与扩展性设计.md`(设计规范)。
> 状态标记:🔓 无需登录 · 🔐 玩家 JWT · 👑 管理员 JWT · 🧪 调试接口(需 `DEBUG_ENABLED=true`)

---

## 1. 通用约定

### 1.1 Base URL

```
开发:http://127.0.0.1:8000/v1
生产:https://<你的域名>/v1
```

### 1.2 认证(双 JWT 体系)

| 体系 | Header | 获取方式 | 有效期 |
|---|---|---|---|
| 玩家 | `Authorization: Bearer <player_token>` | `POST /v1/auth/register` 或 `/login` | 7 天(可配) |
| 管理员 | `Authorization: Bearer <admin_token>` | `POST /v1/admin/login` | 2 小时 |

> WebSocket 无法带 Header:玩家 WS 无需鉴权(仅广播);管理日志流 WS 用查询参数 `?token=<admin_token>`。

### 1.3 响应信封(所有 REST 接口统一)

**成功**:

```json
{ "code": 0, "message": "ok", "data": { } }
```

**失败**(HTTP 状态码 + 业务错误码):

```json
{ "code": 21003, "error_code": "CROP_NOT_AVAILABLE", "message": "当前节气(立春)不适合种植水稻" }
```

**列表分页信封**(`data` 内):

```json
{ "items": [], "page": 1, "page_size": 20, "total": 42 }
```

### 1.4 通用规则

- 时间格式:ISO 8601 UTC(如 `2026-08-13T12:00:00+00:00`);请求体里的时间一律服务端生成,客户端不传
- ID 格式:UUID 字符串
- 分页参数:`page`(从 1 起)/ `page_size`(默认 20,最大 100)
- 请求体:`Content-Type: application/json`
- 价格/金币为整数;`coins` 账本制,所有变动记录在 `coin_transactions`

---

## 2. 完整端点索引

### 2.1 玩家端(REST)

| # | 方法 | 路径 | 鉴权 | 说明 |
|---|---|---|---|---|
| 1 | POST | `/v1/auth/register` | 🔓 | 注册(名字+密码),返回 token + 玩家 |
| 2 | POST | `/v1/auth/login` | 🔓 | 登录 |
| 3 | GET | `/v1/player/me` | 🔐 | 玩家档案(等级/金币/农场摘要) |
| 4 | GET | `/v1/player/inventory` | 🔐 | 背包列表(含数量 0 的道具行) |
| 5 | POST | `/v1/player/inventory/{item_id}/use` | 🔐 | 使用道具(水壶/肥料,需目标地块) |
| 6 | GET | `/v1/calendar/current` | 🔐 | **我的当前节气**(每用户独立世界:在线 1× / 离线 offline_factor) |
| 7 | GET | `/v1/farm/state` | 🔐 | 农场全量状态(4×5=20 地块 + 每格作物状态) |
| 8 | POST | `/v1/farm/plots/{plot_id}/sow` | 🔐 | 播种(校验节气窗 + 消耗种子) |
| 9 | POST | `/v1/farm/plots/{plot_id}/water` | 🔐 | 浇水(water_level → 100) |
| 10 | POST | `/v1/farm/plots/{plot_id}/harvest` | 🔐 | 收获(产量入收成仓,择机出售) |
| 11 | POST | `/v1/farm/plots/{plot_id}/clear` | 🔐 | 铲除作物(清空地块) |
| 12 | GET | `/v1/shop/state` | 🔐 | **我的商店**:商品(库存/售价)+ 作物收购价(季节涨降) |
| 12a | GET | `/v1/shop/items` | 🔐 | 商品列表(兼容,= state.items) |
| 13 | POST | `/v1/shop/items/{item_id}/buy` | 🔐 | 购买(扣库存,售空拒绝;双账本) |
| 13a | GET | `/v1/shop/storage` | 🔐 | 收成仓(收获入仓 + 当前收购价) |
| 13b | POST | `/v1/shop/crops/{crop_id}/sell` | 🔐 | 出售农作物(按季节/分类收购价结算) |

### 2.2 扩展功能:任务 / 社交 / 成就 / AI(玩家端)

| # | 方法 | 路径 | 鉴权 | 说明 |
|---|---|---|---|---|
| 14 | GET | `/v1/quests` | 🔐 | 任务列表(自动跟踪,含实时进度) |
| 15 | POST | `/v1/quests/{quest_id}/claim` | 🔐 | 领取任务奖励 |
| 16 | GET | `/v1/social/friends` | 🔐 | 好友列表 |
| 17 | GET | `/v1/social/requests` | 🔐 | 收到的待处理好友申请 |
| 18 | POST | `/v1/social/requests` | 🔐 | 发送好友申请 `{"player_id": "uuid"}` |
| 19 | POST | `/v1/social/requests/{player_id}/accept` | 🔐 | 接受申请 |
| 20 | POST | `/v1/social/requests/{player_id}/reject` | 🔐 | 拒绝申请 |
| 21 | DELETE | `/v1/social/friends/{player_id}` | 🔐 | 删除好友 |
| 22 | GET | `/v1/achievements` | 🔐 | 成就列表(自动重算进度,达成即 completed) |
| 23 | POST | `/v1/achievements/{achievement_id}/claim` | 🔐 | 领取成就奖励 |
| 24 | POST | `/v1/ai/chat` | 🔐 | **OpenAI 兼容对话转发**(请求体透传,自动记用量) |
| 25 | GET | `/v1/ai/models` | 🔐 | 上游可用模型列表(透传) |
| 26 | GET | `/v1/ai/usage` | 🔐 | 我的 AI 用量(总量 + 按日) |
| 27 | GET | `/v1/art/crops/{slug}/{name}.png?w=` | 🔓 | **美术下发**:按请求分辨率返回预渲染 PNG(见 §8.3) |
| 28 | GET | `/v1/art/version` | 🔓 | **素材版本**(内容哈希):客户端判断是否需要更新本地缓存 |

### 2.2 调试接口(🧪 `DEBUG_ENABLED=true` 时可用,需 🔐)

| # | 方法 | 路径 | 说明 |
|---|---|---|---|
| 14 | POST | `/v1/debug/config` | 热改 `game_config` KV(改价格/节气时长等,不发版) |
| 15 | POST | `/v1/debug/term/advance` | 手动推进**自己**一个节气(测播种窗/事件;只影响调用者玩家的世界) |
| 16 | POST | `/v1/debug/grow` | 催熟指定地块作物(测收获) |

### 2.3 管理后台(👑 全部需 admin token)

| # | 方法 | 路径 | 说明 |
|---|---|---|---|
| 17 | POST | `/v1/admin/login` | 管理员登录 → admin token |
| 18 | GET | `/v1/admin/dashboard` | 服务状态 + 节气 + 全服统计 |
| 19 | GET | `/v1/admin/env` | 系统环境变量只读(敏感值打码) |
| 20 | GET | `/v1/admin/users?page&page_size` | 用户列表(含玩家资产) |
| 21 | PATCH | `/v1/admin/users/{user_id}/status` | 封禁/解封 `{"status": 0|1}` |
| 21a | PATCH | `/v1/admin/users/{user_id}/assets` | 编辑玩家资产 `{"coins","level","exp","unlocked_term_index"}`(全可选) |
| 21b | GET | `/v1/admin/users/{user_id}/farm` | 某用户农场(地块 + 当前作物 + 玩家当前节气) |
| 21c | PUT | `/v1/admin/users/{user_id}/plots/{plot_idx}` | 地块管理 `{"locked","soil_quality"}`(全可选) |
| 21d | PUT | `/v1/admin/users/{user_id}/plots/{plot_idx}/crop` | **地块作物**:种植/替换指定作物(不消耗种子、不校验节气窗) |
| 21e | DELETE | `/v1/admin/users/{user_id}/plots/{plot_idx}/crop` | 清除地块作物 |
| 21f | PUT | `/v1/admin/users/{user_id}/plots/{plot_idx}/growth` | 调整已有作物生长进度% / 浇水 |
| 21g | GET | `/v1/admin/users/{user_id}/inventory` | 玩家背包明细(全部道具 + 当前数量) |
| 21h | PUT | `/v1/admin/users/{user_id}/inventory/{item_id}` | 设定道具数量(绝对值,0=清空;写账本) |
| 21i | GET | `/v1/admin/users/{user_id}/storage` | 玩家收成仓明细(全部作物 + 当前数量) |
| 21j | PUT | `/v1/admin/users/{user_id}/storage/{crop_id}` | 设定收成仓库存(绝对值,0=清空) |
| 22 | GET | `/v1/admin/config` | 全部 `game_config` KV |
| 23 | PUT | `/v1/admin/config/{key}` | 新增/更新 KV `{"value": ...}` |
| 24 | DELETE | `/v1/admin/config/{key}` | 删除 KV |
| 25 | GET | `/v1/admin/crops` | 作物配置列表(含美术) |
| 26 | POST | `/v1/admin/crops` | 新增植物(可 `auto_seed` 自动建种子) |
| 27 | PUT | `/v1/admin/crops/{crop_id}` | 编辑作物(节气窗/生长/价格/美术) |
| 28 | DELETE | `/v1/admin/crops/{crop_id}` | 软删除(下架作物 + 其种子) |
| 29 | GET | `/v1/admin/plantings?active&page&page_size` | 全服种植状态(每株实时) |
| 30 | GET | `/v1/admin/items` | 道具配置列表 |
| 31 | POST | `/v1/admin/items` | 新增道具 |
| 32 | PUT | `/v1/admin/items/{item_id}` | 编辑道具 |
| 33 | DELETE | `/v1/admin/items/{item_id}` | 软删除道具 |
| 34 | GET | `/v1/admin/terms` | 24 节气时长 + 游戏时钟 |
| 35 | PUT | `/v1/admin/terms/{term_index}` | 设置节气时长 `{"duration_seconds": 300}` |
| 36 | PUT | `/v1/admin/clock` | 时钟:倍速/暂停/纪元重置 |
| 36e | GET | `/v1/admin/shop/settings` | 全局商店默认(库存/补货/价格系数) |
| 36f | PUT | `/v1/admin/shop/settings` | 保存全局商店默认 |
| 36g | GET | `/v1/admin/shop/users?page` | 每用户商店摘要(隔离实例) |
| 36h | GET | `/v1/admin/shop/users/{pid}/items` | 某用户商店商品明细(库存/价格/覆盖) |
| 36i | PUT | `/v1/admin/shop/users/{pid}/items/{iid}` | 覆盖库存/买卖价(显式 null 恢复公式价) |
| 36j | POST | `/v1/admin/shop/users/{pid}/restock` | 手动补货(重置为默认库存) |
| 36k | POST | `/v1/admin/shop/users/{pid}/reset` | 重置商店(清覆盖 + 默认库存) |
| 36l | GET | `/v1/admin/worlds?page&page_size` | 每用户世界/节气列表(在线状态 + 累计世界秒 + 当前节气) |
| 36m | PUT | `/v1/admin/worlds/{player_id}` | 设定/重置玩家世界 `{"accum": 秒}` 或 `{"reset": true}`(回立春) |

**管理后台 AI 端点**:

| # | 方法 | 路径 | 说明 |
|---|---|---|---|
| 36a | GET | `/v1/admin/ai/config` | AI 配置(api_key 脱敏) |
| 36b | PUT | `/v1/admin/ai/config` | 保存 AI 配置 `{"enabled","base_url","api_key","model"}` |
| 36c | POST | `/v1/admin/ai/test` | 测试连接(拉取上游模型列表) |
| 36d | GET | `/v1/admin/ai/usage?page&page_size` | 全服每用户 AI 用量 |

### 2.4 WebSocket 与页面

| # | 类型 | 路径 | 说明 |
|---|---|---|---|
| 37 | WS | `/v1/ws?token=` | **每用户节气推送**(🔐 玩家 token,连上即推我的节气,到点推送;无效关 4401) |
| 38 | WS | `/v1/admin/logs?token=` | 后端日志监控(只读流,👑) |
| 39 | GET | `/admin` | 管理后台页面(浏览器) |
| 40 | GET | `/docs` | Swagger UI(OpenAPI) |
| 41 | GET | `/static/*` | 静态资源(管理后台 JS / 植物美术 SVG) |

---

## 3. 玩家端端点详解

### 3.1 POST /v1/auth/register — 注册

**请求体**:

```json
{ "name": "demo01", "password": "demo123456" }
```

| 字段 | 类型 | 约束 |
|---|---|---|
| name | string | 1-32 字符,唯一 |
| password | string | 6-64 字符 |

**成功响应 `data`**:

```json
{
  "token": "<jwt>",
  "player": {
    "player_id": "6f9b...",
    "name": "demo01",
    "level": 1,
    "exp": 0,
    "coins": 200,
    "head_title_id": null,
    "unlocked_term_index": 1,
    "farm_id": "1a2b...",
    "plot_count": 20,
    "register_location": "浙江省 杭州市 阿里",
    "last_login_location": null
    }
}
```

> 注册副作用:自动创建玩家(初始金币 **200**)、农场(20 地块,4 列 × 5 行)、`coin_transactions` 记 `register` 账。
> **IP 与地理位置**:客户端 IP 优先取 `X-Forwarded-For`(反代后),回退直连地址;注册/登录时用 ip2region 离线库解析地理位置(`register_location` / `last_login_location`),库缺失或内网地址降级为 `"内网"`/`null`,**无任何外部请求**。

**错误**:`20001 USER_EXISTS`(用户名已存在)、`10001 INVALID_PARAMS`(参数不合法)

### 3.2 POST /v1/auth/login — 登录

请求体同注册。**错误**:`20003 BAD_CREDENTIALS`(401,密码错)、`20004 USER_BANNED`(403,已封禁)。响应同注册。

### 3.3 GET /v1/player/me — 玩家档案

**成功响应 `data`**:与注册的 `player` 对象相同(见 3.1)。

### 3.4 GET /v1/player/inventory — 背包

**成功响应 `data`**:

```json
{
  "items": [
    { "item_id": "uuid", "code": "seed_rice", "name": "水稻种子",
      "category": "seed", "quantity": 2,
      "effect": { "type": "seed", "crop_id": "uuid" } }
  ]
}
```

> 包含数量为 0 的行(客户端自行决定是否展示);`effect` 为道具效果定义。

### 3.5 POST /v1/player/inventory/{item_id}/use — 使用道具

**请求体**(可选):

```json
{ "target": { "plot_id": "uuid" } }
```

`target.plot_id` 对水壶(water)/肥料(boost)必填。

**成功响应 `data`**:

```json
{ "effect_applied": { "growth_pct": 50, "total_boost_pct": 50 } }   // 肥料
{ "effect_applied": { "water_level": 100 } }                        // 水壶
```

**错误**:`22001 NOT_ENOUGH_ITEM`(道具不足)、`22002 ITEM_NOT_FOUND`、`10001 INVALID_PARAMS`(缺 target)、`21004 PLOT_EMPTY`(地块无作物)、`22004 EFFECT_NOT_SUPPORTED`(种子/节气卡:种子走播种接口,节气卡功能开发中)

### 3.6 GET /v1/calendar/current — 我的当前节气(🔐)

**鉴权**:需玩家 JWT(每用户独立世界)。

> **每用户世界时钟**:每个玩家维护自己的累计世界时间。
> - 在线(最近一次请求/心跳在 `world.online_threshold_sec` 秒内,默认 300):世界按全局 `time_scale × 1.0` 推进。
> - 离线:按全局 `time_scale × world.offline_factor` 推进(**默认 0.25**,`game_config` 可配)。
> - **植物生长始终按墙钟正常速度**(与节气倍速无关)。首次访问自动继承全局节气位置(老玩家零成本迁移)。

**成功响应 `data`**:

```json
{ "term_index": 6, "name": "谷雨", "cycle": 0, "remaining_sec": 173 }
```

| 字段 | 说明 |
|---|---|
| term_index | 1-24(1立春 … 24大寒) |
| name | 节气名 |
| cycle | 完整轮次数(从服务启动纪元起) |
| remaining_sec | 本轮剩余秒(节气切换倒计时,按玩家倍速) |

### 3.7 GET /v1/farm/state — 农场状态(🔐)

> `current_term` 为该玩家自己的节气(每用户独立世界,见 §3.6);作物 `growth_progress`/`stage` 始终按墙钟正常速度计算。

**成功响应 `data`**:

```json
{
  "farm": { "farm_id": "uuid", "name": "demo01的农场", "plot_count": 20,
            "grid": { "cols": 4, "rows": 5 } },
  "current_term": { "term_index": 6, "name": "谷雨", "cycle": 0, "remaining_sec": 173 },
  "plots": [
    {
      "plot_id": "uuid",
      "idx": 1,
      "soil_quality": 1,
      "locked": false,
      "crop": {
        "crop_id": "uuid",
        "name": "水稻",
        "art": { "seed": "/static/assets/crops/rice/seed.svg",
                 "stages": ["/static/assets/crops/rice/1.svg",
                            "/static/assets/crops/rice/2.svg",
                            "/static/assets/crops/rice/3.svg"] },
        "stage": 1,
        "growth_progress": 12,
        "water_level": 100,
        "water_need": 60,   // 需水红线(低于则生长停滞)
        "settings": {       // 植物高级设定(枯萎季节/加速/需水/需肥/单株上限)
          "wither_seasons": ["winter"],
          "fast_growth_seasons": { "summer": 1.5 },
          "water_need": { "min": 60, "ideal": 90 },
          "fertility_need": 1,
          "max_value": 30
        },
        "predicted_harvest_at": "2026-08-13T12:15:00+00:00"
      }
    }
  ]
}
```

**作物状态规则(服务器权威,客户端勿本地推算)**:

- `growth_progress` = min(100, 已生长秒/生长时长×100 + 肥料boost%)
- `stage`:1 苗期(<50%) / 2 生长期(<100%) / 3 成熟(=100%)
- `water_level`:0-100,浇水置 100(当前无衰减)
- `art.stages[0..2]` 对应 苗期/生长期/成熟 三张图,Godot 按 `stage-1` 取图

**作物图片获取(推荐走分辨率下发接口,见 §8.3)**:

1. 从地块 `crop.art` 取路径,**提取 slug**(路径倒数第二段:`/static/assets/crops/rice/seed.svg` → `rice`)
2. 按格子显示尺寸请求预渲染 PNG,服务端自动选最近档(32/64/128/256):

```http
# 种子图标(背包/商店用)
GET /v1/art/crops/{slug}/seed.png?w=64
# 阶段图(农场地块,crop.stage 为 1/2/3)
GET /v1/art/crops/{slug}/{crop.stage}.png?w=128
```

3. 响应 `image/png` + `Cache-Control: public, max-age=86400`,客户端可放心缓存;素材不存在返回 404(`28001`)

**错误**:`21000 FARM_NOT_FOUND`

### 3.8 POST /v1/farm/plots/{plot_id}/sow — 播种

**请求体**:

```json
{ "crop_id": "uuid" }
```

`crop_id` 从商店种子道具的 `effect.crop_id` 或 `/v1/admin/crops` 获取。

**成功响应 `data`**:

```json
{
  "plot_id": "uuid",
  "crop_id": "uuid",
  "crop_name": "水稻",
  "sowed_term_index": 6,
  "predicted_harvest_at": "2026-08-13T12:15:00+00:00"
}
```

**节气窗校验规则**:
- `sow_window.type == "term"`:`start <= 当前节气 <= end` 或 `end < 当前节气 <= end+grace`(宽限期)
- `sow_window.type == "season"`:`seasons` 含当前季节(春=1-6 / 夏=7-12 / 秋=13-18 / 冬=19-24)

**错误**:`21001 PLOT_NOT_FOUND`、`21002 PLOT_OCCUPIED`(已有作物,先收或铲)、`21005 CROP_NOT_FOUND`、`21003 CROP_NOT_AVAILABLE`(节气窗外)、`21006 NOT_ENOUGH_ITEM`(种子不足,先买)

### 3.9 POST /v1/farm/plots/{plot_id}/water — 浇水

无请求体。**响应** `data`: `{"plot_id": "...", "water_level": 100}`。
**错误**:`21001 PLOT_NOT_FOUND`、`21004 PLOT_EMPTY`

### 3.10 POST /v1/farm/plots/{plot_id}/harvest — 收获

无请求体。**成功响应 `data`**:

```json
{
  "plot_id": "uuid", "crop_id": "uuid", "crop_name": "水稻",
  "yield": 6, "coins_earned": 120, "coins_balance": 320
}
```

> 结算:`yield = round(yield_base × (1 + 0.1×(soil_quality-1)))`;`coins = yield × base_price`。丰收记录保留(`crop_instances` 带 `harvested_at`),地块可再种。

**错误**:`23001 CROP_NOT_MATURE`(未成熟)、`21004 PLOT_EMPTY`

### 3.11 POST /v1/farm/plots/{plot_id}/clear — 铲除

无请求体。**响应** `data`: `{"plot_id": "...", "cleared": true}`(作物标记收获、yield=0,地块释放)。

### 3.12 GET /v1/shop/items — 商店

> 季节涨降(`crop_quotes.sell_price` 的 `season_factor`)跟随**该玩家自己的世界节气**(每用户独立,见 §3.6),而非全局。

**成功响应 `data`**:

```json
{ "items": [ { "item_id": "uuid", "code": "seed_rice", "name": "水稻种子",
    "category": "seed", "buy_price": 25, "sell_price": 5, "unlock_level": 1,
    "effect": { "type": "seed", "crop_id": "uuid" } } ] }
```

### 3.13 POST /v1/shop/items/{item_id}/buy — 购买

**请求体**: `{"quantity": 1}`(1-999,默认 1)

**成功响应 `data`**:

```json
{ "item_id": "uuid", "code": "seed_rice", "quantity": 1, "cost": 25, "coins_balance": 175 }
```

**错误**:`22002 ITEM_NOT_FOUND`、`22003 NOT_ENOUGH_COINS`

---

## 4. 调试接口(🧪)

### 4.1 POST /v1/debug/config — 热改全局配置

**请求体**: `{"key": "sow.grace_terms", "value": 2}`(`value` 可为任意 JSON 类型)

**响应** `data`: `{"key": "...", "value": ...}`。配置写入 `game_config` 表,即时生效,不发版。

**错误**:`90001 DEBUG_DISABLED`(403,`DEBUG_ENABLED=false` 时)

### 4.2 POST /v1/debug/term/advance — 推进节气(只影响自己)

无请求体。**响应** `data`: 同 `/v1/calendar/current`(推进后的**调用者**当前节气)。

> 只推进调用者玩家的世界一个节气时长,其他玩家互不影响(每用户独立世界)。

### 4.3 POST /v1/debug/grow — 催熟

**请求体**: `{"plot_id": "uuid"}`

**响应** `data`: `{"plot_id": "...", "mature": true}`(把 `sowed_at` 回拨,作物立即成熟)。

---

## 5. 管理后台端点详解(👑)

### 5.1 POST /v1/admin/login

**请求体**: `{"username": "admin", "password": "admin123"}`

**成功响应 `data`**: `{"token": "<admin_jwt>"}`
**错误**:`30001 ADMIN_BAD_CREDENTIALS`(401)、`30002 ADMIN_DISABLED`(403,`ADMIN_ENABLED=false`)

### 5.2 GET /v1/admin/dashboard

**成功响应 `data`**:

```json
{
  "server": { "pid": 1234, "version": "0.1.0", "admin_enabled": true, "debug_enabled": true, "db_size": 188416 },
  "calendar": { "term_index": 6, "name": "谷雨", "cycle": 0, "remaining_sec": 173 },
  "counts": { "users": 3, "players": 3, "farms": 3, "coins_total": 600,
              "crops": 6, "items": 9, "terms": 24, "growing": 1 }
}
```

### 5.3 GET /v1/admin/env

**成功响应 `data`**: `{"items": [{"name": "PATH", "value": "..."}, ...]}`(最多 100 条;含 password/secret/token/key 的变量值打码为 `***`)

### 5.4 GET /v1/admin/users?page=1&page_size=20

**成功响应 `data`**(分页信封):

```json
{
  "items": [
    { "user_id": "uuid", "name": "demo01", "status": 1,
      "register_ip": "127.0.0.1", "register_location": "内网",
      "last_login_ip": "223.5.5.5", "last_login_location": "浙江省 杭州市 阿里",
      "created_at": "2026-08-13T...", "last_login_at": "2026-08-13T...",
      "player": { "level": 1, "exp": 0, "coins": 200, "unlocked_term_index": 1 } }
  ],
  "page": 1, "page_size": 20, "total": 3
}
```

### 5.5 PATCH /v1/admin/users/{user_id}/status

**请求体**: `{"status": 0}`(0 封禁 / 1 解封)

**响应** `data`: `{"user_id": "...", "status": 0}`。封禁后该用户登录返回 `20004 USER_BANNED`。

### 5.6 GET /v1/admin/config · PUT /v1/admin/config/{key} · DELETE

- `GET`: `{"items": [{"key": "...", "value": ..., "updated_at": "..."}]}`
- `PUT /config/{key}` 请求体: `{"value": ...}` → `data: {"key": "...", "value": ...}`
- `DELETE /config/{key}` → `data: {"deleted": "..."}`

### 5.7 作物管理(25-28)

**GET /v1/admin/crops** → `data: {"items": [作物对象]}`。作物对象:

```json
{
  "crop_id": "uuid", "name": "水稻", "category": "谷物",
  "sow_window": { "type": "term", "start": 5, "end": 7, "grace": 2 },
  "grow_seconds": 900, "yield_base": 6, "base_price": 20,
  "unlock_level": 1, "description": "谷雨前后,种瓜点豆。",
  "art": { "seed": "/static/assets/crops/rice/seed.svg",
           "stages": [".../1.svg", ".../2.svg", ".../3.svg"] },
  "sort_order": 1, "active": true
}
```

**POST /v1/admin/crops** 请求体(新增植物):

```json
{
  "name": "萝卜", "category": "蔬菜",
  "sow_window": { "type": "term", "start": 14, "end": 16, "grace": 2 },
  "grow_seconds": 700, "yield_base": 4, "base_price": 14,
  "description": "头伏萝卜二伏菜。",
  "auto_seed": true
}
```

- `name` 必填;`category` ∈ 谷物/蔬菜/瓜果/花卉
- `auto_seed=true` 自动创建对应种子道具(`code = seed_<uuid前8位>`,商店可买)
- 不传 `art` 时自动生成通用占位 SVG 美术
- 响应:作物对象 + `"seed_created": true/false`
- 错误:`21006 CROP_EXISTS`、`10001 INVALID_PARAMS`(名称必填)

**PUT /v1/admin/crops/{crop_id}** 请求体:任意可改字段(与 POST 相同字段,均可选,含 `art`)。响应:更新后的作物对象。错误:`21005 CROP_NOT_FOUND`。

**DELETE /v1/admin/crops/{crop_id}** → `data: {"crop_id": "...", "active": false}`(软删,同时下架其种子)。错误:`21005 CROP_NOT_FOUND`、`21007 CROP_IN_USE`(有种植中的作物)。

### 5.8 GET /v1/admin/plantings — 全服种植状态

**成功响应 `data`**(分页信封):

```json
{
  "items": [
    { "planting_id": "uuid", "player": "demo01", "farm": "demo01的农场", "plot_idx": 1,
      "crop": "水稻", "stage": 1, "growth_progress": 12, "water_level": 100,
      "predicted_harvest_at": "2026-08-13T12:15:00+00:00",
      "sowed_term_index": 6, "sowed_at": "2026-08-13T11:45:00+00:00" }
  ],
  "page": 1, "page_size": 20, "total": 1
}
```

查询参数:`active=true`(默认,只看种植中)/ `false` 含历史。

### 5.9 道具管理(30-33)

**GET /v1/admin/items** → `data: {"items": [道具对象]}`:

```json
{
  "item_id": "uuid", "code": "fertilizer", "name": "农家肥", "category": "fertilizer",
  "buy_price": 50, "sell_price": 10, "unlock_level": 1,
  "effect": { "type": "boost", "growth_pct": 50 }, "active": true
}
```

**POST /v1/admin/items** 请求体:`code`(必填,唯一)/ `name`(必填)/ `category` / `effect` / `buy_price` / `sell_price` / `unlock_level` / `active`。
- `effect.type="seed"` 时 `effect.crop_id` 必须是存在的作物,否则 `10001 INVALID_PARAMS`
- 错误:`22005 ITEM_EXISTS`、`10001 INVALID_PARAMS`

**PUT /v1/admin/items/{item_id}** / **DELETE**(软删 `active:false`)同作物模式。

### 5.10 节气与时钟(34-36)

**GET /v1/admin/terms** → `data`:

```json
{
  "items": [ { "term_index": 1, "name": "立春", "duration_seconds": 300 } ],
  "clock": { "epoch": "2026-08-13T...", "time_scale": 1.0, "paused": false }
}
```

**PUT /v1/admin/terms/{term_index}** 请求体: `{"duration_seconds": 420}`(10-86400)→ `data: {"term_index": 1, "name": "立春", "duration_seconds": 420}`。错误:`23002 TERM_NOT_FOUND`。

**PUT /v1/admin/clock** 请求体(全部可选):

```json
{ "time_scale": 2.0, "paused": true, "reset_epoch": false }
```

→ `data: {"epoch": "...", "time_scale": 2.0, "paused": true}`。`reset_epoch=true` 把纪元重置为当前时间。**注意**:全局时钟现作为"参考"与新玩家初始化起点;玩家各自的世界在其基础上按在线/离线倍速推进。

### 5.11 玩家资产 / 农场 / 每用户世界(21a-21c,36l-36m)

**PATCH /v1/admin/users/{user_id}/assets** 请求体(全可选): `{"coins": 9999, "level": 5, "exp": 100, "unlocked_term_index": 12}`

→ `data: {"player_id", "name", "level", "exp", "coins", "unlocked_term_index"}`。

**GET /v1/admin/users/{user_id}/farm** → `data`:

```json
{
  "player_id": "uuid", "name": "demo01",
  "farm": { "farm_id": "uuid", "name": "demo01的农场", "plot_count": 20, "grid": {"cols":4,"rows":5} },
  "current_term": { "term_index": 6, "name": "谷雨", "cycle": 0, "remaining_sec": 173 },
  "plots": [ { "plot_id": "uuid", "idx": 1, "soil_quality": 1, "locked": false, "crop": { ... } } ]
}
```

**PUT /v1/admin/users/{user_id}/plots/{plot_idx}** 请求体(全可选): `{"locked": true, "soil_quality": 3}` → `data: {"plot_id","idx","soil_quality","locked"}`。

**GET /v1/admin/worlds?page=1&page_size=20** → `data`:

```json
{ "items": [ { "player_id": "uuid", "name": "demo01",
    "online": true, "last_active_at": "...", "world_accum": 12345, "world_last_sync": "...",
    "current_term": { "term_index": 6, "name": "谷雨", "cycle": 0, "remaining_sec": 173 } } ],
  "page": 1, "page_size": 20, "total": 3 }
```

**PUT /v1/admin/worlds/{player_id}** 请求体: `{"accum": 6000}` 设定累计世界秒;或 `{"reset": true}` 重置回立春(term 1,accum=0)。→ `data: {"player_id","accum","term_index","name","cycle","remaining_sec"}`。

### 5.12 每用户世界配置(离线倍速)

`game_config` 键(管理后台"全局配置"页或 `PUT /v1/admin/config/{key}` 热改,即时生效):

| key | 默认 | 说明 |
|---|---|---|
| `world.offline_factor` | `0.25` | 离线时世界推进倍速(0-1;1 = 在线同速) |
| `world.online_threshold_sec` | `300` | 距最近心跳超过该秒数判定为离线 |

### 5.13 地块作物 / 背包 / 收成仓控制(21d-21j,👑)

管理端**纯后台直接改库**:播种不消耗种子、不校验节气窗(与玩家正常播种区分开)。

**PUT /v1/admin/users/{user_id}/plots/{plot_idx}/crop** — 种植/替换指定作物

```json
{ "crop_id": "uuid", "growth_progress": 60, "water_level": 80 }
```

| 字段 | 说明 |
|---|---|
| crop_id | 目标作物(必须 `active`) |
| growth_progress | 0-100,默认 0;**唯一真源**——按进度回拨 `sowed_at`,`stage` 由服务器推导(≥50 → 生长期,=100 → 成熟) |
| water_level | 0-100,默认 100 |

若该地块已有活跃作物 → 先标记已收获(yield=0)再种新的。→ `data`: 含 `plot_id`/`idx` + 作物 view(`crop_id`/`name`/`stage`/`growth_progress`/`water_level`/`predicted_harvest_at`)。

**DELETE /v1/admin/users/{user_id}/plots/{plot_idx}/crop** → `{"plot_id","idx","cleared":true}`(无产量)。

**PUT /v1/admin/users/{user_id}/plots/{plot_idx}/growth** — 调整已有作物(全可选): `{"growth_progress": 100, "water_level": 50}` → 作物 view。空地块报 `21004 PLOT_EMPTY`。

**GET /v1/admin/users/{user_id}/inventory** → `data: {"player_id", "items": [{item_id, code, name, category, quantity, active}]}`(全部道具,数量 0 也列出)。

**PUT /v1/admin/users/{user_id}/inventory/{item_id}** 请求体 `{"quantity": 5}`(0=清空行)→ `data: {"player_id","item_id","code","quantity"}`。**写 `item_transactions` 账本**(`reason="admin"`),便于审计。

**GET /v1/admin/users/{user_id}/storage** → `data: {"player_id", "crops": [{crop_id, name, category, quantity, active}]}`。

**PUT /v1/admin/users/{user_id}/storage/{crop_id}** 请求体 `{"quantity": 12}`(0=清空行)→ `data: {"player_id","crop_id","name","quantity"}`。

> 玩家视角立即生效:种植后 `/v1/farm/state` 可见;背包改后 `/v1/player/inventory` 可见;收成仓改后 `/v1/shop/storage` 可见。进度调至 100 后玩家可正常收获(走正常链路入仓)。

---

## 6. 任务 / 社交 / 成就 / AI

### 6.1 通用条件格式(任务与成就共用)

进度**由服务器从真实数据实时计算**,不依赖客户端上报。`objective`(任务)/ `target`(成就)格式:

| type | 字段 | 含义 |
|---|---|---|
| sow | count | 累计播种次数 |
| harvest | count | 累计收获次数 |
| spend_coins | amount | 累计消费金币 |
| level | level | 达到等级 |
| friend | count | 好友数量 |
| counter | key + count | 通用计数器(`ai_requests` / `ai_tokens`,取自用量表) |
| any | count | 占位,直接达成 |

> 新增条件类型只需扩展 `app/services/goal_service.py`,任务/成就配置零改动。

### 6.2 任务

**GET /v1/quests** → `data: {"items": [...]}`,每个任务:

```json
{
  "quest_id": "uuid", "code": "q_sow_3", "name": "春耕三亩",
  "description": "累计播种 3 株作物", "category": "daily",
  "objective": { "type": "sow", "count": 3 },
  "reward": { "coins": 30, "exp": 5 },
  "status": 0,                       // 0进行中 1已完成 2已领取
  "progress": { "current": 1, "target": 3 }
}
```

任务自动跟踪(无需接取);`status` 在读取时自动更新。**POST /v1/quests/{id}/claim** → `data: {quest_id, code, reward, coins_balance}`。奖励(金币/经验/道具)全部走账本。

### 6.3 社交

- **GET /v1/social/friends** → `{"items": [{"player_id","name"}]}`
- **GET /v1/social/requests** → 发给我的待处理申请 `{"items": [{"player_id","name","created_at"}]}`
- **POST /v1/social/requests** body `{"player_id": "对方玩家id"}` → `{"status": 0, "target_player_id"}`
- **accept / reject** → `{"status": 1|2, "target_player_id"}`
- **DELETE /v1/social/friends/{player_id}** → `{"removed_player_id"}`

### 6.4 成就(通用版)

**GET /v1/achievements** → `{"items": [...]}`,每个:

```json
{
  "achievement_id": "uuid", "code": "a_first_sow", "name": "初识农事",
  "category": "成长", "target": { "type": "sow", "count": 1 },
  "reward": { "coins": 10, "exp": 5 },
  "completed": true, "claimed": false,
  "progress": { "current": 1, "target": 1 },
  "completed_at": "2026-08-13T..."
}
```

读取时自动重算并置 `completed`;**POST /v1/achievements/{id}/claim** 领取奖励。后续可按需逐条细化规则,API 不变。

### 6.5 AI 转发(OpenAI 兼容)

**POST /v1/ai/chat** —— 请求体与上游完全一致(OpenAI chat/completions 格式),响应原样透传,自动记录用量:

```json
// 请求
{ "model": "deepseek-chat", "messages": [{"role": "user", "content": "谷雨是什么?"}], "temperature": 0.7 }
// 响应 data(上游原样)
{ "id": "chatcmpl-...", "model": "deepseek-chat",
  "choices": [{"index": 0, "message": {"role": "assistant", "content": "..."}, "finish_reason": "stop"}],
  "usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20} }
```

- `model` 缺省时用管理后台配置的默认模型
- 支持任意 OpenAI 兼容上游(DeepSeek / 通义 / 智谱 / OpenAI)
- 配置在管理后台"AI 设置"或 `PUT /v1/admin/ai/config`:enabled / base_url / api_key / model
- **GET /v1/ai/usage** → `{total: {requests, prompt_tokens, completion_tokens, total_tokens}, by_day: [...]}`
- **GET /v1/admin/ai/usage** → 全服每用户用量(按玩家聚合)

### 3.10 商店(每用户独立 · 季节涨降)

**隔离**:每个玩家一个商店实例(`user_shops` + `user_shop_items`),库存/价格互不影响;首次访问自动初始化(全部在售道具,库存=全局默认)。

**定价公式**(管理端全局可调):
```
道具/种子售价 = item.buy_price × shop_settings.item_factor
作物收购价   = crop.base_price × sell_factor × season_effect[季节] × category_factor[分类]
季节:节气 1-6 春 / 7-12 夏 / 13-18 秋 / 19-24 冬(默认系数 春1.1 夏1.0 秋1.2 冬0.9)
覆盖:管理端可对单用户单商品设 buy_price/sell_price(显式 null 恢复公式价)
```

**补货**:`restocked_at + restock_seconds` 到点后全量重置库存为默认(读取时惰性触发);管理端可手动补货。**售空**:库存 0 时购买返回 `22006 NOT_ENOUGH_STOCK`。

**收成仓**:收获不再直接结算金币,产量入 `crop_storage`;玩家择机出售吃季节涨降:
- `POST /v1/shop/crops/{id}/sell {quantity}` → `{crop_id, name, quantity, price, unit_price, storage_after, coins_balance}`
- 收成仓与收购价:`GET /v1/shop/storage` → `{season, items:[{crop_id, name, quantity, sell_price, season}]}`

**GET /v1/shop/state** → `{season, restocked, restock_seconds, items:[{item_id, code, name, category, effect, stock, buy_price, sell_price}], crop_quotes:[{crop_id, name, category, base_price, sell_price, season, season_factor}]}`

**harvest 响应**(已变更):`{plot_id, crop_id, crop_name, yield, storage_after, note}`(不再含 coins_earned)。

---

## 7. WebSocket 协议

### 7.1 WS /v1/ws?token=<player_token> — 每用户节气推送(🔐)

- **鉴权**:玩家 JWT 走查询参数(WS 无法带 Header)。无效/过期 token → 服务端关 `4401`。
- 连接建立后立即推送一条**我的**当前节气事件;此后按该玩家的世界倍速,到点推送下一条(`remaining_sec` 除以倍速后的墙钟等待)
- 连接期间视为**在线**(世界按 1× 推进),与 REST 心跳同一阈值判定
- 客户端收到 `{"type":"unknown"}` 事件应**忽略**(向前兼容)

```json
{ "type": "solar_term_change", "payload": { "term_index": 7, "name": "立夏", "cycle": 1, "remaining_sec": 300 }, "ts": 1784000000 }
```

- 客户端发文本 `ping` → 服务端回 `{"type":"pong"}`
- 断线重连:重连后第一条就是当前节气,不会丢状态

### 7.2 WS /v1/admin/logs?token=<admin_token> — 后端日志监控(只读)

后端运行日志实时流,等价 `Get-Content server.out.log -Wait`。

- 连接即**回放最后 200 行**,之后**增量实时推送**
- 服务端 → 客户端(JSON):
  - `{"type":"log","data":"<日志行>"}` — 普通日志行
  - `{"type":"error","data":"<提示>"}` — 日志文件不存在 / 文件轮转提示
- 客户端 → 服务端:文本 `ping`(保活),服务端回 `{"type":"pong"}`
- 日志源:`server/logs/server.out.log`(uvicorn 访问日志);文件被轮转(变小)时自动从头重读
- 断开后客户端应自动重连(重连后重新回放最后 200 行)

> 该流为**只读**,不暴露任何命令执行能力(无 RCE 面),生产环境可放心开放;后端由系统服务托管常驻。

### 7.3 服务端主动推送事件(每用户定向,WS /v1/ws)

除节气帧外,服务端会向**目标玩家的所有在线连接**主动推送以下事件;客户端收到后应**立即刷新对应资源**:

| type | 触发场景 | payload | 客户端动作 |
|---|---|---|---|
| `resources_changed` | 管理后台编辑该玩家资产(金币/等级/经验/解锁节气) | `{player_id, name, level, exp, coins, unlocked_term_index}` | **强制刷新** `/v1/player/me` 并更新本地资源(此事件为资源权威变更,不依赖轮询) |
| `pest_big` | 该玩家大虫害触发(音游对抗) | `{pest_id, type:"big", duration_seconds}` | 弹出音游界面,游玩结束后 POST `/v1/farm/pest/{pest_id}/result` |
| `pest_small` | 该玩家小虫害寄生(含大虫害未达标的惩罚寄生) | `{pest_id, type:"small", targets:[{pest_id, plot_id, idx, crop, stage, wait_seconds, ready_at}]}` | 标红目标地块,倒计时;驱赶 POST `/v1/farm/pest/{pest_id}/drive-away` |
| `pest_destroyed` | 寄生倒计时到点,作物被摧毁 | `{targets:[{pest_id, plot_id}]}` | 刷新对应地块(作物已消失) |
| `crop_withered` | 玩家季节进入植物枯萎季节,作物枯萎 | `{targets:[{plot_id, idx, crop_name}]}` | 刷新对应地块(作物已消失)+ 弹枯萎提示 |

```json
{ "type": "resources_changed", "payload": { "player_id": "…", "name": "demo01", "level": 5, "exp": 120, "coins": 666, "unlocked_term_index": 6 }, "ts": 1784000000 }
```

- 事件都带 `ts`(unix 秒);未知事件类型一律**忽略**(向前兼容)
- 玩家不在线时推送静默丢弃,客户端下次登录/轮询自然收敛
- 管理端其他资源编辑(背包/收成仓/地块作物)按同一模式推送,事件类型另行约定

---

## 8. 数据对象速查

### 8.1 道具效果(effect JSONB)

| type | 字段 | 说明 |
|---|---|---|
| seed | crop_id | 对应作物,播种时消耗 1 个 |
| boost | growth_pct | 生长进度 +N%(可叠加,存 `extra.boost_pct`) |
| water | amount | 浇水(当前置 water_level=100) |
| term_lock | lock_terms | 节气卡,锁定 N 轮(效果未实现) |

### 8.2 内置数据(seed 幂等导入)

**24 节气**(term_index 1-24):立春 雨水 惊蛰 春分 清明 谷雨 / 立夏 小满 芒种 夏至 小暑 大暑 / 立秋 处暑 白露 秋分 寒露 霜降 / 立冬 小雪 大雪 冬至 小寒 大寒

**6 作物**:水稻(5-7)、小麦(19-21)、大豆(9-11)、白菜(18-20)、番茄(6-8)、菊花(4-6)—— 括号内为节气窗,均有 grace 2

**9 道具**:6 种子 + 农家肥(boost 50)+ 水壶(water)+ 节气卡(term_lock)

### 8.3 美术资产(多分辨率预渲染)

每个作物 4 个素材(种子 + 苗期/生长期/成熟),双格式:

- **SVG 矢量源**:`/static/assets/crops/<slug>/{seed,1,2,3}.svg`(管理后台预览用)
- **预渲染 PNG 四档**:`<name>_32.png` / `_64.png` / `_128.png` / `_256.png`(启动/创建时生成)

**客户端取图协议(推荐)** —— 按屏幕分辨率请求,服务端自动选档:

```
GET /v1/art/crops/{slug}/{seed|1|2|3}.png?w=<目标像素>
```

- 选档规则:取**最小不小于 w** 的预渲染档;w 超过 256 时返回最大档(256)
- 响应:`image/png` + `Cache-Control: public, max-age=86400`;素材不存在返回 404(`28001 ART_NOT_FOUND`)
- slug 来源:作物 `art.seed` 路径中的目录名(如 `/static/assets/crops/rice/seed.svg` → `rice`)
- 示例:Godot 端格子图 `?w=64`(缩略)/ 大图 `?w=256`;玩家视角按 `stage-1` 取 `stages` 对应素材
- **取图闭环**:`GET /v1/farm/state` → 每格 `crop.art`(取 slug)→ `GET /v1/art/crops/{slug}/{seed|stage}.png?w=<px>`(详见 §3.7)

**素材版本更新协议(客户端缓存刷新)**:

```
GET /v1/art/version  →  data: {
  "version": "a1b2c3d4e5f6",          // 全服素材版本(全部文件内容哈希)
  "crops": { "rice": "9f8e7d...", ... },  // 逐作物版本
  "sizes": [32, 64, 128, 256],
  "updated_at": "2026-08-13T..."
}
```

- **客户端本地缓存素材时**:登录后 / 每次节气切换(WS 广播)时调用一次,与本地记录的版本对比:
  - `version` 不同 → 全量刷新本地素材缓存
  - 仅某作物 `crops[slug]` 不同 → 只重新下载该作物的图片
- 版本 = 素材文件内容哈希(管理后台新增/修改作物、替换美术文件后自动变化,无需重启)
- 服务端带 mtime 缓存,轮询开销极小

### 8.4 植物设定文件(data/crops/<slug>.json)

每株植物一个 JSONC 文件(支持 `//` 注释),是植物设定的**事实源**,启动/重跑 seed 时幂等同步到 DB(`crops` 表新增 `unlock_exp` + `settings` 列)。修改文件 → 重启服务即生效。

- `data/crops/_template.json`:全字段注释模板(复制即可新增植物)
- 字段:`slug / name / category / sort_order / sow_window / grow_seconds / yield_base / base_price / unlock_level / unlock_exp / settings / art(可选)/ note`
- `settings` 含义:
  - `wither_seasons`: 玩家世界进入这些季节(spring/summer/autumn/winter)时,未收获的该植物枯萎(WS 推 `crop_withered`,farm state 返回 `wither_events`)
  - `fast_growth_seasons`: `{季节: 倍率}` —— 在该季节播种 → 生长速度 × 倍率(成熟时间缩短;sow 响应含 `grow_seconds_eff`/`season_boost`)
  - `water_need`: `{min, ideal}` —— 水分每节气 -10,低于 `min` 生长停滞
  - `fertility_need`: 土壤肥力低于该值 → 收成减产 ×(soil/need)
  - `max_value`: 单株卖价上限(金币),0 = 不封顶
- 管理后台"作物管理"新增/编辑植物时自动写回文件

---

## 9. 错误码全表

| code | error_code | HTTP | 场景 |
|---|---|---|---|
| 0 | - | 200 | 成功 |
| 10001 | INVALID_PARAMS | 400 | 参数不合法/缺字段/种子 crop_id 无效 |
| 10002 | UNAUTHORIZED | 401 | 未登录 / 玩家不存在 |
| 10003 | UNAUTHORIZED | 401 | token 过期或无效 |
| 20001 | USER_EXISTS | 400 | 注册用户名已存在 |
| 20002 | USER_NOT_FOUND | 400 | 用户不存在(管理端) |
| 20003 | BAD_CREDENTIALS | 401 | 用户名或密码错误 |
| 20004 | USER_BANNED | 403 | 账号被封禁 |
| 21000 | FARM_NOT_FOUND | 400 | 农场不存在 |
| 21001 | PLOT_NOT_FOUND | 400 | 地块不存在/未解锁/非本人 |
| 21002 | PLOT_OCCUPIED | 400 | 地块已有作物 |
| 21003 | CROP_NOT_AVAILABLE | 400 | 当前节气不在该作物宜种窗 |
| 21004 | PLOT_EMPTY | 400 | 地块没有作物 |
| 21005 | CROP_NOT_FOUND | 400 | 作物不存在 |
| 21005 | SEED_NOT_FOUND | 400 | 该作物没有对应种子道具 |
| 21006 | CROP_EXISTS | 400 | 作物重名(管理端新增) |
| 21006 | NOT_ENOUGH_ITEM | 400 | 种子不足(播种时) |
| 21007 | CROP_IN_USE | 400 | 有种植中的作物,无法删除 |
| 21008 | CROP_LOCKED | 400 | 植物未解锁(经验/等级未达其一) |
| 22001 | NOT_ENOUGH_ITEM | 400 | 道具数量不足 |
| 22002 | ITEM_NOT_FOUND | 400 | 道具/商品不存在 |
| 22003 | NOT_ENOUGH_COINS | 400 | 金币不足 |
| 22004 | EFFECT_NOT_SUPPORTED | 400 | 效果不支持(种子走播种/节气卡开发中) |
| 22005 | ITEM_EXISTS | 400 | 道具 code 已存在 |
| 22006 | NOT_ENOUGH_STOCK | 400 | 商店库存不足(可售空) |
| 22007 | NOT_ENOUGH_CROP | 400 | 收成仓数量不足 |
| 23001 | CROP_NOT_MATURE | 400 | 作物尚未成熟 |
| 23002 | TERM_NOT_FOUND | 400 | 节气不存在(管理端) |
| 24001 | AI_DISABLED | 400 | AI 服务未启用 |
| 24002 | AI_NOT_CONFIGURED | 400 | AI 服务器或 API Key 未配置 |
| 24003 | AI_UPSTREAM_ERROR | 400 | 上游 AI 服务错误/连接失败 |
| 25001 | QUEST_NOT_FOUND | 400 | 任务不存在 |
| 25002 | QUEST_NOT_COMPLETE | 400 | 任务尚未完成 |
| 25003 | QUEST_ALREADY_CLAIMED | 400 | 任务奖励已领取 |
| 26001 | ACHIEVEMENT_NOT_FOUND | 400 | 成就不存在 |
| 26002 | ACHIEVEMENT_NOT_COMPLETE | 400 | 成就尚未达成 |
| 26003 | ACHIEVEMENT_ALREADY_CLAIMED | 400 | 成就奖励已领取 |
| 27001 | ALREADY_FRIENDS | 400 | 已经是好友 |
| 27002 | REQUEST_EXISTS | 400 | 好友申请已发送,等待处理 |
| 27003 | REQUEST_NOT_FOUND | 400 | 好友申请不存在 |
| 27004 | NOT_YOUR_REQUEST | 400 | 该申请不是发给你的 |
| 27005 | FRIEND_NOT_FOUND | 400 | 好友不存在 |
| 28001 | ART_NOT_FOUND | 404 | 美术素材不存在 |
| 30001 | ADMIN_BAD_CREDENTIALS | 401 | 管理员账号或密码错误 |
| 30002 | ADMIN_DISABLED | 403 | 管理后台已关闭 |
| 90000 | INTERNAL_ERROR | 500 | 服务器内部错误 |
| 90001 | DEBUG_DISABLED | 403 | 调试接口已关闭 |

---

## 10. 实现示例(可直接复用)

### 10.1 完整玩法闭环(Python,urllib 标准库)

```python
"""注册 → 买种子 → 播种 → 浇水 → 收获 完整闭环。"""
import json, urllib.request

BASE = "http://127.0.0.1:8000/v1"

def call(method, path, token=None, body=None):
    req = urllib.request.Request(BASE + path, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    data = json.dumps(body).encode() if body else None
    with urllib.request.urlopen(req, data=data, timeout=10) as r:
        return json.loads(r.read())

# 1. 注册
r = call("POST", "/auth/register", body={"name": "agent_bot", "password": "pass123456"})
token = r["data"]["token"]                      # code==0 时 data.token 有效
print("注册:", r["data"]["player"]["coins"], "金币")

# 2. 推进节气到水稻宜种窗(调试接口;正式环境等节气自然轮转)
for _ in range(40):
    cal = call("GET", "/calendar/current")["data"]
    if 5 <= cal["term_index"] <= 9:             # 水稻窗 5-7 + 宽限 2
        break
    call("POST", "/debug/term/advance", token)
print("当前节气:", call("GET", "/calendar/current")["data"]["name"])

# 3. 买种子(从商店找 seed_rice,effect.crop_id 就是播种目标)
shop = call("GET", "/shop/items")["data"]["items"]
seed = next(i for i in shop if i["code"] == "seed_rice")
call("POST", f"/shop/items/{seed['item_id']}/buy", token, {"quantity": 1})

# 4. 播种第一块地
plot = call("GET", "/farm/state", token)["data"]["plots"][0]["plot_id"]
call("POST", f"/farm/plots/{plot}/sow", token, {"crop_id": seed["effect"]["crop_id"]})

# 5. 浇水 → 催熟(调试)→ 收获
call("POST", f"/farm/plots/{plot}/water", token)
call("POST", "/debug/grow", token, {"plot_id": plot})
hv = call("POST", f"/farm/plots/{plot}/harvest", token)["data"]
print(f"收获: {hv['crop_name']} ×{hv['yield']} = +{hv['coins_earned']} 金币,余额 {hv['coins_balance']}")
```

### 10.2 管理后台示例(curl)

```bash
# 登录
TOKEN=$(curl -s -X POST http://127.0.0.1:8000/v1/admin/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"admin123"}' | grep -oE '"token":"[^"]+"' | cut -d'"' -f4)

# 查全服种植状态
curl -s "http://127.0.0.1:8000/v1/admin/plantings?active=true" \
  -H "Authorization: Bearer $TOKEN"

# 新增植物(自动建种子)
curl -s -X POST http://127.0.0.1:8000/v1/admin/crops \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"name":"萝卜","category":"蔬菜","sow_window":{"type":"term","start":14,"end":16,"grace":2},"grow_seconds":700,"yield_base":4,"base_price":14,"auto_seed":true}'
```

### 10.3 Agent 行为准则

1. 调用任何 🔐 接口前,先注册/登录拿 token,放入 `Authorization` 头
2. 判断成功看 `code == 0`,不要只看 HTTP 200(业务错误 HTTP 也是 400/401/403)
3. 播种前必须确认当前节气在宜种窗(`/v1/calendar/current`);被 `21003` 拒绝时等待轮转或使用调试推进
4. 修改类操作(购买/播种/收获)失败后不要盲目重试,先读 `error_code`
5. 管理接口只用于运维与内容配置;玩家数据一律走玩家端接口
6. 时间敏感操作(收获判断)以服务端返回的 `stage`/`growth_progress` 为准,不要本地计时
