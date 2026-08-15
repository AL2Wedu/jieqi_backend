# 节气种田后端 API 文档

> **本文档是完整的接口参考:不 clone 后端源代码即可对接全部接口。**
> 每个端点含:鉴权 / 请求(路径·查询·请求体字段表)/ 请求示例 / 响应示例与字段表 / 错误码 / 注意事项。
> 配套:[README.md](README.md)(机制与部署)· [ASSETS.md](ASSETS.md)(游戏资源统一接口与全量清单)· 服务运行后 `GET /docs`(OpenAPI 交互文档)。

**当前覆盖**:88 个 REST/WS 端点 + 3 个页面端点,与代码逐一核对(校验方法见第 13 章)。

---

## 1. 文档说明与使用前提

- **独立可用**:字段表 + 示例已足够拼请求,不需要读源码。
- **阅读顺序**:
  - 新接入:第 2 章(约定)→ 第 3 章(索引)→ 第 5 章(玩家端)→ 第 9 章(WS)
  - 调 bug:第 11 章(错误码全表)
  - 管理运维:第 8 章(管理后台)
- **术语**:节气=term(1-24,立春…大寒)、地块=plot(4×5=20)、宜种窗=sow_window、收成仓=storage、单株上限=max_value、世界秒=world_accum。完整术语表见 README 第 8 章。
- **鉴权徽章**:🔓 无需登录 · 🔐 玩家 JWT · 👑 管理员 JWT · 🧪 需 `DEBUG_ENABLED=true`

---

## 2. 通用约定

### 2.1 Base URL

```
开发:http://127.0.0.1:8000/v1
生产:https://<你的域名>/v1
```

所有 REST 路径以 `/v1` 开头;WS 路径不含 `/v1` 前缀(`ws://host/v1/ws`)。

### 2.2 认证(双 JWT 体系)

| 体系 | 获取 | 有效期 | 使用方式 |
|---|---|---|---|
| 玩家 token | 注册/登录返回 `data.token` | 7 天 | HTTP Header:`Authorization: Bearer <token>` |
| 管理员 token | `POST /v1/admin/login` | 2 小时 | 同上(管理端专用) |

- WS 无法带 Header → token 走查询参数:`ws://host/v1/ws?token=<player_token>`
- 无效/过期 token:REST 返回 `401`;WS 服务端关闭码 `4401`
- **封禁即时生效**:账号被封后,已登录 token 的下一次请求也会被拒(`20004 USER_BANNED`)

### 2.3 响应信封(所有 REST 接口统一)

```json
{ "code": 0, "message": "ok", "data": { } }
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `code` | int | **业务码**:`0` = 成功;非 0 = 失败(见第 11 章全表)。**不要用 HTTP 状态判断业务成败,看 code** |
| `message` | str | 成功 `"ok"`;失败为人类可读原因 |
| `data` | any | 成功时的数据;失败时通常为 `null` |

- 失败响应同时带 `error_code`(字符串标识,如 `CROP_NOT_AVAILABLE`)。
- HTTP 状态与 code 的关系:`code=0` → HTTP 200;业务失败 → 400/401/403/404(与错误表一致);参数校验失败 → 422;未捕获异常 → 500(`90000 INTERNAL_ERROR`)。

### 2.4 分页信封(列表接口统一)

```json
{ "items": [ ], "page": 1, "page_size": 20, "total": 42 }
```

| 字段 | 说明 |
|---|---|
| `items` | 当前页数据 |
| `page` | 当前页码(从 1 开始) |
| `page_size` | 每页条数(默认 20,多数接口上限 100) |
| `total` | 总条数 |

### 2.5 ID 与时间规则

- **ID**:主键一律 UUID(字符串形式传参);前端**原样透传**,不要截断/转换。
- **时间**:ISO8601 带时区(如 `2026-08-14T12:00:00+00:00`),一律 UTC。
- **世界秒(world_accum)**:玩家世界时钟的累计秒数(管理端设置玩家世界时用)。

### 2.6 通用规则

- **只加不减**:响应 `data` 只增字段不删字段,客户端兼容旧字段即可升级。
- **JSONB 兜底**:道具效果/植物设定等开放结构用 JSON 字段承载,加配置不改接口。
- **幂等与重试**:业务写操作(播种/购买/领取)非幂等 —— 重复调用会产生重复结果,客户端对超时重试要谨慎(失败重试前先查状态)。
- **未知事件/字段一律忽略**(向前兼容)。

---

## 3. 完整端点索引(90 REST/WS + 3 页面)

### 3.1 玩家端基础(13)

| # | 方法 | 路径 | 鉴权 | 说明 |
|---|---|---|---|---|
| 1 | POST | `/v1/auth/register` | 🔓 | 注册(名字+密码)→ 返回 token + 玩家档案 |
| 2 | POST | `/v1/auth/login` | 🔓 | 登录 |
| 3 | GET | `/v1/player/me` | 🔐 | 玩家档案(金币/等级/经验/解锁节气/教学状态) |
| 4 | POST | `/v1/player/tutorial/complete` | 🔐 | 结束新手教学(恢复正常世界/虫害) |
| 5 | GET | `/v1/player/inventory` | 🔐 | 背包列表(含数量 0 的道具行) |
| 6 | POST | `/v1/player/inventory/{item_id}/use` | 🔐 | 使用道具(肥料/水壶等,需目标地块) |
| 7 | GET | `/v1/calendar/current` | 🔐 | 我的当前节气(每用户世界) |
| 8 | GET | `/v1/farm/state` | 🔐 | 农场全量状态(20 地块 + 每格作物 + 杂草标记) |
| 8 | POST | `/v1/farm/plots/{plot_id}/sow` | 🔐 | 播种(解锁→宜种窗→种子校验) |
| 9 | POST | `/v1/farm/plots/{plot_id}/water` | 🔐 | 浇水(水分补满,重新计时衰减) |
| 10 | POST | `/v1/farm/plots/{plot_id}/harvest` | 🔐 | 收获(入收成仓,不直接给金币) |
| 11 | POST | `/v1/farm/plots/{plot_id}/clear` | 🔐 | 铲除(移除当前作物,地块可再种) |
| 12 | POST | `/v1/farm/plots/{plot_id}/weed-clear` | 🔐 | 清除单个地块的杂草(只清所选格) |
| 13 | GET | `/v1/shop/state` | 🔐 | 我的商店(商品+库存+当前季节与倍率) |
| 14 | GET | `/v1/shop/items` | 🔐 | 商店商品列表(简版) |
| 15 | POST | `/v1/shop/items/{item_id}/buy` | 🔐 | 购买道具(扣金币,写账本) |
| 16 | GET | `/v1/shop/storage` | 🔐 | 收成仓(数量 + 当前季节卖价) |
| 17 | POST | `/v1/shop/crops/{crop_id}/sell` | 🔐 | 出售收成(按当前季节价结算金币) |
| 18 | GET | `/v1/player/uid/{uid_num}` | 🔐 | 按对外纯数字 ID 查任意玩家公开资料(与 social/players 同构) |
| 19 | POST | `/v1/player/rename` | 🔐 | 改名(1-16 字符,限速 rename.cooldown_seconds,默认 7 天) |
| 20 | POST | `/v1/auth/deactivate` | 🔐 | 注销账号(留档冻结,需密码+confirm,世界冻结) |
| 21 | POST | `/v1/redeem` | 🔐 | 兑换码兑换(限速+哈希匹配+原子抢占,奖励走账本) |

### 3.2 扩展玩法(13)

| # | 方法 | 路径 | 鉴权 | 说明 |
|---|---|---|---|---|
| 17 | POST | `/v1/quests/{quest_id}/claim` | 🔐 | 领取任务奖励(自动跟踪,达成才可领) |
| 42 | GET | `/v1/quests` | 🔐 | 任务列表(自动跟踪,含实时进度) |
| 18 | GET | `/v1/social/friends` | 🔐 | 好友列表 |
| 19 | GET | `/v1/social/requests` | 🔐 | 发给我的待处理申请 |
| 20 | POST | `/v1/social/requests` | 🔐 | 发送好友申请 |
| 21 | POST | `/v1/social/requests/{player_id}/accept` | 🔐 | 接受申请 |
| 22 | POST | `/v1/social/requests/{player_id}/reject` | 🔐 | 拒绝申请 |
| 23 | DELETE | `/v1/social/friends/{player_id}` | 🔐 | 删除好友 |
| 24 | POST | `/v1/achievements/{achievement_id}/claim` | 🔐 | 领取成就奖励(配置驱动自动达成) |
| 43 | GET | `/v1/achievements` | 🔐 | 成就列表(自动重算进度,达成即置 completed) |
| 25 | POST | `/v1/ai/chat` | 🔐 | AI 对话(OpenAI 兼容透传) |
| 26 | GET | `/v1/ai/models` | 🔐 | 可用模型列表(透传上游) |
| 27 | GET | `/v1/ai/usage` | 🔐 | 我的 AI 用量统计 |
| 28 | GET | `/v1/pest/state` | 🔐 | 我的虫害状态(季节/活跃窗/下次触发/进行中事件) |
| 29 | POST | `/v1/farm/pest/{pest_id}/result` | 🔐 | 大虫害提交成绩(防作弊校验+奖惩) |
| 30 | POST | `/v1/farm/pest/{pest_id}/drive-away` | 🔐 | 驱赶小虫害寄生目标 |
| 31 | POST | `/v1/shop/guest/start` | 🔐 | 开一单 AI 客人议价(1 份收成) |
| 32 | POST | `/v1/shop/guest/{session_id}/chat` | 🔐 | 跟客人对话一轮(deal=true 当场成交) |
| 33 | POST | `/v1/shop/guest/{session_id}/accept` | 🔐 | 接受客人当前报价 → 成交结算 |
| 34 | POST | `/v1/shop/guest/{session_id}/cancel` | 🔐 | 赶客放弃,不成交 |
| 35 | GET | `/v1/shop/guest/{session_id}` | 🔐 | 会话快照(含消息历史,断线重进用) |
| 36 | GET | `/v1/social/search?q=&exact=` | 🔐 | 按名字查玩家(排除自己):模糊包含 / 精确匹配(重名全返回) |
| 37 | GET | `/v1/social/players/{player_id}` | 🔐 | UUID 查询:任意玩家公开资料 + 关系状态 |
| 38 | GET | `/v1/social/players/{player_id}/farm` | 🔐 | 公开访客模式:任意玩家农场参观(田格数据,只读无副作用) |
| 38 | GET | `/v1/social/friends/{player_id}` | 🔐 | 好友资料卡(须已是好友,friends_since) |
| 39 | GET | `/v1/social/friends/{player_id}/farm` | 🔐 | 好友农场参观(只读快照,无副作用) |
| 40 | POST | `/v1/social/friends/{player_id}/water` | 🔐 | 互助浇水(预留接口,功能开发中) |
| 41 | POST | `/v1/social/friends/{player_id}/plots/{plot_idx}/steal` | 🔐 | 偷菜(预留接口,功能开发中) |

### 3.3 美术素材(3)

| # | 方法 | 路径 | 鉴权 | 说明 |
|---|---|---|---|---|
| 31 | GET | `/v1/art/version` | 🔓 | 素材版本(全局+逐作物+逐节气哈希) |
| 32 | GET | `/v1/art/manifest` | 🔓 | 素材全量清单(15 作物×4 + 24 节气 + 版本 + URL 模板) |
| 33 | GET | `/v1/art/{kind}/{key}/{name}.png?w=` | 🔓 | **统一资源接口**:crops(seed/1/2/3)或 terms(main),按分辨率选档 |
| 34 | GET | `/v1/art/terms/{term_index}.png?w=` | 🔓 | 24 节气图(1-24,兼容别名,等价 terms/{index}/main) |

### 3.3.1 通用资源接口(任意类型,👑 notify 需 admin)

> 除图片外,音频/配置等任意类型资源统一走 `/v1/assets`。`/v1/art` 保留为 `images` 别名(向后兼容)。

| # | 方法 | 路径 | 鉴权 | 说明 |
|---|---|---|---|---|
| 35 | GET | `/v1/assets/{type}/{key}/{name}.{ext}?w=` | 🔓 | **通用资源接口**:type∈{images,audio,config}(注册表声明),key 可多级(如 crops/shuidao),图片走预渲染选档 |
| 36 | GET | `/v1/assets/version` | 🔓 | 全局资源版本(逐类型/逐资源哈希) |
| 37 | GET | `/v1/assets/manifest` | 🔓 | 资源全量清单(按类型分组 + URL 模板 + 版本) |
| 38 | POST | `/v1/assets/notify` | 👑 | 资源更新后向全服广播 `asset_update`(客户端按 url 拉取强制更新) |

### 3.4 调试接口(7,🧪 全部需 `DEBUG_ENABLED=true` + 🔐)

| # | 方法 | 路径 | 说明 |
|---|---|---|---|
| 34 | POST | `/v1/debug/config` | 热改全局配置(game_config) |
| 35 | POST | `/v1/debug/term/advance` | 推进节气(只影响自己) |
| 36 | POST | `/v1/debug/grow` | 催熟指定地块 |
| 37 | POST | `/v1/debug/pest/trigger` | 强制触发一次虫害(big/small) |
| 38 | POST | `/v1/debug/pest/clear` | 清除我的全部虫害 |
| 39 | POST | `/v1/debug/weed/trigger` | 强制触发一次杂草生长 |
| 40 | POST | `/v1/debug/weed/clear` | 清除我的全部杂草 |

### 3.4.1 资源清单接口(1,🔐 需玩家登录 token)

| # | 方法 | 路径 | 说明 |
|---|---|---|---|
| 41 | GET | `/v1/dev/assets` | 完整资源清单(遍历 assets 目录树:path/url/size,开发联调与客户端共用) |

> **认证**:`Authorization: Bearer <玩家登录 JWT>`(与玩家端接口一致,见 §3.1;无效/过期返回 401)。

### 3.5 管理后台(41,👑 全部需 admin token)

| # | 方法 | 路径 | 说明 |
|---|---|---|---|
| 41 | POST | `/v1/admin/login` | 管理员登录(密码为空拒登) |
| 42 | GET | `/v1/admin/dashboard` | 仪表盘统计 |
| 43 | GET | `/v1/admin/env` | 系统环境变量(敏感打码) |
| 44 | GET | `/v1/admin/users` | 用户列表(分页) |
| 45 | PATCH | `/v1/admin/users/{user_id}/status` | 封禁/解封 |
| 46 | GET | `/v1/admin/users/{user_id}/assets` | 玩家资产(弹窗预填) |
| 47 | PATCH | `/v1/admin/users/{user_id}/assets` | 编辑玩家资产(推 resources_changed) |
| 48 | GET | `/v1/admin/config` | 全局配置列表(game_config) |
| 49 | PUT | `/v1/admin/config/{key}` | 写全局配置 |
| 50 | DELETE | `/v1/admin/config/{key}` | 删全局配置 |
| 51 | GET | `/v1/admin/crops` | 植物列表 |
| 52 | POST | `/v1/admin/crops` | 新增植物(可 auto_seed,写回设定文件) |
| 53 | PUT | `/v1/admin/crops/{crop_id}` | 编辑植物(写回设定文件) |
| 54 | DELETE | `/v1/admin/crops/{crop_id}` | 软删除植物(有种植中则拒) |
| 55 | GET | `/v1/admin/plantings` | 全服种植状态(每株实时) |
| 56 | GET | `/v1/admin/items` | 道具列表 |
| 57 | POST | `/v1/admin/items` | 新增道具 |
| 58 | PUT | `/v1/admin/items/{item_id}` | 编辑道具 |
| 59 | DELETE | `/v1/admin/items/{item_id}` | 删除道具(软删) |
| 60 | GET | `/v1/admin/terms` | 节气列表(24) |
| 61 | PUT | `/v1/admin/terms/{term_index}` | 修改节气时长 |
| 62 | PUT | `/v1/admin/clock` | 时钟(全局默认倍速/暂停) |
| 63 | GET | `/v1/admin/users/{user_id}/farm` | 某用户农场 |
| 64 | PUT | `/v1/admin/users/{user_id}/plots/{plot_idx}` | 地块(锁定/肥力) |
| 65 | PUT | `/v1/admin/users/{user_id}/plots/{plot_idx}/crop` | 种/替换作物(不校验窗,不耗种子) |
| 66 | DELETE | `/v1/admin/users/{user_id}/plots/{plot_idx}/crop` | 清除地块作物 |
| 67 | PUT | `/v1/admin/users/{user_id}/plots/{plot_idx}/growth` | 调整生长进度/水分 |
| 68 | GET | `/v1/admin/users/{user_id}/inventory` | 某用户背包 |
| 69 | PUT | `/v1/admin/users/{user_id}/inventory/{item_id}` | 设定道具数量(绝对值) |
| 70 | GET | `/v1/admin/users/{user_id}/storage` | 某用户收成仓 |
| 71 | PUT | `/v1/admin/users/{user_id}/storage/{crop_id}` | 设定收成数量 |
| 72 | GET | `/v1/admin/worlds` | 每用户世界列表(节气位置) |
| 73 | PUT | `/v1/admin/worlds/{player_id}` | 覆盖/重置玩家世界 |
| 74 | GET | `/v1/admin/shop/settings` | 全局商店默认 |
| 75 | PUT | `/v1/admin/shop/settings` | 保存全局商店默认 |
| 76 | GET | `/v1/admin/shop/users` | 全部用户商店摘要 |
| 77 | GET | `/v1/admin/shop/users/{player_id}/items` | 某用户商店商品 |
| 78 | PUT | `/v1/admin/shop/users/{player_id}/items/{item_id}` | 覆盖商品(库存/买卖价) |
| 79 | POST | `/v1/admin/shop/users/{player_id}/restock` | 手动补货 |
| 88 | GET | `/v1/admin/guests` | AI 客人会话列表(可过滤状态,分页) |
| 89 | POST | `/v1/admin/shop/users/{player_id}/reset` | 重置商店 |
| 90 | GET | `/v1/admin/ai/config` | AI 配置(密钥打码) |
| 91 | PUT | `/v1/admin/ai/config` | 保存 AI 配置 |
| 92 | POST | `/v1/admin/ai/test` | AI 连通性测试 |
| 93 | GET | `/v1/admin/ai/usage` | 全服 AI 用量 |
| 94 | GET | `/v1/admin/pest/config` | 虫害系统配置 |
| 95 | PUT | `/v1/admin/pest/config` | 保存虫害配置 |
| 96 | GET | `/v1/admin/pest/events` | 虫害事件记录 |
| 97 | POST | `/v1/admin/redeem/codes` | 发布兑换码(单个/批量,明文只回一次,库存哈希) |
| 98 | GET | `/v1/admin/redeem/codes` | 兑换码列表(运营视图:前 6 位 hint + 用量/状态) |
| 99 | PUT | `/v1/admin/redeem/codes/{code_id}` | 更新兑换码(停用/启用/次数/过期) |
| 100 | PUT | `/v1/admin/users/{user_id}/rename` | 管理端改名(无限速,同步 User+Player) |

### 3.6 WebSocket 与页面(2 WS + 3 页面)

| # | 类型 | 路径 | 鉴权 | 说明 |
|---|---|---|---|---|
| 97 | WS | `/v1/ws?token=` | 🔐 | 玩家实时推送(节气+7 类事件) |
| 98 | WS | `/v1/admin/logs?token=` | 👑 | 后端日志实时流(只读) |
| — | GET | `/admin` | 页面 | 管理后台单页 |
| — | GET | `/docs` | 页面 | OpenAPI 交互文档 |
| — | GET | `/static/*` | 静态 | 美术素材/前端资源 |
---

## 4. 端点详解模板(本文件统一格式)

每个端点一节,固定结构:

```
### X.Y <METHOD> /v1/<path> — 中文名(鉴权徽章)
**鉴权:** 说明
**请求:**
- 路径参数:字段 | 类型 | 必填 | 说明
- 查询参数:字段 | 类型 | 必填 | 默认 | 说明
- 请求体:字段 | 类型 | 必填 | 约束 | 默认 | 说明
**请求示例:** ```json {...}```
**响应(data):** 字段 | 类型 | 说明(附完整示例)
**错误:** code | error_code | HTTP | 触发条件
**注意事项:** 副作用/时序依赖/相关端点
```

- 请求体字段表中"必填"为 ✅;未列出 = 非必填。
- 所有响应 `data` 均包在信封 `{code,message,data}` 内(第 2.3 节),下文只写 `data` 内容。

---

## 5. 玩家端端点详解

### 5.1 POST /v1/auth/register — 注册(🔓)

**请求体:**

| 字段 | 类型 | 必填 | 约束 | 说明 |
|---|---|---|---|---|
| `name` | str | ✅ | 1-32 字符 | 登录名(也是显示名),**全局唯一** |
| `password` | str | ✅ | 6-64 字符 | 明文传输(HTTPS 下),服务端 PBKDF2 哈希存储 |

**请求示例:**

```json
{ "name": "demo01", "password": "pass123456" }
```

**响应(data):**

| 字段 | 类型 | 说明 |
|---|---|---|
| `token` | str | 玩家 JWT(7 天),后续请求 `Authorization: Bearer <token>` |
| `player` | object | 玩家档案(字段见下表) |

`player` 字段: `player_id`(UUID)/ `name` / `level` / `exp` / `coins` / `head_title_id`(无则 null)/ `unlocked_term_index` / `farm_id` / `plot_count`(20)/ `register_location`(IP 地理,可能为空)/ `last_login_location`

```json
{
  "code": 0, "message": "ok",
  "data": {
    "token": "eyJhbGciOiJIUzI1NiIs...",
    "player": { "player_id": "1a2b...", "name": "demo01", "level": 1, "exp": 0,
                "coins": 200, "head_title_id": null, "unlocked_term_index": 1,
                "farm_id": "9f8e...", "plot_count": 20,
                "register_location": "中国·广东省", "last_login_location": null }
  }
}
```

**错误:** `10001 INVALID_PARAMS`(参数不合法)

**注意事项:** 副作用 = 自动创建玩家(初始金币 **200**)、农场(**20 地块,4×5**)、`coin_transactions` 记 `register` 账、IP 落库并解析地理位置。**允许重名**(班级同名场景):重名账号靠密码区分,见 5.2 登录双匹配。

### 5.2 POST /v1/auth/login — 登录(🔓)

**请求体:** `name` / `password`(同注册)。

**响应(data):** 同注册(`token` + `player`)。登录取到 token 后应缓存,过期(7 天)重新登录。

**错误:** `20002 USER_NOT_FOUND`(用户不存在)· `20003 BAD_CREDENTIALS`(密码错误)· `20004 USER_BANNED`(已封禁,HTTP 403)· `20006 NAME_CONFLICT`(同名多账号且密码相同,登录歧义)

**注意事项:** 名字可重名 → **密码双匹配**:同名的所有账号中,密码匹配且唯一命中的那个才登录;同名同密码 → 20006(需改其中一个密码)。

### 5.3 GET /v1/player/me — 玩家档案(🔐)

**请求:** 无参数。

**响应(data):** 同注册的 `player` 对象(不含 token),含 `tutorial`(新手教学状态)。

**错误:** `10002 UNAUTHORIZED`(未登录/玩家不存在)· `10003 UNAUTHORIZED`(token 过期)· `20004 USER_BANNED`(被封禁,HTTP 403)

**注意事项:** 收到 WS `resources_changed` 事件后**必须重新调用本接口**获取权威数值。

### 5.3.1 GET /v1/player/uid/{uid_num} — 按数字 ID 查公开资料(🔐)

**请求:** 路径参数 `uid_num`(纯数字,7 位)。

**响应(data):** 与 `/v1/social/players/{player_id}` 同构的公开资料 + `relation`(与我的关系状态)。

**错误:** `20013 UID_NOT_FOUND`(数字 ID 不存在)· `10002 UNAUTHORIZED`

### 5.3.2 POST /v1/player/rename — 改名(🔐)

**请求体:** `new_name`(1-16 字符)。

**响应(data):** `{ "name", "rename_last_at", "next_rename_at" }`

**错误:** `10001 INVALID_PARAMS`(长度非法/与旧名相同)· `20008 RENAME_TOO_FREQUENT`(限速内,响应带剩余秒数)· `20004 USER_BANNED`· `20007 USER_DEACTIVATED`

**注意事项:** 限速 `rename.cooldown_seconds`(默认 7 天,后台可调);同步改 `User.name` + `Player.name`。

### 5.3.3 POST /v1/auth/deactivate — 注销账号(🔐)

**请求体:** `password`(当前密码)+ `confirm`(必须 true)。

**响应(data):** `{ "deactivated": true, "deactivated_at" }`

**错误:** `20003 BAD_CREDENTIALS`(密码错误)· `10001 INVALID_PARAMS`(confirm 非 true)· `20004 USER_BANNED`

**注意事项:** 注销=留档冻结(数据不删),世界停止推进;注销后 token 立即失效,无法再登录。

### 5.3.4 POST /v1/redeem — 兑换码兑换(🔐)

**请求体:** `code`(6-24 位 [A-Z0-9])。

**响应(data):** `{ "reward": {coins, exp, items}, "claimed_at" }`

**错误:** `20009 REDEEM_RATE_LIMITED`(限速内)· `20010 REDEEM_INVALID`(无效/停用/过期,统一)· `20011 REDEEM_CLAIMED`(已兑换过)· `20012 REDEEM_EXHAUSTED`(已用完)

**注意事项:** 限速 `redeem.cooldown_seconds`(默认 60s,成功失败都算);奖励走账本(金币/经验/道具)。

### 5.3b POST /v1/player/tutorial/complete — 结束新手教学(🔐)

**请求:** 无请求体。

**响应(data):** `{ "tutorial": false, "already_completed": bool }`(`already_completed=true`=本已结束,幂等)。

**错误:** `10002/10003 UNAUTHORIZED` · `20004 USER_BANNED`

**注意事项:** 新手教学期间玩家世界**恒为清明**(首个可播种节气,节气不推进)、**不产生虫害**;调用本接口后恢复正常世界时钟与虫害调度(世界从清明无缝续跑,虫害排程清空后按季节重排)。

### 5.4 GET /v1/player/inventory — 背包(🔐)

**响应(data):** `{ "items": [...] }`

| 字段 | 类型 | 说明 |
|---|---|---|
| `items[].item_id` | str | 道具 UUID |
| `items[].code` | str | 道具稳定标识(如 `seed_shuidao`) |
| `items[].name` | str | 道具名 |
| `items[].category` | str | 分类(seed/tool/…) |
| `items[].quantity` | int | 数量(**含 0 的行**,客户端按 quantity 显示) |
| `items[].effect` | object | 效果定义(见 10.1) |

### 5.5 POST /v1/player/inventory/{item_id}/use — 使用道具(🔐)

**路径参数:** `item_id` — 道具 UUID。

**请求体:**

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `target.plot_id` | str | 视道具 | 目标地块(肥料/水壶需要) |

**请求示例:** `{ "target": { "plot_id": "3f2a..." } }`

**响应(data):** 按效果分发:

| effect.type | 效果 | data |
|---|---|---|
| `water` | 浇水 | `{ "effect_applied": { "water_level": 100 } }` |
| `boost` | 肥料加速 50% | `{ "effect_applied": { "boost_pct": 50 } }` |
| `seed` | — | 拒绝(提示用播种接口) |
| `term_lock` | — | ⚠️ 未实现,拒绝 |

**错误:** `22002 ITEM_NOT_FOUND`(道具不存在)· `22001 NOT_ENOUGH_ITEM`(数量不足)· `22004 EFFECT_NOT_SUPPORTED`(效果不支持/未实现)· `21001 PLOT_NOT_FOUND`(目标地块不存在)

### 5.6 GET /v1/calendar/current — 我的当前节气(🔐)

**响应(data):**

| 字段 | 类型 | 说明 |
|---|---|---|
| `term_index` | int | 节气序号 1-24(1=立春 … 24=大寒) |
| `name` | str | 节气名 |
| `cycle` | int | 轮次(第几圈循环) |
| `remaining_sec` | int | 本节气剩余秒(按我的世界倍速) |

**注意事项:** 返回的是**该玩家自己世界**的节气(离线减速后与他人不同步);节气切换会经 WS 推送 `solar_term_change`。

### 5.7 GET /v1/farm/state — 农场状态(🔐)

**响应(data):**

| 字段 | 类型 | 说明 |
|---|---|---|
| `farm.farm_id / name / plot_count / grid` | — | 农场信息(`grid={cols:4, rows:5}`,地块 idx 行优先) |
| `current_term` | object | 同 5.6 |
| `wither_events` | array | 本次读取时**新枯萎(冻死)**的作物 `[{plot_id, idx, crop_name, status:"wilted"}]`(空数组=无);作物仍在地块,不消失 |
| `weed_events` | array | 本次读取时新长的杂草地块 `[{plot_id, idx}]` |
| `plots[]` | array | 20 个地块 |

`plots[]` 字段: `plot_id` / `idx`(1-20)/ `soil_quality`(1-3)/ `locked` / `weeded`(bool,**附杂草 → 该地块作物生长减速**)/ `crop`(null=空地)

`plots[].crop` 字段: `crop_id` / `name` / `art`(种子+三阶段素材路径)/ `settings`(植物高级设定,见 10.4)/ `stage`(1 苗期/2 生长期/3 成熟)/ `status`(`growing` 生长中 / `mature` 成熟 / `wilted` **枯萎冻死**——仍占地块,待铲除或收割)/ `growth_progress`(0-100)/ `water_level`(0-100,**已衰减后的有效值**)/ `water_need`(需水红线)/ `predicted_harvest_at`

**注意事项:** ① 本接口有**副作用**:会执行枯萎判定与杂草触发检查(到点即落库),并返回对应事件;② **枯萎作物不直接消失**:`status="wilted"` 提示"植物冻死了",玩家可 `clear` 铲除或 `harvest` 收割(减产入劣质仓);③ `crop.settings` 供客户端展示需水/枯萎季节等;④ 作物素材取图闭环见 10.3。

### 5.8 POST /v1/farm/plots/{plot_id}/sow — 播种(🔐)

**路径参数:** `plot_id` — 地块 UUID(从 farm/state 获取)。

**请求体:**

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `crop_id` | str | ✅ | 作物 UUID(从商店种子的 `effect.crop_id` 获取) |

**响应(data):** `plot_id` / `crop_id` / `crop_name` / `sowed_term_index` / `predicted_harvest_at` / `grow_seconds_eff`(加速后的有效生长时长)/ `season_boost`(加速倍率,无加速为 null)

**校验顺序(任一失败即拒绝):**

| 顺序 | 检查 | 失败错误 |
|---|---|---|
| 1 | 作物存在且 active | `21005 CROP_NOT_FOUND` |
| 2 | 地块存在且未锁定、属于我 | `21001 PLOT_NOT_FOUND` |
| 3 | 地块无未收获作物 | `21002 PLOT_OCCUPIED` |
| 4 | 解锁(经验或等级其一) | `21008 CROP_LOCKED` |
| 5 | 当前节气 ∈ 宜种窗(+grace 宽限) | `21003 CROP_NOT_AVAILABLE` |
| 6 | 有对应种子道具 | `21005 SEED_NOT_FOUND` |
| 7 | 种子数量 ≥ 1 | `21006 NOT_ENOUGH_ITEM` |

**错误:** 见上表;另 `10001 INVALID_PARAMS`。

**注意事项:** ① 播种自动消耗 1 个种子(写 `item_transactions` 账本);② 播种 = 翻地整地 → 清除该地块的杂草;③ 在植物加速季节播种 → `grow_seconds_eff` 缩短(如水稻夏季 300→200);④ 生长阶段/进度由服务器时间推导,客户端不可伪造。

### 5.9 POST /v1/farm/plots/{plot_id}/water — 浇水(🔐)

**路径参数:** `plot_id`。

**响应(data):** `{ "plot_id": "...", "water_level": 100 }`

**错误:** `21001 PLOT_NOT_FOUND` · `21004 PLOT_EMPTY`(地块无作物)· `21009 CROP_WILTED`(作物已枯萎冻死,无法浇水,HTTP 400)

**注意事项:** 浇水后水分从 100 重新衰减(每节气 -10);低于作物 `water_need.min` → 生长停滞。枯萎作物已死,浇水会被拒绝。

### 5.10 POST /v1/farm/plots/{plot_id}/harvest — 收获(🔐)

**路径参数:** `plot_id`。

**响应(data):** `plot_id` / `crop_id` / `crop_name` / `wilted`(是否枯萎抢收)/ `yield`(实际产量,已含肥力加成/减产/枯萎减半)/ `storage_after`(收成仓该作物总量)/ `exp_gained`(收获经验 = 产量×2)/ `level`(收获后等级)/ `leveled_up`(本次是否升级)/ `note`(提示文案)

**错误:** `21001 PLOT_NOT_FOUND` · `21004 PLOT_EMPTY` · `23001 CROP_NOT_MATURE`(未成熟,HTTP 400;枯萎作物不受此限)

**注意事项:** ① 产量公式:`yield_base × (1 + 0.1×(肥力-1))`,土壤肥力 < `fertility_need` 再乘 `(soil/need)` 减产;**枯萎作物收割再 ×0.5**,且**不必成熟**也可抢收(抢救性收割);② 收成**入收成仓**(不直接给金币),枯萎收成计入 `wilted_quantity`(劣质),出售时收购价大打折扣(×0.3);③ **每株收成 +2 经验**,累计 100 经验自动升 1 级(`exp//100+1`,只升不降),客户端可用 `leveled_up` 弹升级提示;④ 收获后地块可再种(历史记录保留)。

### 5.11 POST /v1/farm/plots/{plot_id}/clear — 铲除(🔐)

**路径参数:** `plot_id`。

**响应(data):** `{ "plot_id": "...", "cleared": true, "wilted": false }`(`wilted`=铲除的作物是否为枯萎状态)

**错误:** `21001 PLOT_NOT_FOUND` · `21004 PLOT_EMPTY`

**注意事项:** 铲除 = 移除当前作物(无产量),地块立即可再种;枯萎(冻死)作物**占用地块**,需铲除或收割后才能再种。

### 5.11b POST /v1/farm/plots/{plot_id}/weed-clear — 清除单格杂草(🔐)

**路径参数:** `plot_id` — 地块 UUID(从 farm/state 获取)。

**响应(data):** `{ "plot_id": "...", "idx": 1-20, "cleared": bool }`(`cleared=true`=该格原本有杂草且已清除;`false`=原本无杂草,幂等无操作)

**错误:** `21001 PLOT_NOT_FOUND`(地块不存在/不属于我)

**注意事项:** ① 只清**所选格**的杂草,不影响其他地块;② 清除后该格作物不再受杂草减速(生长速率恢复);③ 播种(翻地)也会清该格杂草;杂草会**累积**(不除一直在),全农场有总量上限 `weed.max_total`(杂草系统见 README 2.x)。

### 5.12 GET /v1/shop/state — 我的商店(🔐)

**响应(data):**

| 字段 | 类型 | 说明 |
|---|---|---|
| `season` | str | 当前季节(spring/summer/autumn/winter) |
| `restocked` | bool | 本次请求是否触发了自动补货 |
| `restock_seconds` | int | 补货周期 |
| `items[]` | array | 商品:`item_id/code/name/category/effect/stock(库存)/buy_price(公式价或覆盖价)/sell_price` |
| `crop_quotes[]` | array | 作物收购报价:`crop_id/name/category/base_price/sell_price(当前季节收购价)/season/season_factor` |

**注意事项:** ① 每个玩家独立库存,售空不共享;② 道具价 = `base × item_factor`;作物收购价 = `base × sell_factor × season_effect × category_factor`,且 **≤ 植物 max_value**;③ 管理后台可逐用户覆盖商品(见 8.26)。

### 5.13 GET /v1/shop/items — 商店商品(简版)(🔐)

**响应(data):** `{ "items": [...] }`,字段同 5.12 的 `items[]`。

**注意事项:** 与 5.12 的差异:不含季节/补货/作物报价信息,适合"只要商品列表"的场景。

### 5.14 POST /v1/shop/items/{item_id}/buy — 购买(🔐)

**路径参数:** `item_id`。

**请求体:**

| 字段 | 类型 | 必填 | 约束 | 说明 |
|---|---|---|---|---|
| `quantity` | int | 否 | 1-999 | 默认 1 |

**响应(data):** `item_id` / `code` / `name` / `quantity`(本次购买量)/ `price`(总价)/ `unit_price` / `coins_balance`(购买后余额)/ `stock_after`(商店剩余库存)

**错误:** `22002 ITEM_NOT_FOUND`(商品不存在)· `22003 NOT_ENOUGH_COINS`(金币不足)· `22006 SOLD_OUT`(售罄,若有)· `10001 INVALID_PARAMS`

**注意事项:** 扣金币 + 背包加数量,均写账本(`coin_transactions` / `item_transactions`)。

### 5.15 GET /v1/shop/storage — 收成仓(🔐)

**响应(data):** `season`(当前季节)+ `items[]`:

| 字段 | 类型 | 说明 |
|---|---|---|
| `crop_id` | str | 作物 UUID |
| `name` | str | 作物名 |
| `quantity` | int | 仓内总数量(正常 + 枯萎劣质,0 的不返回) |
| `wilted_quantity` | int | 其中**枯萎劣质收成**的数量(售价大打折扣) |
| `sell_price` | int | **当前季节**单株正常收购价(已含 max_value 封顶) |
| `wilted_sell_price` | int | 枯萎劣质收成单株收购价(= 正常价 × 0.3) |

### 5.16 POST /v1/shop/crops/{crop_id}/sell — 出售收成(🔐)

**路径参数:** `crop_id`。

**请求体:**

| 字段 | 类型 | 必填 | 约束 | 说明 |
|---|---|---|---|---|
| `quantity` | int | 否 | ≥1 | 默认 1 |

**响应(data):** `crop_id` / `name` / `quantity` / `wilted`(本次卖出中枯萎劣质收成的数量)/ `price`(总价)/ `unit_price`(混合单价)/ `storage_after`(仓内剩余,含正常+枯萎)/ `coins_balance`(出售后余额)

**错误:** `21005 CROP_NOT_FOUND` · `22007 NOT_ENOUGH_CROP`(仓内不足,HTTP 400)· `10001 INVALID_PARAMS`

**注意事项:** 按当前季节价结算(秋 1.2 倍最赚/冬 0.9 倍最亏),金币写账本;**出售先扣正常收成(原价),不足再扣枯萎劣质收成(×0.3 大打折价)**。

### 5.17 AI 客人议价出售(🔐,主玩法)

玩家与 LLM 扮演的客人**自然语言讨价还价**卖收成(1 份/单);旧快速卖出(5.16)保留为兜底。

**接口一览:**

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/v1/shop/guest/start` | body `{crop_id}` → 随机客人 + 开场白 + 初始报价 |
| POST | `/v1/shop/guest/{session_id}/chat` | body `{message}` → AI 回复一轮 |
| POST | `/v1/shop/guest/{session_id}/accept` | 接受客人当前报价 → 成交结算 |
| POST | `/v1/shop/guest/{session_id}/cancel` | 赶客,不成交 |
| GET | `/v1/shop/guest/{session_id}` | 快照(含全部消息历史,断线重进) |

**chat 响应(data)字段:**

| 字段 | 类型 | 说明 |
|---|---|---|
| `reply_text` | str | 客人回复(自然口语) |
| `guest_name` | str | 客人名字(王奶奶/陈大厨/小美,随机) |
| `mood` | str | `plain/happy/sad/confused`(服务端校验,非法兜底 plain) |
| `offer` | int | 客人当前报价(**服务端校验后**:∈ [市场价×0.5, 市场价×1.5],越界截断) |
| `deal` | bool | 是否接受玩家报价成交;`false` → 对话继续 |
| `status` | str | `bargaining/done/closed/cancelled` |

**状态机:**

```
bargaining --deal=true(chat 内)或 accept--> done(按校验后 offer 结算)
bargaining --turns ≥ max_turns(默认 8)--> closed(不自动成交)
bargaining --cancel--> cancelled
```

**结算:** 复用 `_settle_sale`(先扣正常后扣枯萎,枯萎按 offer×wilted_ratio 折价);金币 + `coin_transactions`(reason=`guest_sell:<guest_key>`)。

**成本控制:** 每玩家同时最多 1 个活跃会话(`29001 GUEST_BUSY`);start 冷却 `guest.cooldown_seconds`(默认 30s,`29002`);`guest.max_turns` 轮次上限;历史截断 `guest.context_messages`(默认 12 条);AI 用量自动进 `ai_usage`。

**错误:** `29001`-`29007`(见错误码表)· `22007 NOT_ENOUGH_CROP`(收成仓无货)· `21005 CROP_NOT_FOUND`

**客人模板:** `server/data/guests.json`(3 个:王奶奶 0.6-0.9 / 陈大厨 0.95-1.3 / 小美 0.75-1.05,心理价位 = 市场价 × 随机系数,会话创建时定死)。管理后台可调 `guest.*` 配置与开关。

### 5.18 社交查询与好友互动(🔐)

**名字搜索(找人加好友的入口):**

```
GET /v1/social/search?q=<关键词>&exact=<true|false>&limit=<默认20,≤50>
→ { "items": [ { "player_id", "name", "level", "unlocked_term_index", "farm_name", "last_active_at" } ] }
```

- `q` 必填,模糊匹配 `User.name`(排除自己),按最近活跃排序;空词 → `10001`

**UUID 查询(任意玩家公开资料 + 关系):**

```
GET /v1/social/players/{player_id}
→ { "player_id", "name", "level", "unlocked_term_index", "farm_name", "last_active_at", "relation" }
```

- `relation`:`none`(无关系)/ `pending_out`(我发过申请)/ `pending_in`(对方申请我)/ `friends` / `self`
- 不存在 → `20002 USER_NOT_FOUND`

**好友资料卡(须已是好友):** `GET /v1/social/friends/{player_id}` → 同上 + `friends_since`(成为好友时间);非好友 → `27005`

**好友农场参观(只读,无副作用):**

```
GET /v1/social/friends/{player_id}/farm
→ { "farm": { "farm_id", "name", "plot_count", "owner": {...公开资料} },
    "plots": [ { "plot_id", "idx", "soil_quality", "locked", "weeded", "crop": {...同 farm/state 的 crop 视图} } ] }
```

- 只读快照:**不触发**枯萎/杂草/虫害等任何状态变更(与玩家自己 `GET /v1/farm/state` 的副作用区分)
- 非好友 → `27005`

**公开访客模式(任意玩家,只读无副作用,田格数据同上 —— 为"帮忙浇水"提供前置数据):**

```
GET /v1/social/players/{player_id}/farm
```

- 不要求好友关系:通过用户名/UUID 找到对方即可参观其田格;浇水/偷菜等副作用动作仍仅限好友

**预留互动接口(契约已定,功能开发中):**

| 方法 | 路径 | 未来契约(开发中) |
|---|---|---|
| POST | `/v1/social/friends/{player_id}/water` | 帮好友浇水 → `{friend_player_id, watered_plot_count, cooldown_seconds}`(需冷却限制,防刷) |
| POST | `/v1/social/friends/{player_id}/plots/{plot_idx}/steal` | 偷好友成熟作物 → `{friend_player_id, plot_idx, stolen_crop, stolen_quantity, daily_remaining}`(需每日上限) |

当前返回:`{ "feature": "water|steal", "enabled": false, "message": "开发中,敬请期待" }`(code=0,前端可先渲染禁用态按钮);已校验好友关系(非好友 → `27005`)。

---

## 6. 扩展玩法端点详解

### 6.0 GET /v1/quests — 任务列表(🔐)

**请求:** 无参数。

**响应(data):** `{ "items": [{ "quest_id", "code", "name", "desc", "progress", "target", "completed", "claimed", "reward" }] }`(自动跟踪,含实时进度)。

**错误:** `10002 UNAUTHORIZED`

### 6.1 POST /v1/quests/{quest_id}/claim — 领取任务奖励(🔐)

**路径参数:** `quest_id` — 任务 UUID。

**请求:** 无请求体。

**响应(data):**

| 字段 | 类型 | 说明 |
|---|---|---|
| `quest_id` | str | 任务 UUID |
| `code` | str | 任务稳定标识 |
| `reward` | object | 实际发放的奖励(见下) |
| `coins_balance` | int | 领取后金币余额 |

`reward` 结构: `{coins?, exp?, items?: [{code, quantity}]}`(按任务配置发放)。

**错误:** `25001 QUEST_NOT_FOUND` · `25002 QUEST_NOT_COMPLETE`(未达成,HTTP 400)· `25003 QUEST_ALREADY_CLAIMED`

**注意事项:** ① 任务**自动跟踪**,无需接取 —— 服务器按玩家行为实时计算进度;② 领取前会**重算一次进度**(防止客户端伪造);③ 奖励走账本。

### 6.2 GET /v1/social/friends — 好友列表(🔐)

**响应(data):** `{ "items": [{ "player_id", "name" }] }`

### 6.3 GET /v1/social/requests — 待处理申请(🔐)

**响应(data):** `{ "items": [{ "player_id", "name", "created_at" }] }`(发给我的、未处理的申请)。

### 6.4 POST /v1/social/requests — 发送好友申请(🔐)

**请求体:**

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `player_id` | str | ✅ | 目标玩家 UUID |

**响应(data):** `{ "status": 0, "target_player_id": "..." }`

**错误:** `20002 USER_NOT_FOUND` · `10001 INVALID_PARAMS`(不能加自己)· `27001 ALREADY_FRIENDS` · `27002 REQUEST_EXISTS`(申请已发送,等待处理)

**注意事项:** 曾被拒绝的好友可重新申请。

### 6.5 POST /v1/social/requests/{player_id}/accept — 接受申请(🔐)

**路径参数:** `player_id` — 申请方玩家 UUID。

**响应(data):** `{ "status": 1, "target_player_id": "..." }`

**错误:** `27003 REQUEST_NOT_FOUND`(没有该申请)

### 6.6 POST /v1/social/requests/{player_id}/reject — 拒绝申请(🔐)

**响应(data):** `{ "status": -1, "target_player_id": "..." }`

**错误:** `27003 REQUEST_NOT_FOUND`

### 6.7 DELETE /v1/social/friends/{player_id} — 删除好友(🔐)

**响应(data):** `{ "removed_player_id": "..." }`

**错误:** `27004 NOT_FRIENDS`(非好友关系)

### 6.7.1 GET /v1/achievements — 成就列表(🔐)

**请求:** 无参数。

**响应(data):** `{ "items": [{ "achievement_id", "code", "name", "desc", "progress", "target", "completed", "claimed", "reward", "head_title_id" }] }`(自动重算进度,达成即置 completed)。

**错误:** `10002 UNAUTHORIZED`

### 6.8 POST /v1/achievements/{achievement_id}/claim — 领取成就奖励(🔐)

**路径参数:** `achievement_id`。

**响应(data):** `achievement_id` / `code` / `reward` / `coins_balance`(结构同 6.1)。

**错误:** `26001 ACHIEVEMENT_NOT_FOUND` · `26002 ACHIEVEMENT_NOT_COMPLETE` · `26003 ACHIEVEMENT_ALREADY_CLAIMED`

**注意事项:** 成就**配置驱动自动达成**(达成条件与任务同格式),领奖前重算;部分成就奖励为头衔(解锁 `head_title_id`)。

### 6.9 POST /v1/ai/chat — AI 对话(🔐)

**请求体(OpenAI 兼容,透传上游):**

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `messages` | array | ✅ | `[{role, content}]`(role: system/user/assistant) |
| `model` | str | 否 | 缺省用管理后台配置的默认模型 |
| 其他 | — | 否 | temperature 等 OpenAI 参数原样透传 |

**请求示例:**

```json
{ "messages": [ { "role": "user", "content": "谷雨适合种什么?" } ] }
```

**响应(data):** 上游完整响应(OpenAI 格式):`{ id, object, choices: [{message, finish_reason}], usage: {prompt_tokens, completion_tokens, total_tokens} }`。

**错误:** `24001 AI_DISABLED`(未启用)· `24002 AI_NOT_CONFIGURED`(APIKEY/地址未配置)· `24003 AI_UPSTREAM_ERROR`(上游连接失败/非 200)

**注意事项:** ① 每次调用自动记录用量(按玩家+按天);② 本接口**透传**请求/响应 —— 客户端按 OpenAI 协议解析即可;③ 上游超时 60 秒。

### 6.10 GET /v1/ai/models — 模型列表(🔐)

**响应(data):** `{ "models": ["deepseek-chat", ...] }`(透传上游 /models 的 id 列表)。

**错误:** `24002 AI_NOT_CONFIGURED` · `24003 AI_UPSTREAM_ERROR`

### 6.11 GET /v1/ai/usage — 我的 AI 用量(🔐)

**响应(data):**

| 字段 | 类型 | 说明 |
|---|---|---|
| `total` | object | 累计:`requests / prompt_tokens / completion_tokens / total_tokens` |
| `by_day` | array | 按天明细:`[{date, model, requests, prompt_tokens, completion_tokens, total_tokens}]` |

### 6.12 GET /v1/pest/state — 我的虫害状态(🔐)

**响应(data):**

| 字段 | 类型 | 说明 |
|---|---|---|
| `enabled` | bool | 虫害系统是否启用 |
| `season` | str | 当前玩家世界季节(spring/summer/autumn/winter) |
| `pest_active` | bool | 当前节气是否在虫害活跃窗口(冬季/早春=无虫) |
| `next_pest_at` | str\|null | 下次触发时间(ISO8601) |
| `active_big` | object\|null | 进行中的大虫害:`{pest_id, duration_seconds, elapsed_seconds}` |
| `active_small` | array | 寄生目标:`[{pest_id, plot_id, idx, ready_at, remaining_sec}]` |

### 6.13 POST /v1/farm/pest/{pest_id}/result — 大虫害提交成绩(🔐)

**路径参数:** `pest_id`(来自 WS `pest_big` 事件)。

**请求体:**

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `score` | int | ✅ | 音游得分 |
| `max_score` | int | ✅ | 满分 |
| `miss_count` | int | 否 | 失误数(默认 0,惩罚用) |

**响应(data):**

| 字段 | 类型 | 说明 |
|---|---|---|
| `pest_id` | str | 事件 UUID |
| `passed` | bool | 是否达标 |
| `score` / `max_score` / `miss_count` | int | 回显 |
| `reward` | object\|null | 达标时发放:`{coins, exp, items?}` |
| `penalty` | object\|null | 不达标时:`{targets: N}`(寄生 N 个小虫害) |
| `pest_small` | object\|null | 不达标时生成的寄生事件(同 WS `pest_small` payload) |

**错误:** `28005 PEST_NOT_FOUND`(事件不存在/已结束)· `28006 PEST_RESULT_TOO_FAST`(**防作弊**:提交耗时 < 音游时长 × min_elapsed_factor,HTTP 400)

**注意事项:** ① **防作弊**:广播到提交的时间必须 ≥ 时长 × 0.6(默认),否则拒绝;② 达标条件 `score/max_score ≥ pass_ratio`(默认 0.6);③ 事件只能提交一次(重复提交返回 PEST_NOT_FOUND)。

### 6.14 POST /v1/farm/pest/{pest_id}/drive-away — 驱赶小虫害(🔐)

**路径参数:** `pest_id`(来自 WS `pest_small` 事件或 `pest/state`)。

**请求体:**

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `plot_id` | str | ✅ | 被寄生的地块 UUID |

**响应(data):** `pest_id` / `plot_id` / `status`(1=已驱赶,2=已到点被摧毁)/ `destroyed`(bool:作物是否已被虫害摧毁)

**错误:** `28007 PEST_TARGET_NOT_FOUND`(目标不存在/已处理)

**注意事项:** 倒计时结束后驱赶无效(虫已得手,作物被摧毁)。

---

## 7. 调试接口详解(🧪 全部需 `DEBUG_ENABLED=true` + 🔐)

> 生产环境必须关闭 `DEBUG_ENABLED`(环境变量默认 false)。调试接口不写审计,仅供开发/测试。

### 7.1 POST /v1/debug/config — 热改全局配置

**请求体:** `{ "key": "xxx", "value": <任意 JSON 值> }`(写入 game_config,立即生效,不发版)。

**响应(data):** `{ "key": "xxx", "value": ... }`

**错误:** `90001 DEBUG_DISABLED`(未开启,HTTP 403)

### 7.2 POST /v1/debug/term/advance — 推进节气(只影响自己)

**请求:** 无请求体。

**响应(data):** `{ "term_index", "name", "cycle", "remaining_sec" }`(推进后的我的节气)。

**注意事项:** 只推进**调用者自己的世界**(每用户隔离),不影响其他玩家。

### 7.3 POST /v1/debug/grow — 催熟

**请求体:** `{ "plot_id": "..." }`

**响应(data):** `{ "plot_id": "...", "mature": true }`(该地块作物变为成熟)。

### 7.4 POST /v1/debug/pest/trigger — 强制触发虫害

**请求体:** `{ "type": "big"|"small" }`(默认 big)。

**响应(data):** 同 WS 事件:`{ "type": "pest_big"|"pest_small", "payload": {...}, "ts" }`。

**错误:** `28002 PEST_DISABLED` · `28003 PEST_BUSY`(已有进行中事件)

### 7.5 POST /v1/debug/pest/clear — 清除虫害

**请求:** 无请求体。

**响应(data):** `{ "events": N, "targets": N }`(清除的事件/寄生目标数)。

### 7.6 POST /v1/debug/weed/trigger — 强制触发杂草生长

**请求:** 无请求体。

**响应(data):** `{ "type": "weed_growth", "targets": [{ "plot_id", "idx" }] }`。

### 7.7 POST /v1/debug/weed/clear — 清除杂草

**请求:** 无请求体。

**响应(data):** `{ "cleared": N }`(清除的地块数)。
---

### 7.8 GET /v1/dev/assets — 完整资源清单(🔐 需玩家登录 token)

**认证:** `Authorization: Bearer <玩家登录 JWT>`(与玩家端接口一致,见 §3.1;无效/过期返回 401)。

**响应(data):**

| 字段 | 类型 | 说明 |
|---|---|---|
| `root` | str | 资源根目录 `app/static/assets` |
| `count` | int | 文件总数 |
| `tree` | object | 目录树(嵌套,叶子为 null) |
| `files[]` | array | `{ "path", "url", "size", "ext" }` 每个文件及访问 URL |
| `registry` | object | 注册表类型 → url_template |

**URL 规则:** 注册表类型(audio/config)与 images 子目录(crops/terms/animals)→ `/v1/assets/...`;其他 → `/static/assets/...`。

**示例:**

```
GET /v1/dev/assets
Authorization: Bearer dev_xxx
→ { "count": 124, "files": [{ "path": "animals/happy/dog.png",
      "url": "/v1/assets/images/animals/happy/dog.png", "size": 12345, "ext": "png" }, ...] }
```

## 8. 管理后台端点详解(👑 全部需 admin token)

> 公共约定:除 `POST /v1/admin/login` 外全部需要 `Authorization: Bearer <admin_token>`;admin token 有效期 **2 小时**。错误:`30001 ADMIN_BAD_CREDENTIALS`(登录失败,HTTP 401)、`30002 ADMIN_DISABLED`(ADMIN_ENABLED=false,HTTP 403)。

### 8.1 POST /v1/admin/login — 管理员登录(🔓)

**请求体:** `{ "username": "...", "password": "..." }`

**响应(data):** `{ "token": "<admin_jwt>" }`

**错误:** `30001 ADMIN_BAD_CREDENTIALS`(账号或密码错误)· `30002 ADMIN_DISABLED` · **`ADMIN_PASSWORD` 为空时拒绝一切登录**

### 8.2 GET /v1/admin/dashboard — 仪表盘

**响应(data):**

| 字段 | 类型 | 说明 |
|---|---|---|
| `server` | object | `{pid, version, admin_enabled, debug_enabled, db_size}` |
| `clock` | object | `{time_scale, paused}` 全局默认速率与暂停状态 |
| `counts` | object | `{users, players, farms, coins_total, world_accum_total, crops, items, terms, growing}` |

### 8.3 GET /v1/admin/env — 环境变量(只读)

**响应(data):** `{ "items": [{ "name", "value" }] }`(敏感键值打码为 `****`)。

### 8.4 GET /v1/admin/users — 用户列表

**查询参数:** `page`(默认 1)/ `page_size`(默认 20,≤100)。

**响应(data):** 分页信封,`items[]`:

| 字段 | 说明 |
|---|---|
| `user_id` / `name` / `status`(1 正常/0 封禁) | 用户基础 |
| `register_ip` / `register_location` / `last_login_ip` / `last_login_location` | IP 与地理位置 |
| `created_at` / `last_login_at` | 时间 |
| `player` | 玩家摘要:`{level, exp, coins, unlocked_term_index}`(无玩家则 null) |

### 8.5 PATCH /v1/admin/users/{user_id}/status — 封禁/解封

**请求体:** `{ "status": 0|1 }`(0=封禁,1=解封)。

**响应(data):** `{ "user_id", "status" }`

**注意事项:** 封禁**即时生效**(已登录 token 下次请求即被拒)。

### 8.6 GET /v1/admin/users/{user_id}/assets — 玩家资产(预填)

**响应(data):** `{ "player_id", "name", "level", "exp", "coins", "unlocked_term_index" }`

### 8.7 PATCH /v1/admin/users/{user_id}/assets — 编辑玩家资产

**请求体(全可选,只改提供的字段):**

| 字段 | 类型 | 约束 |
|---|---|---|
| `coins` | int | ≥0 |
| `level` | int | ≥1 |
| `exp` | int | ≥0 |
| `unlocked_term_index` | int | 1-24 |

**响应(data):** 同 8.6(更新后)。

**注意事项:** 编辑成功后向该玩家在线 WS 推送 **`resources_changed`**(客户端强制刷新)。

### 8.7.1 POST /v1/admin/redeem/codes — 发布兑换码(👑)

**请求体:**

| 字段 | 类型 | 约束 |
|---|---|---|
| `reward` | object | 奖励 `{coins, exp, items:[{code,quantity}]}` |
| `count` | int | 批量数量(1-100,仅未指定 code 时) |
| `code` | str? | 指定码值(6-24 位 [A-Z0-9]);省略则随机生成 |
| `batch_name` | str? | 批次名(运营备注) |
| `max_uses` | int | 总使用次数上限,0=不限 |
| `per_player_limit` | int | 每人限领次数(默认 1) |
| `expires_at` | str? | 过期时间 ISO8601 |

**响应(data):** `{ "codes": [{ "code", "id", "batch_name" }] }` —— **明文只在本次响应返回一次**,库中存 SHA-256 哈希。

**错误:** `20015 REDEEM_CODE_EXISTS`(指定码值已存在)

### 8.7.2 GET /v1/admin/redeem/codes — 兑换码列表(👑)

**查询:** `page` / `page_size`。

**响应(data):** `{ "items": [{ "id", "hint"(前6位), "batch_name", "max_uses", "used_count", "per_player_limit", "expires_at", "active", "created_at" }], "page", "page_size", "total" }`

### 8.7.3 PUT /v1/admin/redeem/codes/{code_id} — 更新兑换码(👑)

**请求体(全可选):** `active`(bool)· `max_uses`(int)· `per_player_limit`(int)· `expires_at`(str?)。

**错误:** `20016 REDEEM_NOT_FOUND`(兑换码不存在)

### 8.7.4 PUT /v1/admin/users/{user_id}/rename — 管理端改名(👑)

**请求体:** `new_name`(1-16 字符)。

**响应(data):** `{ "name", "user_id" }`

**注意事项:** 无限速;同步改 `User.name` + `Player.name`。

### 8.8 GET /v1/admin/config — 全局配置列表

**响应(data):** `{ "items": [{ "key", "value", "updated_at" }] }`(game_config 全部 KV)。

### 8.9 PUT /v1/admin/config/{key} — 写全局配置

**请求体:** `{ "value": <任意 JSON> }`(写入或覆盖)。

**响应(data):** `{ "key", "value" }`(更新后)。

### 8.10 DELETE /v1/admin/config/{key} — 删全局配置

**响应(data):** `{ "key", "deleted": true }`

### 8.11 GET /v1/admin/crops — 植物列表

**响应(data):** `{ "items": [作物对象] }`

`作物对象` 字段:`crop_id / name / category / sow_window / grow_seconds / yield_base / base_price / unlock_level / unlock_exp / settings / description / art / sort_order / active`(settings 结构见 10.4)。

### 8.12 POST /v1/admin/crops — 新增植物

**请求体(AdminCropPayload,大部分可选):**

| 字段 | 类型 | 说明 |
|---|---|---|
| `name` | str | ✅ 必填,唯一 |
| `category` | str | 谷物/油料/蔬菜/经济作物/花卉 |
| `sow_window` | dict | `{type:"term", start, end, grace}` |
| `grow_seconds` / `yield_base` / `base_price` | int | 基础数值 |
| `unlock_level` / `unlock_exp` | int | 解锁要求 |
| `settings` | dict | 高级设定(枯萎/加速/需水/需肥/单株上限) |
| `art` | dict | 素材路径(缺省自动生成占位) |
| `auto_seed` | bool | true = 自动创建对应种子道具 |

**响应(data):** 作物对象 + `seed_created`(bool)。

**错误:** `21006 CROP_EXISTS`(重名)

**注意事项:** 创建后自动**写回设定文件**(`data/crops/<slug>.json`,文件为事实源)。

### 8.13 PUT /v1/admin/crops/{crop_id} — 编辑植物

**请求体:** 同 8.12(全可选,含 `active`)。

**响应(data):** 作物对象。

**注意事项:** 修改后写回设定文件;`unlock_exp/settings` 等新字段直接生效(下次播种校验)。

### 8.14 DELETE /v1/admin/crops/{crop_id} — 删除植物(软删)

**响应(data):** `{ "crop_id", "active": false }`。

**错误:** `21007 CROP_IN_USE`(有种植中的该作物,HTTP 400)

**注意事项:** 软删除 + 自动下架对应种子道具。

### 8.15 GET /v1/admin/plantings — 全服种植状态

**查询参数:** `active`(bool,默认 true,只看未收获)/ `page` / `page_size`。

**响应(data):** 分页信封,`items[]`:

| 字段 | 说明 |
|---|---|
| `planting_id` / `player` / `farm` / `plot_idx` | 位置 |
| `crop` / `stage` / `growth_progress` / `water_level` | 作物状态(服务器权威) |
| `sowed_term_index` / `sowed_at` / `predicted_harvest_at` | 播种信息 |

### 8.16 GET /v1/admin/items — 道具列表

**响应(data):** `{ "items": [道具对象] }`

`道具对象`:`item_id / code / name / category / stackable / max_stack / effect / buy_price / sell_price / unlock_level / sort_order / active`。

### 8.17 POST /v1/admin/items — 新增道具

**请求体:** `{ "code", "name", "category", "effect", "buy_price", ... }`(全可选除 code/name;`effect` 为 JSONB,见 10.1)。

**响应(data):** 道具对象。

**错误:** `22005 ITEM_EXISTS`(code 重复)

### 8.18 PUT /v1/admin/items/{item_id} — 编辑道具

**请求体:** 同 8.17(全可选,含 `active`)。

**响应(data):** 道具对象。

### 8.19 DELETE /v1/admin/items/{item_id} — 删除道具(软删)

**响应(data):** `{ "item_id", "active": false }`

### 8.20 GET /v1/admin/terms — 节气列表

**响应(data):** `{ "items": [{ "term_index", "name", "duration_seconds" }] }`(24 个)。

### 8.21 PUT /v1/admin/terms/{term_index} — 修改节气时长

**请求体:** `{ "duration_seconds": 600 }`(10-86400)。

**响应(data):** `{ "term_index", "name", "duration_seconds" }`。

### 8.22 PUT /v1/admin/clock — 时钟控制

**请求体:**

| 字段 | 类型 | 说明 |
|---|---|---|
| `time_scale` | float | 全局默认倍速(>0,≤100);玩家无 override 时用此值 |
| `paused` | bool | true=暂停(世界冻结) |

**响应(data):** `{ "time_scale", "paused" }`。

> 全局倍速是**默认值**;单个玩家可覆盖(见 8.33 `time_scale` 字段)。已删除全局纪元概念,新玩家从立春开始。

### 8.23 GET /v1/admin/users/{user_id}/farm — 某用户农场

**响应(data):** `{ "plots": [{ "plot_id", "idx", "soil_quality", "locked", "crop": {...} }], "current_term": {...} }`(crop 结构与 5.7 一致)。

### 8.24 PUT /v1/admin/users/{user_id}/plots/{plot_idx} — 地块设置

**请求体:** `{ "locked": bool, "soil_quality": 1-5 }`(全可选)。

**响应(data):** `{ "plot_id", "idx", "locked", "soil_quality" }`

### 8.25 PUT /v1/admin/users/{user_id}/plots/{plot_idx}/crop — 种/替换作物

**请求体:**

| 字段 | 类型 | 说明 |
|---|---|---|
| `crop_id` | str | ✅ 作物 UUID |
| `growth_progress` | int | 0-100,默认 0(回拨 sowed_at 实现) |
| `water_level` | int | 0-100,默认 100 |

**响应(data):** `{ "plot_id", "idx", "crop_id", "stage", "growth_progress", "water_level", ... }`。

**注意事项:** 管理端种植**不消耗种子、不校验节气窗/解锁**(GM 操作);替换会清除旧作物。

### 8.26 DELETE /v1/admin/users/{user_id}/plots/{plot_idx}/crop — 清除作物

**响应(data):** `{ "plot_id", "idx", "cleared": true }`。

### 8.27 PUT /v1/admin/users/{user_id}/plots/{plot_idx}/growth — 调整生长/水分

**请求体:** `{ "growth_progress": 0-100, "water_level": 0-100 }`(全可选)。

**响应(data):** 同 8.25。

**注意事项:** 改水分时重置水分衰减计时(从设定时刻重新算)。

### 8.28 GET /v1/admin/users/{user_id}/inventory — 某用户背包

**响应(data):** `{ "items": [{ "item_id", "code", "name", "quantity" }] }`

### 8.29 PUT /v1/admin/users/{user_id}/inventory/{item_id} — 设定道具数量

**请求体:** `{ "quantity": N }`(绝对值,0=清空)。

**响应(data):** `{ "item_id", "quantity" }`

**注意事项:** 写 `item_transactions` 账本(审计用,reason 带 admin)。

### 8.30 GET /v1/admin/users/{user_id}/storage — 某用户收成仓

**响应(data):** `{ "items": [{ "crop_id", "name", "quantity" }] }`

### 8.31 PUT /v1/admin/users/{user_id}/storage/{crop_id} — 设定收成数量

**请求体:** `{ "quantity": N }`(绝对值)。

**响应(data):** `{ "crop_id", "quantity" }`

### 8.32 GET /v1/admin/worlds — 每用户世界列表

**查询参数:** `page` / `page_size`。

**响应(data):** 分页信封,`items[]`:`{ "player_id", "name", "world_accum"(世界秒), "time_scale_override"(float|null,覆盖速率), "current_term": {term_index, name, remaining_sec}, "online"(bool), "last_active_at" }`。

### 8.33 PUT /v1/admin/worlds/{player_id} — 覆盖/重置玩家世界

**请求体(全可选):**

| 字段 | 类型 | 说明 |
|---|---|---|
| `accum` | float | 设定累计世界秒 |
| `reset` | bool | true=回到立春(accum=0) |
| `time_scale` | float | 覆盖该玩家世界速率(0.1-100) |
| `clear_override` | bool | true=清除速率覆盖,恢复用全局 time_scale |

**响应(data):** `{ "player_id", "accum", "time_scale_override", "term_index", "name", "cycle", "remaining_sec" }`

### 8.34 GET /v1/admin/shop/settings — 全局商店默认

**响应(data):**

| 字段 | 说明 |
|---|---|
| `default_stock` / `restock_seconds` | 库存与补货周期 |
| `sell_factor` / `item_factor` | 价格系数 |
| `season_effect` | `{spring, summer, autumn, winter}` |
| `category_factor` | `{谷物, 蔬菜, 花卉, ...}` |

### 8.35 PUT /v1/admin/shop/settings — 保存全局商店默认

**请求体:** 同 8.34(全可选)。

**响应(data):** 同 8.34(更新后)。

### 8.36 GET /v1/admin/shop/users — 全部用户商店摘要

**响应(data):** 分页信封,`items[]`:`{ "user_id", "name", "player_id", "shop_created"(bool), "item_count", "total_stock" }`(按创建时间倒序)。

### 8.37 GET /v1/admin/shop/users/{player_id}/items — 某用户商店商品

**响应(data):** `{ "items": [{ "item_id", "code", "name", "stock", "buy_override", "sell_override" }] }`(override 为 null = 用全局公式价)。

### 8.38 PUT /v1/admin/shop/users/{player_id}/items/{item_id} — 覆盖商品

**请求体:** `{ "stock": int, "buy_price": int\|null, "sell_price": int\|null }`(buy_price=null 恢复公式价)。

**响应(data):** `{ "item_id", "code", "stock", "buy_override", "sell_override" }`

### 8.39 POST /v1/admin/shop/users/{player_id}/restock — 手动补货

**请求:** 无请求体。**响应(data):** `{ "player_id", "restocked": true }`

### 8.40 POST /v1/admin/shop/users/{player_id}/reset — 重置商店

**请求:** 无请求体。**响应(data):** `{ "player_id", "reset": true }`(清空覆盖,恢复全局默认)

### 8.41 GET /v1/admin/ai/config — AI 配置(密钥打码)

**响应(data):** `{ "enabled", "base_url", "model", "api_key"(打码), "configured"(bool) }`

### 8.42 PUT /v1/admin/ai/config — 保存 AI 配置

**请求体:** `{ "enabled": bool, "base_url": str, "api_key": str, "model": str }`(全可选)。

**响应(data):** 同 8.41(打码)。

### 8.43 POST /v1/admin/ai/test — AI 连通性测试

**请求:** 无请求体。

**响应(data):** `{ "ok": true, "message": "..." }`(或错误 `24003 AI_UPSTREAM_ERROR`)。

### 8.44 GET /v1/admin/ai/usage — 全服 AI 用量

**查询参数:** `page` / `page_size`。

**响应(data):** 分页信封,`items[]`:`{ "player_id", "name", "requests", "prompt_tokens", "completion_tokens", "total_tokens" }`(总 token 降序)。

### 8.45 GET /v1/admin/pest/config — 虫害配置

**响应(data):** `pest.enabled / pest.events_per_window / pest.window_terms / pest.big_ratio / pest.big_duration_seconds / pest.stage_wait / pest.min_elapsed_factor / pest.pass_ratio / pest.reward_coins / pest.active_terms / pest.season_frequency / pest.season_big_ratio`(全部可读)。

**默认(节气/季节驱动)**:`active_terms={start:3,end:18}`(惊蛰~霜降,窗口外无虫)、`season_frequency={spring:0.6,summer:1.5,autumn:0.8,winter:0}`(盛夏最频繁)、`season_big_ratio={spring:0.3,summer:0.5,autumn:0.2,winter:0}`(盛夏大虫灾最多)。

### 8.46 PUT /v1/admin/pest/config — 保存虫害配置

**请求体:** 上述键的任意子集。

**响应(data):** 更新后的完整配置。

### 8.47 GET /v1/admin/pest/events — 虫害事件记录

**查询参数:** `page` / `page_size`。

**响应(data):** 分页信封,`items[]`:`{ "pest_id", "player", "type"(big/small), "status"(0进行中/1已结束/2已过期), "score", "max_score", "miss_count", "reward", "penalty", "broadcast_at" }`
---

## 9. WebSocket 协议

### 9.1 WS /v1/ws?token=<player_token> — 玩家实时推送(🔐)

- **鉴权**:玩家 JWT 走查询参数(WS 无法带 Header)。无效/过期 token → 服务端关闭码 **`4401`**。
- **首帧**:连接建立后立即推送一条 `solar_term_change`(我的当前节气),用于初始化 UI。
- **心跳**:客户端发文本 `ping` → 服务端回 `{"type":"pong"}`(每 30 秒一次;也刷新"在线"判定)。
- **推送节奏**:此后按我的世界倍速,到点推送下一条节气;期间任何定向事件随时插入。
- **断线重连**:重连后第一条就是当前节气,不丢状态;关闭码 4401 时停止重连,回登录页。

### 9.2 服务端主动推送事件(定向,每用户)

| type | 触发场景 | payload | 客户端动作 |
|---|---|---|---|
| `solar_term_change` | 连接首帧 / 节气切换 | `{term_index, name, cycle, remaining_sec}` | 更新节气 UI;按需刷新商店/农场视图 |
| `resources_changed` | 管理后台编辑该玩家资产 | `{player_id, name, level, exp, coins, unlocked_term_index}` | **重新 GET /v1/player/me**(事件只是通知,值以接口为准) |
| `pest_big` | 大虫害触发(音游对抗) | `{pest_id, type:"big", duration_seconds}` | 弹音游;结束 POST `/v1/farm/pest/{id}/result` |
| `pest_small` | 小虫害寄生(含惩罚寄生) | `{pest_id, type:"small", targets:[{pest_id, plot_id, idx, crop, stage, wait_seconds, ready_at}]}` | 标红地块 + 倒计时;驱赶 POST `/v1/farm/pest/{id}/drive-away` |
| `pest_destroyed` | 寄生倒计时到点,作物被摧毁 | `{targets:[{pest_id, plot_id}]}` | 刷新地块(作物已消失) |
| `crop_withered` | 玩家季节进入植物枯萎季节 | `{targets:[{plot_id, idx, crop_name, status:"wilted"}]}` | 显示"植物冻死了"覆盖层(作物**仍占地块**,不消失);玩家可铲除/收割 |
| `weed_growth` | 本节气随机时刻杂草生长 | `{targets:[{plot_id, idx}]}` | 地块显示杂草(生长减速)+ 刷新 farm/state |
| `asset_update` | 管理端 POST `/v1/assets/notify`(资源更新) | `{asset_type, key, name, url, version}` | 按 `url` 拉取;若 `version` 与本地缓存不同则**强制更新该资源** |

示例:

```json
{ "type": "resources_changed", "payload": { "player_id": "…", "name": "demo01",
  "level": 5, "exp": 120, "coins": 666, "unlocked_term_index": 6 }, "ts": 1784000000 }
```

- 所有事件带 `ts`(unix 秒);**未知类型一律忽略**(向前兼容)。
- 玩家不在线时推送静默丢弃,下次登录/轮询自然收敛。

### 9.3 WS /v1/admin/logs?token=<admin_token> — 日志监控(只读,👑)

- 连接即**回放最后 200 行**,之后增量实时推送。
- 服务端 → 客户端:`{"type":"log","data":"<行>"}` / `{"type":"error","data":"<提示>"}`(文件不存在/轮转)。
- 客户端 → 服务端:文本 `ping` → `pong`。
- 断开后自动重连(重连后重新回放)。**只读,无任何命令执行能力(无 RCE 面)**。

### 9.4 客户端接入指南(Godot 可直接照抄)

**完整时序**:登录拿 token → `ws://host/v1/ws?token=` 连接 → 首帧节气初始化 → 每 30s `ping` → 事件分发 → `resources_changed` 后重新 GET /v1/player/me → 断线指数退避重连(2s→4s→8s,上限 30s;4401 停止重连回登录)。

```gdscript
# ws_client.gd —— Godot 4 WebSocketPeer 示例(连接/心跳/分发/刷新/重连)
extends Node

const HOST := "ws://127.0.0.1:8000/v1/ws"
var _ws := WebSocketPeer.new()
var _token := ""
var _connected := false
var _ping_timer := 0.0
const PING_INTERVAL := 30.0

signal resources_changed
signal solar_term_changed(payload: Dictionary)
signal pest_event(type: String, payload: Dictionary)

func connect_ws(token: String) -> void:
    _token = token
    _ws.connect_to_url(HOST + "?token=" + token)  # 鉴权走查询参数

func _process(delta: float) -> void:
    _ws.poll()
    if _ws.get_ready_state() == WebSocketPeer.STATE_OPEN:
        if not _connected:
            _connected = true
        _ping_timer += delta
        if _ping_timer >= PING_INTERVAL:
            _ping_timer = 0.0
            _ws.send_text("ping")
        while _ws.get_available_packet_count() > 0:
            _on_message(_ws.get_packet().get_string_from_utf8())
    elif _ws.get_ready_state() == WebSocketPeer.STATE_CLOSED and _connected:
        _connected = false
        get_tree().create_timer(3.0).timeout.connect(func(): connect_ws(_token))

func _on_message(raw: String) -> void:
    var msg: Dictionary = JSON.parse_string(raw)
    match msg.get("type"):
        "pong": pass
        "solar_term_change": solar_term_changed.emit(msg["payload"])
        "resources_changed":
            _refetch_player()          # 权威值以 /v1/player/me 为准
            resources_changed.emit()
        "pest_big", "pest_small", "pest_destroyed", "crop_withered", "weed_growth":
            pest_event.emit(msg["type"], msg["payload"])
        _: pass  # 未知事件忽略(向前兼容)
```

---

## 10. 数据对象速查

### 10.1 道具效果(effect JSONB)

| type | 字段 | 说明 |
|---|---|---|
| `seed` | `crop_id` | 对应作物 UUID(播种消耗) |
| `boost` | `boost_pct` | 生长加速百分比(肥料 50) |
| `water` | — | 浇水(水壶) |
| `term_lock` | `term_index` | 锁定节气 ⚠️ 效果未实现 |

### 10.2 内置数据(seed 幂等导入)

`data/term_config.json`(24 节气,时长可配)、`data/items.json`(18 道具)、`data/quests.json`(5 任务)、`data/achievements.json`(成就)、`data/crops/*.json`(15 植物)。

### 10.3 美术素材(作物 + 节气)

```
GET /v1/art/{kind}/{key}/{name}.png?w=<px>              # 统一资源接口(唯一入口)
    # kind=crops:key=slug,name=seed|1|2|3(1/2/3 = 苗期/生长期/成熟)
    # kind=terms:key=节气序号 1-24,name=main
    # 旧路径 GET /v1/art/terms/{term_index}.png 仍可用(等价 terms/{index}/main)
GET /v1/art/version                                 # 版本:version/crops/terms/sizes
GET /v1/art/manifest                                # 全量清单:作物×4 + 节气×1 + 版本 + URL 模板
```

- `w` 取**最小不小于 w** 的预渲染档(32/64/128/256),超出取最大档;响应 `image/png` + 长缓存。
- **取图闭环**:`GET /v1/farm/state` → 每格 `crop.art`(含 seed + stages 路径)→ 从路径取 slug → 按 `crop.stage` 取对应图。
- **缓存刷新**:登录/节气切换时对比 `version`(全局变 → 全量刷新;`crops[slug]`/`terms[slug]` 变 → 只刷对应素材)。
- 节气 slug 映射:1 lichun / 2 yushui / 3 jingzhe / 4 chunfen / 5 qingming / 6 guyu / 7 lixia / 8 xiaoman / 9 mangzhong / 10 xiazhi / 11 xiaoshu / 12 dashu / 13 liqiu / 14 chushu / 15 bailu / 16 qiufen / 17 hanlu / 18 shuangjiang / 19 lidong / 20 xiaoxue / 21 daxue / 22 dongzhi / 23 xiaohan / 24 dahan。

### 10.4 植物设定文件(data/crops/<slug>.json)

每株植物一个 JSONC 文件(支持 `//` 注释),是植物设定的**事实源**,启动/重跑 seed 幂等同步到 DB。字段:`slug / name / category / sort_order / sow_window / grow_seconds / yield_base / base_price / unlock_level / unlock_exp / settings / art(可选)/ note`。

`settings` 含义:

| 键 | 说明 |
|---|---|
| `wither_seasons` | 枯萎季节(玩家世界进入时未收获作物**标记枯萎/冻死**——仍占地块,可铲除或收割,收割减产入劣质仓) |
| `fast_growth_seasons` | `{季节: 倍率}` —— 该季节播种 → 生长速度 × 倍率 |
| `water_need` | `{min, ideal}` —— 水分每节气 -10,低于 min 生长停滞 |
| `fertility_need` | 土壤肥力低于该值 → 收成减产 ×(soil/need) |
| `max_value` | 单株卖价上限(0=不封顶) |

完整注释模板见 `data/crops/_template.json`;修改文件 → 重启服务生效;管理后台增改自动写回文件。

---

## 11. 错误码全表(49 + 1 兜底,与代码逐一核对)

> **判断业务成败看 `code`(0=成功),不要只看 HTTP 状态。** HTTP 与 code 的关系见各端点错误表;下表为全量。

### 1xxxx 通用

| code | error_code | HTTP | 触发条件 |
|---|---|---|---|
| 10001 | INVALID_PARAMS | 400 | 参数不合法/缺失 |
| 10002 | UNAUTHORIZED | 401 | 未登录 / 玩家不存在 |
| 10003 | UNAUTHORIZED | 401 | 登录已过期 |

### 2xxxx 账号 / 农场 / 商店

| code | error_code | HTTP | 触发条件 |
|---|---|---|---|
| 20002 | USER_NOT_FOUND | 400 | 用户/玩家不存在 |
| 20003 | BAD_CREDENTIALS | 400 | 密码错误 |
| 20004 | USER_BANNED | 403 | 账号已封禁(登录与存量 token 均拦截) |
| 20006 | NAME_CONFLICT | 400 | 同名多账号且密码相同,登录歧义 |
| 20007 | USER_DEACTIVATED | 403 | 账号已注销(登录与存量 token 均拦截,世界冻结) |
| 20008 | RENAME_TOO_FREQUENT | 400 | 改名过于频繁(rename.cooldown_seconds 内,响应带剩余秒数) |
| 20009 | REDEEM_RATE_LIMITED | 400 | 兑换过于频繁(redeem.cooldown_seconds 内,成功失败都算) |
| 20010 | REDEEM_INVALID | 400 | 兑换码无效/停用/过期(统一报错防枚举) |
| 20011 | REDEEM_CLAIMED | 400 | 该兑换码已兑换过(per_player_limit 已满) |
| 20012 | REDEEM_EXHAUSTED | 400 | 兑换码已用完(max_uses 耗尽) |
| 20013 | UID_NOT_FOUND | 400 | 数字 ID 不存在 |
| 20014 | UID_GEN_FAILED | 500 | 数字 ID 生成失败(随机冲突重试耗尽) |
| 20015 | REDEEM_CODE_EXISTS | 400 | 兑换码已存在(管理端发布重复) |
| 20016 | REDEEM_NOT_FOUND | 400 | 兑换码不存在(管理端更新) |
| 21000 | FARM_NOT_FOUND | 400 | 农场不存在 |
| 21001 | PLOT_NOT_FOUND | 400 | 地块不存在/未解锁/不属于我 |
| 21002 | PLOT_OCCUPIED | 400 | 地块已有作物 |
| 21003 | CROP_NOT_AVAILABLE | 400 | 当前节气不在宜种窗 |
| 21004 | PLOT_EMPTY | 400 | 地块没有作物 |
| 21005 | CROP_NOT_FOUND | 400 | 作物不存在(或 SEED_NOT_FOUND:无对应种子) |
| 21006 | NOT_ENOUGH_ITEM | 400 | 种子不足(播种时) |
| 21007 | CROP_IN_USE | 400 | 有种植中的作物,无法删除 |
| 21008 | CROP_LOCKED | 400 | 植物未解锁(经验/等级未达其一) |
| 21009 | CROP_WILTED | 400 | 作物已枯萎冻死(无法浇水,需铲除或收割) |
| 22001 | NOT_ENOUGH_ITEM | 400 | 道具数量不足(使用道具时) |
| 22002 | ITEM_NOT_FOUND | 400 | 道具/商品不存在 |
| 22003 | NOT_ENOUGH_COINS | 400 | 金币不足 |
| 22004 | EFFECT_NOT_SUPPORTED | 400 | 效果不支持/未实现(如节气卡、种子直用) |
| 22005 | ITEM_EXISTS | 400 | 道具 code 重复(管理端) |
| 22006 | NOT_ENOUGH_STOCK | 400 | 商店库存不足 |
| 22007 | NOT_ENOUGH_CROP | 400 | 收成仓数量不足 |
| 23001 | CROP_NOT_MATURE | 400 | 作物尚未成熟 |
| 23002 | TERM_NOT_FOUND | 400 | 节气不存在 |

### 24xxx-27xxx 扩展玩法

| code | error_code | HTTP | 触发条件 |
|---|---|---|---|
| 24001 | AI_DISABLED | 400 | AI 服务未启用 |
| 24002 | AI_NOT_CONFIGURED | 400 | AI 地址/APIKEY 未配置 |
| 24003 | AI_UPSTREAM_ERROR | 400 | AI 上游连接失败/非 200 |
| 25001 | QUEST_NOT_FOUND | 400 | 任务不存在 |
| 25002 | QUEST_NOT_COMPLETE | 400 | 任务尚未完成 |
| 25003 | QUEST_ALREADY_CLAIMED | 400 | 任务奖励已领取 |
| 26001 | ACHIEVEMENT_NOT_FOUND | 400 | 成就不存在 |
| 26002 | ACHIEVEMENT_NOT_COMPLETE | 400 | 成就尚未达成 |
| 26003 | ACHIEVEMENT_ALREADY_CLAIMED | 400 | 成就奖励已领取 |
| 27001 | ALREADY_FRIENDS | 400 | 你们已经是好友 |
| 27002 | REQUEST_EXISTS | 400 | 申请已发送,等待处理 |
| 27003 | REQUEST_NOT_FOUND | 400 | 申请不存在 |
| 27004 | NOT_YOUR_REQUEST | 400 | 不是发给你的申请 |
| 27005 | FRIEND_NOT_FOUND | 400 | 好友关系不存在 |

### 28xxx 虫害 / 素材

| code | error_code | HTTP | 触发条件 |
|---|---|---|---|
| 28001 | ART_NOT_FOUND | 404 | 美术素材不存在/档缺失/节气越界 |
| 28002 | PEST_DISABLED | 400 | 虫害系统未启用 |
| 28003 | PEST_BUSY | 400 | 已有进行中的虫害 |
| 28004 | PEST_NO_TARGET | 400 | 没有可寄生的作物 |
| 28005 | PEST_NOT_FOUND | 400 | 虫害事件不存在/已结束 |
| 28006 | PEST_RESULT_TOO_FAST | 400 | 成绩提交过早(防作弊) |
| 28007 | PEST_TARGET_NOT_FOUND | 400 | 寄生目标不存在/已处理 |

### 3xxxx 管理 / 9xxxx 系统

| code | error_code | HTTP | 触发条件 |
|---|---|---|---|
| 30001 | ADMIN_BAD_CREDENTIALS | 401 | 管理员账号/密码错误 |
| 30002 | ADMIN_DISABLED | 403 | 管理后台未启用(ADMIN_ENABLED=false) |
| 29001 | GUEST_BUSY | 400 | 已有活跃的 AI 客人会话 |
| 29002 | GUEST_COOLDOWN | 400 | start 冷却中(guest.cooldown_seconds,默认 30s) |
| 29003 | GUEST_NOT_FOUND | 404 | 会话不存在或不属于该玩家 |
| 29004 | GUEST_CLOSED | 400 | 会话已结束(done/closed/cancelled) |
| 29005 | GUEST_AI_RESPONSE | 502 | AI 回复无法解析/校验失败(兜底后仍失败) |
| 29006 | GUEST_DISABLED | 403 | AI 客人功能未开放(guest.enabled=false) |
| 29007 | GUEST_NO_OFFER | 400 | 客人还没报价,无法 accept |
| 90000 | INTERNAL_ERROR | 500 | 未捕获异常(兜底) |
| 90001 | DEBUG_DISABLED | 403 | 调试接口未开启(DEBUG_ENABLED=false) |

---

## 12. 实现示例(可直接复用)

### 12.1 完整玩法闭环(Python,urllib 标准库)

```python
import json, urllib.request, time

BASE = "http://127.0.0.1:8000/v1"

def call(method, path, token=None, body=None):
    req = urllib.request.Request(BASE + path, method=method)
    req.add_header("Content-Type", "application/json")
    if token: req.add_header("Authorization", f"Bearer {token}")
    data = json.dumps(body).encode() if body is not None else None
    with urllib.request.urlopen(req, data=data, timeout=10) as r:
        return json.loads(r.read())

# 1. 注册(初始 200 金币 + 20 地块)
reg = call("POST", "/auth/register", body={"name": "demo01", "password": "pass123456"})
token = reg["data"]["token"]

# 2. 推进节气到水稻宜种窗(5-8;正式环境等节气自然轮转)
for _ in range(30):
    cal = call("GET", "/calendar/current", token=token)["data"]
    if 5 <= cal["term_index"] <= 8: break
    call("POST", "/debug/term/advance", token=token)

# 3. 买水稻种子(种子道具的 effect.crop_id 就是播种目标)
shop = call("GET", "/shop/items", token=token)["data"]["items"]
seed = next(i for i in shop if i["code"] == "seed_shuidao")
call("POST", f"/shop/items/{seed['item_id']}/buy", body={"quantity": 1}, token=token)

# 4. 播种 → 浇水 → 催熟(调试) → 收获(入收成仓)
state = call("GET", "/farm/state", token=token)["data"]
pid = state["plots"][0]["plot_id"]
call("POST", f"/farm/plots/{pid}/sow", body={"crop_id": seed["effect"]["crop_id"]}, token=token)
call("POST", f"/farm/plots/{pid}/water", token=token)
call("POST", "/debug/grow", body={"plot_id": pid}, token=token)
harvest = call("POST", f"/farm/plots/{pid}/harvest", token=token)["data"]
print("收成:", harvest["yield"], "入仓,仓内", harvest["storage_after"])

# 5. 按当前季节价出售
sell = call("POST", f"/shop/crops/{harvest['crop_id']}/sell",
            body={"quantity": harvest["yield"]}, token=token)["data"]
print("卖出:", sell["price"], "金币,余额", sell["coins_balance"])
```

### 12.2 管理运维(改资产 → 玩家收到 resources_changed)

```python
adm = call("POST", "/admin/login", body={"username": "admin", "password": "admin123"})
ah = adm["data"]["token"]
users = call("GET", "/admin/users?page_size=50", token=ah)["data"]["items"]
uid = next(u["user_id"] for u in users if u["name"] == "demo01")
r = call("PATCH", f"/admin/users/{uid}/assets", body={"coins": 999}, token=ah)
# → 该玩家在线 WS 立即收到 resources_changed,客户端据此刷新
```

---

## 13. 文档一致性校验

本文档与代码的一致性由 `server/scripts/verify_api_docs.py` 保证(以代码为唯一事实源):

```bash
cd server && uv run python -m scripts.verify_api_docs inventory   # 生成端点/错误码清单
cd server && uv run python -m scripts.verify_api_docs check       # 三查校验
```

三查内容:
1. **端点双向核对**:源码全部路由 ↔ 文档索引(白名单:/docs /static/* /admin)
2. **错误码核对**:源码全部 `AppError` ↔ 文档错误码表
3. **交叉引用**:README 引用的 `/v1/...` 路径在本文档中存在

**最近校验**:文档重写完成时执行,三查全绿;任何接口变更后请重跑 check。
