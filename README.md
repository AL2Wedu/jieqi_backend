# jieqi_backend(节气种田 · 后端)

教育 + AI + 模拟经营游戏的后端仓库(元创S营项目)。客户端使用 Godot 4,后端为独立部署的 API 服务。

**文档导航**:本文档(机制/架构/部署)→ [API.md](API.md)(全部接口,不读源码即可对接)→ [ASSETS.md](ASSETS.md)(游戏资源统一接口与全量清单)→ [docs/](docs/)(设计文档)

---

# 0. 项目状态

| 状态 | 说明 |
|---|---|
| ✅ 已实现 | P0 核心玩法 + 扩展玩法全闭环(见第 1 章) |
| 🧪 测试 | 63 个 pytest 用例全绿 |
| 🚀 部署 | 演示模式可直跑;生产部署方案见第 7 章 |

---

# 1. 功能总览(实现状态)

> 状态标记:✅ 已实现 · ⚠️ 部分实现 · ❌ 未实现 · 📋 计划中

## 1.1 已实现 ✅

### 账号与玩家
- **注册 / 登录**:名字 + 密码(demo 形态),PBKDF2 密码哈希,JWT 签发(玩家 token 7 天)
- **IP 地理位置**:注册/登录自动解析落库(`register_location / last_login_location`,ip2region 离线库,零外部请求,内网降级)
- **封禁 / 解封**:管理后台操作,封禁后无法登录
- **玩家资产**:等级 / 经验 / 金币 / 农场(4×5=20 地块)/ 背包 / 收成仓 / 头衔(成就解锁)

### 时间与节气(核心)
- **24 节气轮转**:每节气默认 300 秒(可配置),约 2 小时一个完整循环,**纯公式计算,无日历表**
- **每用户独立世界**:每个玩家维护自己的世界时钟 `world_accum`(在线 1× 推进 / 离线 0.25× 减速 / 全局暂停冻结 / 倍速可调),节气切换只影响自己
- **实时推送**:节气切换经 WS 广播给该玩家

### 农场玩法(服务器权威)
- **4×5 田地**:20 个地块,idx 行优先(1-20),每个地块可独立选种
- **播种校验链**:植物解锁(等级或经验其一)→ 宜种节气窗(精细节气窗 + grace 宽限轮次)→ 消耗对应种子道具
- **季节加速**:在植物的加速季节播种 → 生长速度 × 倍率(成熟时间缩短)
- **水分系统**:浇水补满,水分随世界时间衰减(每节气 -10),低于植物需水红线 → **生长停滞**
- **杂草减速**:地块附杂草 → 该地块作物生长速度 × 0.5(可配置)
- **季节枯萎(冻死)**:玩家世界进入植物枯萎季节 → 未收获作物**标记枯萎(不直接消失)**,前端显示"植物冻死了";玩家可**铲除**(清掉地块)或**收割**(产量减半、入仓为劣质收成,售价大打折扣)(WS 推送 + farm state 提示)
- **肥力减产**:土壤肥力低于植物需肥力 → 收成减产 ×(soil/need)
- **收获入仓**:收成进收成仓,不直接给金币,玩家择机到商店按季节价出售
- **服务器权威**:阶段(苗期/生长期/成熟)与进度由服务器时间推导,客户端只展示

### 植物 / 道具 / 商店
- **植物设定文件**:每株植物一个带注释的 JSONC 文件(`server/data/crops/<slug>.json`),是植物设定的**事实源**;改文件 → 重启/重跑 seed 即生效
- **15 种植物**:水稻/小麦/谷子/高粱/荞麦/玉米/大豆/花生/油菜/芝麻/白菜/大葱/萝卜/红薯/棉花,各有宜种窗/枯萎季节/加速季节/需水/需肥/单株价值上限/解锁要求
- **18 种道具**:15 种子 + 肥料(生长加速 50%)+ 水壶 + 节气卡;效果用 JSONB 定义,**加道具不改代码**
- **商店**:每用户独立商店(隔离/售空/周期补货),道具价 = base × item_factor;作物收购价 = base × sell_factor × 季节倍率 × 分类倍率,且不超过植物单株价值上限
- **收成仓**:收获入仓,按当前季节价择机出售(秋 1.2 / 冬 0.9 应季涨降)
- **AI 客人议价**:卖收成可走 LLM 客人讨价还价(1 份/单)——随机客人(王奶奶/陈大厨/小美)+ 多轮对话,成交价服务端权威校验(市场价×0.5~1.5,防刷钱);单活跃会话 + 30s 冷却 + 8 轮上限 + 历史截断控成本;旧快速卖出保留(双轨);客人模板 `data/guests.json` 配置化,`guest.*` 管理后台可调

### 扩展玩法
- **任务系统**:5 个种子任务,自动跟踪(无需接取),进度由服务器实时计算,奖励走账本
- **社交系统**:好友申请 / 接受 / 拒绝 / 删除全流程 + 名字搜索(`/social/search`,精确匹配重名全返回)+ UUID 查询公开资料(`/social/players/{id}`,含关系状态)+ 好友资料卡 + 好友农场参观(只读)+ **公开访客模式**(`/social/players/{id}/farm`,任意玩家田格数据,为浇水提供前置);互助浇水 / 偷菜为**预留接口**(契约已定,功能开发中);注册**允许重名**(班级同名场景),登录按"名字+密码"双匹配
- **成就系统**:配置驱动自动达成,解锁头衔
- **AI 助手**:OpenAI 兼容转发(DeepSeek/通义/智谱可插拔),每用户用量统计,管理后台配置 APIKEY
- **虫害系统**:每用户隔离调度;大虫害 = 音游对抗(防作弊:提交耗时校验,达标发奖励/不达标惩罚寄生);小虫害 = 寄生倒计时,到点摧毁作物,可驱赶
- **杂草系统**:每个节气内的随机时刻生长一次(每用户世界),随机覆盖最多 3 个地块,减慢该地块作物生长;新一次生长清除旧杂草

### 美术素材
- **作物**:15 种 × (种子 + 苗期/生长期/成熟 3 阶段)真实素材,预渲染 32/64/128/256 四档按分辨率下发
- **24 节气图**:同一预渲染管线,按节气序号取图
- **版本协议**:`/v1/art/version` 返回全局 + 逐作物 + 逐节气内容哈希,客户端据此刷新本地素材缓存

### 管理后台(/admin)
- **11 大板块**:仪表盘 / 用户列表 / 全局配置(`game_config` 热更新 + 环境变量只读打码)/ 作物管理(新增植物自动建种子 + 写回设定文件)/ 种植状态(全服每株实时)/ 道具管理 / 定价 / 节气设置 / 玩家世界(地块/背包/收成仓控制)/ 商店管理 / AI 设置 + 虫害设置
- **实时日志流**:WS `/v1/admin/logs` 只读日志监控(回放 200 行 + 增量,无 RCE 面)
- **安全模型**:独立 admin JWT(2 小时过期)、`ADMIN_ENABLED` 总开关、`ADMIN_PASSWORD` 为空拒绝一切登录

### 工程基础
- 响应信封 `{code, message, data}` 全接口统一;OpenAPI 自动文档(`/docs`)
- 主键 UUID;分页信封统一;JSONB 兜底可扩展;幂等 seed 导入
- 测试:63 个 pytest 用例全绿

## 1.2 部分实现 ⚠️

- **节气卡(term_lock)**:道具可购买,但"锁定节气"效果未实现(使用返回 `EFFECT_NOT_SUPPORTED`)
- **多 worker 广播**:当前节气广播为进程内任务,多 worker 会重复(生产需 Redis pub/sub,见第 7 章)

## 1.3 未实现 ❌(表已建 / 接口未做)

- 教育内容模块(知识卡片 / 每日一题)—— P1
- AI 增强(上下文记忆 / RAG 知识库 / 内容审核留痕)—— P1
- 排行榜
- 数据库迁移链 Alembic(当前开发用 create_all + 幂等 ALTER)
- 正式版登录扩展(手机号 / 昵称真名分离 / 家长绑定)
- 防沉迷(教育类定位暂不做,埋点保留便于合规加回)

## 1.4 计划中 📋(路线图)

### P1(下一步)
- 教育内容:知识卡片 / 每日一题 / 学习解锁闭环
- AI 增强:上下文记忆 / RAG(pgvector)/ 审核留痕
- 排行榜、节日活动
- Redis pub/sub 广播改造、Alembic 迁移链

### P2(后续)
- 班级 / 学校组织、教师后台
- 活动运营 CMS、埋点分析
- 正式版登录扩展、应季溢价定价

---

# 2. 核心机制详解

> 每个机制:运作方式 → 关键规则/公式 → 配置入口 → 相关 API。全部行为以代码为准,接口细节见 [API.md](API.md)。

## 2.1 时间与节气系统

**运作方式**:游戏时间由**公式计算**,不存日历表。全局参考时钟 `game_clock`(纪元 epoch + 倍速 time_scale),`elapsed = (now - epoch) × time_scale`;24 个节气按 `term_config` 顺序循环,每个节气默认 300 秒,一个完整循环约 2 小时。

**每用户独立世界**:每个玩家有独立的 `world_accum`(累计世界秒):
- **在线**(最近心跳 ≤ 300 秒内):按全局倍速 × 1.0 推进
- **离线**:按全局倍速 × 0.25 推进(`game_config: world.offline_factor` 可配)—— 离线不会完全停止,但成长更慢
- **首次同步**:继承全局参考时钟位置(新玩家从当前节气开始)
- **全局暂停**:管理后台暂停 → 所有玩家世界冻结在暂停时刻
- 节气切换只影响该玩家自己的世界,不同玩家可以处于不同节气

**配置入口**:管理后台"节气设置"(时长)/"时钟"(倍速/暂停);`term_config.json`(初始数据);`game_config: world.*`

**相关 API**:`GET /v1/calendar/current`(我的节气)、`PUT /v1/admin/terms/{i}`、`PUT /v1/admin/clock`、`GET/PUT /v1/admin/worlds`

## 2.2 账号与玩家

**运作方式**:注册(名字+密码)→ PBKDF2(10 万次迭代)哈希落库 → 签发 JWT(HS256,7 天)。登录同流程。注册/登录时自动记录 IP 并解析地理位置(ip2region 离线库,内网/解析失败降级为空)。

**资产体系**:金币走 `coin_transactions` 账本(每次变动留痕可审计);等级/经验/解锁节气为玩家字段;**经验自动升级**:累计经验每 100 升 1 级(`level = exp//100 + 1`,只升不降,管理后台手动调高保留);头衔由成就解锁(见 2.9)。经验来源:收获(每株 +2)、任务/成就奖励、大虫害达标(管理后台可直改)。

**封禁**:管理后台置 `status=0` → **即时生效**:登录被拒(`USER_BANNED`),已登录的 token 在下次请求时同样被拒(存量会话统一拦截),解封后恢复。

**配置入口**:管理后台"用户列表"(封禁/解封/改资产)。

**相关 API**:`POST /v1/auth/register|login`、`GET /v1/player/me`、`PATCH /v1/admin/users/{id}/status|assets`

## 2.3 农场系统

**田地**:4 列 × 5 行 = 20 格,`idx` 按行优先编号(1-20,`idx = (row-1)*4 + col`);每格土壤肥力(1-3,影响产量)、可加锁。一地一株(部分唯一索引:同一地块最多一株未收获/未摧毁作物,历史保留可再种)。

**播种校验链**(顺序执行,任一不过即拒绝):
1. **解锁**:植物 `unlock_exp`(经验)或 `unlock_level`(等级)**达到其一即可**(两者均 0 = 无门槛)→ 失败返回 `CROP_LOCKED`
2. **宜种窗**:当前节气 ∈ `sow_window`(term 精确窗 + grace 宽限轮次)→ 失败返回 `CROP_NOT_AVAILABLE`
3. **种子**:背包有对应种子道具(自动消耗 1 个,写 `item_transactions` 账本)

**生长计算**(服务器权威,客户端只展示):
- 进度 = 经过秒数 × 生长速率 / 有效生长时长 × 100;阶段:1 苗期(<50%)/ 2 生长期(<100%)/ 3 成熟
- **季节加速**:在植物 `fast_growth_seasons` 季节播种 → 有效生长时长 = 基础 ÷ 倍率(如水稻夏季 ×1.5 → 300s 变 200s)
- **水分衰减**:浇水补满 100,此后每节气 -10(自上次浇水/播种起);低于植物 `water_need.min` → 进度冻结在红线时刻(停滞)
- **杂草减速**:地块附杂草 → 生长速率 × `weed.slow_factor`(默认 0.5)
- **枯萎(冻死)**:玩家当前季节 ∈ 植物 `wither_seasons` → 未收获作物**标记枯萎**(`crop.status="wilted"`,进度冻结,**仍占地块、不直接消失**;WS 推 `crop_withered`)。枯萎作物不能浇水,玩家可 `clear` **铲除**(无产量)或 `harvest` **收割**(产量 ×0.5,入仓为**劣质收成**,商店收购价 ×0.3 大打折扣)

**收获**:成熟后收获 → 产量 = 基础 × (1 + 0.1×(肥力-1));土壤肥力 < 植物 `fertility_need` → 再乘 (soil/need) 减产。收成**入收成仓**(不直接给金币),结算留痕 `term_bonus_applied`;**每株收成 +2 经验**(响应含 exp_gained/level/leveled_up,累计 100 经验自动升级)。

**配置入口**:植物设定文件(窗/解锁/加速/需水/需肥/枯萎,见 2.4);管理后台可种/清/改生长、改肥力/锁定。

**相关 API**:`GET /v1/farm/state`、`POST /v1/farm/plots/{id}/sow|water|harvest|clear|weed-clear`、`GET /v1/admin/plantings`、管理后台地块控制 5 端点

## 2.4 植物设定文件(JSONC 事实源)

**运作方式**:每株植物一个文件 `server/data/crops/<slug>.json`,支持 `//` 注释。启动/重跑 seed 时幂等同步到 DB(`sync_crops` upsert,按名称匹配更新,不覆盖 active 状态)。**改文件 → 重启服务即生效**;管理后台增改植物会自动写回文件(文件 = 唯一事实源)。

**字段全表**:

| 字段 | 类型 | 说明 |
|---|---|---|
| `slug` | str | 唯一英文标识(素材目录/种子道具前缀) |
| `name` | str | 中文名 |
| `category` | str | 谷物/油料/蔬菜/经济作物/花卉(影响卖价分类倍率) |
| `sort_order` | int | 排序 |
| `sow_window` | dict | 宜种窗 `{type:"term", start, end, grace}` |
| `grow_seconds` | int | 基础生长时长 |
| `yield_base` | int | 基础收成量 |
| `base_price` | int | 基础收购单价 |
| `unlock_level` / `unlock_exp` | int | 解锁要求(等级/经验,其一即可) |
| `settings.wither_seasons` | list | 枯萎季节(spring/summer/autumn/winter) |
| `settings.fast_growth_seasons` | dict | 加速季节 `{季节: 倍率}` |
| `settings.water_need` | dict | 需水 `{min, ideal}`(低于 min 停滞) |
| `settings.fertility_need` | int | 需肥力(低于则减产) |
| `settings.max_value` | int | 单株卖价上限(0=不封顶) |
| `art`(可选) | dict | 素材路径覆盖(缺省用 slug 派生) |
| `note` | str | 备注 |

**新增植物三步**:复制 `_template.json` → 填字段 → 重启服务(种子道具自动生成:管理后台创建时勾选 auto_seed)。

## 2.5 商店与收成仓

**运作方式**:每个玩家一个独立商店实例(商品库存隔离,售空不共享;按 `restock_seconds` 周期补货)。道具与作物收购价都走公式,管理后台可全局覆盖 + 逐用户覆盖。

**价格公式**:
- 道具/种子售价 = `item.buy_price × item_factor`
- 作物收购价 = `base_price × sell_factor × season_effect[季节] × category_factor[分类]`,且 **≤ 植物 `max_value`**(单株上限)
- 默认系数:季节 春1.1/夏1.0/秋1.2/冬0.9;分类 谷物1.0/蔬菜1.1/花卉1.25;sell_factor 0.8

**收成仓**:收获入仓(不直接变现)→ 玩家在任意时刻按**当前季节价**出售(`POST /v1/shop/crops/{crop_id}/sell`)。秋收秋卖最赚,冬卖最亏 —— 择机出售是玩法空间。仓内区分**正常收成**(原价)与**枯萎劣质收成**(`wilted_quantity`,收购价 ×0.3);出售时先扣正常、再扣枯萎。

**配置入口**:管理后台"商店管理"(全局默认 + 逐用户覆盖/补货/重置)、"定价"(内联改价)。

**相关 API**:`GET /v1/shop/state|items|storage`、`POST /v1/shop/items/{id}/buy`、`POST /v1/shop/crops/{id}/sell`

## 2.6 道具系统

**运作方式**:道具目录 `items`(配置)+ 玩家背包 `user_items`(数量)+ 流水账本 `item_transactions`(每次增减留痕可审计)。效果由 `effect` JSONB 定义,加新道具只改配置不改代码。

**effect 类型表**:`seed`(种子,含 crop_id)/ `fertilizer`(肥料,生长加速 50%)/ `water`(水壶,浇水)/ `term_lock`(节气卡,锁定节气 —— 效果未实现 ⚠️)

**使用**:`POST /v1/player/inventory/{item_id}/use` 按 effect.type 分发(肥料 → 目标地块 boost_pct;水壶 → 浇水;种子 → 播种)。

## 2.7 任务系统

**运作方式**:任务配置(5 个种子任务)自动跟踪,无需接取 —— 服务器根据玩家行为实时计算进度(通用 condition 格式:类型/目标/当前值)。达成后 `POST /v1/quests/{id}/claim` 领取,奖励(金币/道具/经验)走账本。

**配置入口**:`data/quests.json`(seed 导入)。

## 2.8 社交系统

**运作方式**:好友 = 双向关系。发起申请 → 对方接受/拒绝 → 成为好友 → 可删除。申请不能重复、不能加自己。

**相关 API**:`GET /v1/social/friends|requests`、`POST /v1/social/requests`、`POST /v1/social/requests/{id}/accept|reject`、`DELETE /v1/social/friends/{id}`

## 2.9 成就系统

**运作方式**:成就配置驱动,达成条件与任务同格式(target 计数),自动达成后 `POST /v1/achievements/{id}/claim` 领取奖励;头衔(`head_title_id`)由成就解锁,玩家档案展示。

**配置入口**:`data/achievements.json`(seed 导入)。

## 2.10 AI 助手

**运作方式**:OpenAI 兼容协议转发 —— `POST /v1/ai/chat` 接收 `{messages, model}`,后端转发到配置的国内大模型(DeepSeek/通义/智谱可插拔),响应兼容 OpenAI 格式。**每用户用量统计**(token 数)落库,管理后台可查全服用量。

**配置入口**:管理后台"AI 设置"(APIKEY/模型/地址);`game_config: ai.*`。

**相关 API**:`POST /v1/ai/chat`、`GET /v1/ai/models|usage`、`GET/PUT /v1/admin/ai/config`、`POST /v1/admin/ai/test`、`GET /v1/admin/ai/usage`

## 2.11 虫害系统

**运作方式**:每用户隔离调度 —— 平均每 `window_terms`(默认 2)个节气触发 `events_per_window`(默认 3)次,间隔随机化(0.5~1.5×均值)。到点经 WS 推送给该玩家,已有进行中事件则顺延。

**节气/季节驱动(依据真实农时)**:
- **活跃窗口 `pest.active_terms`**(默认 **惊蛰~霜降** 3~18):窗口外(立冬~惊蛰前,含冬季)害虫越冬休眠,**完全不排虫** —— 冬天没有虫子。
- **季节频率 `pest.season_frequency`**:触发间隔 = 基准均值 ÷ 倍率。盛夏(夏 freq 1.5,间隔缩短,**虫害最频繁**)、初春(春 freq 0.6,刚复苏、稀疏)、秋(0.8 回落)、冬(0.0)。
- **季节大小虫比例 `pest.season_big_ratio`**:盛夏高温高湿**大虫灾最多**(0.5,如蝗灾/粘虫爆发期),春 0.3、秋 0.2 大虫害少,冬 0。

- **大虫害**(音游对抗):WS 广播含音游时长 → 前端游玩后提交成绩 → **防作弊**:提交耗时 ≥ 时长 × `min_elapsed_factor`(默认 0.6),过快直接拒绝(`PEST_RESULT_TOO_FAST`)→ 达标(score/max ≥ `pass_ratio` 0.6)发奖励(金币+随机道具);不达标按 miss//2 个随机地块寄生小虫害
- **小虫害**(寄生):1~5 个随机地块(有作物的)各挂倒计时(按生长阶段,苗期 120s/生长期 90s/成熟 60s,可配)→ 到点**摧毁作物**;玩家可驱赶(倒计时结束前驱赶成功则作物保住)

**离线应对**:触发循环在 WS 主循环里,玩家**不在线不产生虫害**。重新上线时做**离线补偿**(`sync_offline`):把离线期间错过/过期的排程**顺延到未来**,不会"一上线就遭虫灾";若回归时正处于非活跃窗(冬季/早春)则直接清空排程不排虫。

**配置入口**:管理后台"虫害设置"(pest.* 全部可调:enabled/频率/活跃窗口/季节频率/季节大小虫比例/大虫害参数/阶段倒计时);调试接口可强制触发/清除。

**相关 API**:`GET /v1/pest/state`(含 `season`/`pest_active`)、`POST /v1/farm/pest/{id}/result|drive-away`、`GET/PUT /v1/admin/pest/config`、`GET /v1/admin/pest/events`、`POST /v1/debug/pest/trigger|clear`

## 2.12 杂草系统

**运作方式**:每用户世界,每个节气内**随机一个时刻**生长一次(世界秒调度 `weed_scheduled_accum`;离线期间世界推进也会触发)。到点:在**未长草**地块中新增覆盖最多 `weed.max_plots`(默认 3)个地块(优先有作物的),杂草**累积**——不主动清就会一直长。杂草地块作物生长速度 × `weed.slow_factor`(默认 0.5)。全农场杂草总量有上限 `weed.max_total`(默认 12,20 格的 60%),防整田荒芜。WS 推 `weed_growth`。

**清除杂草**:① 播种 = 翻地整地 → 清除该格杂草(重新下种一并处理);② 玩家可对**单个地块** `POST /v1/farm/plots/{id}/weed-clear` 除草(只清所选格,原无杂草幂等返回 `cleared=false`);③ 管理/调试可一次清全部。清除后该格作物生长速率恢复。

**生态**:冬天杂草**照常生长**(越冬杂草真实存在,如麦田冬前除草),与"冬季无虫害"互补——冬天是唯一保留的"可主动干预"负面机制。

**配置入口**:`game_config: weed.*`(enabled/slow_factor/max_plots/max_total);调试接口强制触发/清除。

**相关 API**:farm state 的 `plots[].weeded` 与 `weed_events`、`POST /v1/farm/plots/{id}/weed-clear`(单格除草)、`POST /v1/debug/weed/trigger|clear`

## 2.13 美术素材管线

**运作方式**:源素材(PNG)导入后预渲染 32/64/128/256 四档(等比缩放,LANCZOS);客户端请求时按目标宽度 `w` 取**最小不小于 w** 的档(超出取最大档),零请求时渲染。作物每株 4 素材(种子 + 3 阶段),节气每节气 1 素材。

**素材版本协议**:`GET /v1/art/version` 返回全局 `version` + 逐作物 `crops` + 逐节气 `terms`(内容哈希)→ 客户端登录/节气切换时对比:全局变 → 全量刷新;单作物/单节气变 → 只刷该素材。

**素材目录**:`static/assets/crops/<slug>/{seed,1,2,3}.png`、`static/assets/terms/<slug>/main.png`(均含 `_{size}.png` 预渲染档)。

**相关 API**:`GET /v1/art/{kind}/{key}/{name}.png?w=`(统一资源接口,kind=crops/terms)、`GET /v1/art/version`、`GET /v1/art/manifest`

## 2.14 实时推送(WebSocket)

**运作方式**:`WS /v1/ws?token=` 长连接(玩家 JWT 走查询参数)。连接即推当前节气;此后服务端主动推送 7 类事件。**原则:事件是"何时刷新"的通知,数据以 REST 接口为准**。

| 事件 | 触发 | 客户端动作 |
|---|---|---|
| `solar_term_change` | 节气切换/连接首帧 | 更新节气 UI |
| `resources_changed` | 管理后台改该玩家资产 | **重新 GET /v1/player/me** |
| `pest_big` / `pest_small` | 虫害触发 | 弹音游 / 标红地块 |
| `pest_destroyed` | 寄生到点摧毁 | 刷新地块 |
| `crop_withered` | 季节枯萎(冻死) | 显示"植物冻死了"覆盖层(作物**仍占地块**,不消失) |
| `weed_growth` | 杂草生长 | 刷新地块 + 动画 |

心跳:客户端每 30s 发 `ping` → `pong`;断线自动重连(指数退避),重连首帧即当前节气。客户端接入代码见 API.md §9.4。

## 2.15 管理后台

**运作方式**:独立管理员体系(与玩家体系隔离)—— `ADMIN_ENABLED` 总开关;`ADMIN_PASSWORD` 为空**拒绝一切登录**;登录签发独立 admin JWT(2 小时);操作审计入 `event_logs`。`GET /admin` 为单页应用(登录 → 11 板块导航),`WS /v1/admin/logs` 实时日志流(只读,无 RCE 面)。

**11 板块**:仪表盘 / 用户列表 / 全局配置 / 作物管理 / 种植状态 / 道具管理 / 定价 / 节气设置 / 玩家世界 / 商店管理 / AI 设置与虫害设置。

**安全红线**:admin 凭据必须改默认值;生产环境 `ADMIN_ENABLED=false` 或仅内网开放;终端/日志类能力只读。

---
# 3. 技术栈与框架

| 框架/库 | 用途 | 关键点 |
|---|---|---|
| **FastAPI** | Web 框架 | 自动 OpenAPI 文档(`/docs`)、异步支持、依赖注入 |
| **SQLAlchemy 2.0** | ORM | 开发用 SQLite / 生产切 PostgreSQL;UUID 主键、JSONB 扩展 |
| **Pydantic v2** | 请求/响应校验 | 字段约束、类型转换,全接口统一 |
| **PyJWT** | 认证 | HS256;玩家 token 7 天 / admin token 2 小时双体系 |
| **PBKDF2**(标准库) | 密码哈希 | 10 万次迭代,无额外依赖 |
| **uv** | 依赖/工程管理 | `uv.lock` 锁定;国内镜像安装 |
| **uvicorn** | ASGI 服务器 | 开发直跑;生产由 systemd 托管 |
| **Pillow** | 美术预渲染 | 素材 32/64/128/256 四档等比缩放(LANCZOS) |
| **ip2region** | IP 地理位置 | 离线库,零外部请求,内网降级 |
| **pywinpty**(仅本机开发) | 终端桥 | 已废弃(管理后台改为只读日志流) |

# 4. 架构

## 4.1 分层结构

```
客户端(Godot / 管理后台浏览器)
      │  HTTP + WS
      ▼
┌─────────────────────────────────────────────┐
│ API 路由层(app/api)                          │
│   鉴权守卫 → 参数校验(Pydantic)→ 响应信封     │
├─────────────────────────────────────────────┤
│ 业务服务层(app/services)                     │
│   calendar / world(时间)· farm · shop ·      │
│   quests · social · achievements · ai ·      │
│   pest · weed · admin                        │
├─────────────────────────────────────────────┤
│ 数据层(app/models,SQLAlchemy)+ 横切          │
│   core:config / security / errors / deps     │
│   ws:连接管理与定向推送                       │
└─────────────────────────────────────────────┘
```

**请求生命周期**(以播种为例):`POST /v1/farm/plots/{id}/sow` → 玩家 JWT 守卫(含封禁检查/世界时钟同步)→ Pydantic 校验 → farm_service.sow:解锁校验 → 宜种窗校验 → 种子扣除(账本)→ 创建作物实例(服务器权威状态)→ 信封返回。

## 4.2 数据流(配置与实例分离)

```
data/crops/*.json(植物设定,事实源)──seed 同步──▶ crops 表(模板)
data/term_config.json ──▶ term_config 表(节气)
data/items.json ──▶ items 表(道具目录)
static/assets/**(美术源+预渲染档)──▶ /v1/art 按分辨率下发
玩家行为 ──▶ crop_instances(每株状态)/ coin_transactions(账本)/ item_transactions(账本)
```

## 4.3 时间模型(全局 vs 每用户)

```
墙钟(now)──▶ 全局参考 elapsed=(now-epoch)×scale ──▶ 节气公式(term_at)
                 │
                 └─▶ 玩家 world_accum(首次继承全局;在线 1× / 离线 0.25×)
                       └─▶ 玩家自己的节气/季节(独立世界)
作物生长走墙钟(与玩家世界解耦,离线不饿死);枯萎/杂草/虫害/商店季节价走玩家世界
```

## 4.4 进程模型

- **开发/演示**:单 uvicorn 进程,进程内后台任务负责节气广播(每用户 WS 定向推送)
- **生产多 worker**:⚠️ 广播任务每 worker 一份会重复 → 需 Redis pub/sub(见 7.3.4)

# 5. 目录结构

```
jieqi_backend/
├── README.md / API.md / ASSETS.md     # 本文档 / 接口参考 / 资源统一接口与素材清单
├── docs/                              # 设计文档(01框架/02Schema/03API)
└── server/
    ├── pyproject.toml / uv.lock       # uv 工程
    ├── conftest.py                    # 测试隔离(素材目录/植物设定文件)
    ├── data/
    │   ├── term_config.json           # 24 节气(时长可配)
    │   ├── crops/                     # ★ 植物设定:每株一个 JSONC(见 2.4)
    │   ├── items.json / quests.json / achievements.json
    ├── scripts/
    │   ├── seed.py                    # 幂等导入(启动自动执行,含 crops 同步)
    │   ├── crop_loader.py             # JSONC 加载器(注释剥离)
    │   ├── import_term_images.py      # 24 节气图导入+预渲染
    │   ├── verify_api_docs.py         # 文档↔代码一致性校验
    │   └── run_server.ps1 / stop_server.ps1   # 独立进程管理(Windows)
    ├── app/
    │   ├── main.py                    # 入口:lifespan(建表+迁移+seed+同步)
    │   ├── core/                      # config/security/errors/db/deps/utils/svg_art
    │   ├── models/                    # SQLAlchemy 模型(20+ 表)
    │   ├── schemas/                   # Pydantic 请求模型
    │   ├── services/                  # 业务逻辑(14 个 service)
    │   ├── api/                       # 路由(13 个模块,88 端点)
    │   ├── ws/                        # 连接管理 + 定向推送
    │   └── static/
    │       ├── admin.html             # 管理后台单页
    │       └── assets/crops|terms/    # 美术素材(源+预渲染档)
    └── tests/                         # 63 个 pytest 用例
```

# 6. 本地开发

## 6.1 环境要求

- Python 3.11+ / uv
- 依赖安装:`cd server && uv sync --default-index https://mirrors.aliyun.com/pypi/simple/`

## 6.2 配置(.env)

复制 `.env.example` 为 `.env`。关键项:`DATABASE_URL`(默认 SQLite dev.db)、`JWT_SECRET`、`ADMIN_USERNAME/ADMIN_PASSWORD/ADMIN_ENABLED`、`DEBUG_ENABLED`。**上线必须改默认 admin 密码与 JWT_SECRET**。

## 6.3 启动

```bash
# 方式一:前台直跑(开发)
cd server && uv run uvicorn app.main:app --host 0.0.0.0 --port 8000

# 方式二:独立进程(推荐,脱离会话,隐藏窗口+日志+PID)
powershell -File server/scripts/run_server.ps1
powershell -File server/scripts/stop_server.ps1   # 停止
```

## 6.4 测试

```bash
cd server && env -u PYTHONPATH uv run python -m pytest -v   # 63 用例
```

> `env -u PYTHONPATH` 是必须的:本机 Hermes 环境会注入自己的 site-packages,遮蔽项目 venv。

## 6.5 调试接口速查(需 DEBUG_ENABLED=true)

| 接口 | 作用 |
|---|---|
| `POST /v1/debug/config` | 热改 game_config(改配置不发版) |
| `POST /v1/debug/term/advance` | 推进节气(只影响自己) |
| `POST /v1/debug/grow` | 催熟指定地块 |
| `POST /v1/debug/pest/trigger\|clear` | 强制触发/清除虫害 |
| `POST /v1/debug/weed/trigger\|clear` | 强制触发/清除杂草 |

## 6.6 常见坑(Windows 开发)

- uvicorn 被杀后 python 子进程残留占端口 → `Get-NetTCPConnection -LocalPort 8000 | Stop-Process`
- git-bash curl 发中文 JSON 乱码 → 用 `--data @file` 或 Python 脚本
- 改 `data/crops/*.json` 后需重启服务才生效(seed 同步在启动时执行)

# 7. 部署指南

## 7.1 架构总览(生产)

```
客户端(Godot / 浏览器)
      │ HTTPS
      ▼
  Nginx(反向代理 + TLS + 静态缓存)
      │
      ▼
uvicorn × N workers(FastAPI)
      │                    ┌──────────────┐
      ├──▶ PostgreSQL 16+  │ Redis(计划):  │
      └──▶ (广播/缓存)      │ 节气广播 pub/sub│
                           └──────────────┘
```

> 每用户世界时钟:玩家请求时同步(在线 1×/离线 0.25×),多 worker 下天然一致(状态在 DB);唯一需要 Redis 的是节气广播的跨 worker 去重。

## 7.2 快速演示部署(单机直跑)

```bash
cd server && uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

- SQLite 单文件库,开箱即用;管理后台 `http://<host>:8000/admin`
- 演示环境建议 `DEBUG_ENABLED=true` 便于推进节气/催熟测试

systemd 托管(生产单机):

```ini
# /etc/systemd/system/jieqi.service
[Unit]
Description=jieqi backend
After=network.target

[Service]
WorkingDirectory=/opt/jieqi/server
ExecStart=/opt/jieqi/server/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=always
EnvironmentFile=/opt/jieqi/server/.env

[Install]
WantedBy=multi-user.target
```

## 7.3 正式部署(生产)

### 7.3.1 数据库:PostgreSQL 16+

```bash
# 云服务器上(以 Ubuntu 为例)
sudo -u postgres createdb jieqi
sudo -u postgres createuser jieqi_app --pwprompt
```

- `DATABASE_URL=postgresql://jieqi_app:***@127.0.0.1/jieqi`
- 模型已按 PG 友好设计(UUID 原生/JSONB/INET);当前开发用 `create_all` + 幂等 ALTER,上线前补 **Alembic 迁移链**:
  ```bash
  # alembic/env.py 指向 app.core.db 的 Base.metadata,autogenerate 生成迁移
  ```

### 7.3.2 环境变量清单

| 变量 | 必填 | 说明 |
|---|---|---|
| `DATABASE_URL` | ✅ | 生产用 PostgreSQL |
| `JWT_SECRET` | ✅ | 强随机,泄露=全部 token 可伪造 |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | ✅ | 强密码;为空拒绝一切管理登录 |
| `ADMIN_ENABLED` | 否 | 默认 true;生产可关 |
| `DEBUG_ENABLED` | 否 | 默认 false(调试接口必须关) |

### 7.3.3 Nginx 反向代理 + HTTPS

```nginx
# /etc/nginx/sites-available/jieqi
proxy_cache_path /var/cache/nginx/jieqi levels=1:2 keys_zone=jieqi_cache:10m max_size=1g inactive=7d;
server {
    listen 443 ssl;
    server_name api.example.com;
    ssl_certificate     /etc/letsencrypt/live/api.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.example.com/privkey.pem;

    client_max_body_size 10m;
    # 静态素材(管理后台 js/css)长缓存
    location /static/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_cache jieqi_cache;
        proxy_cache_valid 200 7d;
    }
    # 🔥 热点:统一资源接口(作物图/节气图,静态 PNG,全服最高频)
    location /v1/art/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_cache jieqi_cache;
        proxy_cache_valid 200 7d;
        add_header Cache-Control "public, max-age=86400";  # 客户端也可缓存
    }
    # 🔥 热点:素材版本 / 清单(客户端轮询缓存刷新)—— 短缓存,改素材后 30-60s 内生效
    location = /v1/art/version { proxy_pass http://127.0.0.1:8000; proxy_cache jieqi_cache; proxy_cache_valid 200 30s; }
    location = /v1/art/manifest { proxy_pass http://127.0.0.1:8000; proxy_cache jieqi_cache; proxy_cache_valid 200 60s; }
    # 动态 API(每用户鉴权/实时数据):一律不缓存
    location /v1/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_no_cache 1;
        proxy_cache_bypass 1;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;  # IP 地理依赖
    }
    # 管理后台页面
    location = /admin { proxy_pass http://127.0.0.1:8000; }
    # WS:节气推送 + 管理日志流(必须带 Upgrade 头)
    location /v1/ws {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
    location /v1/admin/logs {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

### 7.3.3.1 热点接口分析(缓存策略依据)

| 接口 | 热度 | 请求特征 | Nginx 策略 | 说明 |
|---|---|---|---|---|
| 统一资源接口(作物/节气图) | 🔥🔥🔥 全服最高 | 静态 PNG,每地块作物 / 每节气反复拉,内容不变 | **proxy_cache 7d** + `Cache-Control 86400` | 可进一步上 CDN / 对象存储前置;响应本身带 ETag 可用 304 |
| `/v1/art/version` | 🔥🔥 | 客户端每次进主界面轮询(缓存刷新依据) | 短缓存 **30s** | 改素材后 30s 内全网可见新版本 |
| `/v1/art/manifest` | 🔥 | 客户端启动拉一次全量清单 | 短缓存 **60s** | 与 version 同源(mtime+哈希),短缓存即可 |
| `/static/*` | 🔥 | 管理后台 js/css | 7d | 文件名带版本或内容哈希时更长 |
| `/v1/farm/state`、`/v1/player/me`、`/v1/calendar/current` | 🔥 高频 | **每用户动态数据 + JWT 鉴权** | 禁止缓存 | 缓存会串号/泄露,必须 `proxy_no_cache` |
| `/v1/ws`、`/v1/admin/logs` | 常连 | WebSocket 长连接 | Upgrade 透传 | 不能被 proxy_cache 拦截(WS 无缓存概念) |
| AI 问答、商店、任务/社交/管理端 | 中 | 动态 + 账本副作用 | 禁止缓存 | 任何带写操作的接口不得缓存 |

> 原则:静态素材**大胆缓存**(7d),版本元数据**短缓存**(30-60s),动态/鉴权/写操作**一律不缓存**。素材更新流程:替换 `static/assets/` 文件 → version 哈希自动变化 → 客户端 30s 内轮询到新版本 → 按 `crops[slug]`/`terms[slug]` 定向刷新。

### 7.3.4 多 worker 与节气广播(重要)

- 单进程:广播任务在进程内,直接定向推送,无问题
- 多 worker:每个 worker 都跑一份广播任务 → **同一事件推 N 次**
- 方案:广播改 **Redis pub/sub**(事件 → Redis → 各 worker 消费后定向推送);当前为 P1 计划项

### 7.3.5 安全清单

- [ ] `JWT_SECRET` 强随机、`ADMIN_PASSWORD` 强密码(非默认)
- [ ] `DEBUG_ENABLED=false`;`ADMIN_ENABLED=false` 或仅内网开放
- [ ] 防火墙只开 443;DB 不暴露公网
- [ ] HTTPS 全站;`X-Forwarded-For` 只信任 Nginx
- [ ] 备份策略(见 7.3.6)

### 7.3.6 数据备份与恢复

```bash
# PostgreSQL 每日备份(crontab)
0 3 * * * pg_dump jieqi | gzip > /backup/jieqi_$(date +\%F).sql.gz
# 恢复
gunzip -c /backup/jieqi_2026-08-14.sql.gz | psql jieqi
```

> 配置类数据(植物/节气/道具)在 `server/data/` 文件里,随代码仓库版本化,天然可重建;DB 只需备份运行时数据。

### 7.3.7 上线检查清单

- [ ] 全套测试通过(`env -u PYTHONPATH uv run python -m pytest -q`)
- [ ] 文档一致性校验通过(`uv run python -m scripts.verify_api_docs check`)
- [ ] 管理后台登录/仪表盘可用,admin 密码已改
- [ ] `/docs` OpenAPI 可达;`/v1/art/version` 返回正常
- [ ] 演示数据清理(dev.db 不携带上线)

# 8. 术语表与常见问题

## 8.1 术语表(全文档统一叫法)

| 术语 | 含义 | 对应英文/字段 |
|---|---|---|
| 节气 | 24 节气之一(1-24,立春…大寒) | term / term_index |
| 地块 | 田地格子(4×5=20) | plot / idx |
| 宜种窗 | 植物可播种的节气区间 | sow_window(start/end/grace) |
| 宽限 | 宜种窗过后的额外可种轮次 | grace |
| 收成仓 | 收获作物的暂存仓库 | CropStorage / storage |
| 单株上限 | 单株卖价封顶 | max_value |
| 世界秒 | 玩家世界时钟的累计时间 | world_accum |
| 寄生 | 小虫害挂在地块上的倒计时 | PestTarget |
| 附杂草 | 地块被杂草覆盖的状态 | weeded |

## 8.2 常见问题

**Q: 怎么涨经验 / 升级?** ① 收获:每株收成 +2 经验(核心循环);② 任务/成就奖励;③ 大虫害达标(+5)。累计经验每 100 升 1 级(`level = exp//100+1`),解锁植物看"等级或经验其一"。

**Q: 收获为什么不给金币?** 收成入仓,玩家到商店按当前季节价择机出售(秋 1.2 倍最赚)。防"种了立刻卖"与鼓励季节规划。

**Q: 杂草怎么清除?** 玩家侧暂无需手动清除 —— 下一个节气的杂草生长会重新随机(旧杂草自动消失,存活不超过一个节气)。

**Q: 改了植物 JSON 文件不生效?** 植物设定在服务启动时同步进 DB,改文件后需重启服务(或重跑 seed)。

**Q: 玩家不在线,作物还长吗?** 生长走墙钟,一直长;但玩家世界(节气/季节)离线按 0.25× 减速 —— 枯萎/杂草/虫害等"季节驱动"事件因此也会变慢。

**Q: 节气卡(term_lock)为什么用不了?** 该效果尚未实现(P1),道具可买但使用返回 `EFFECT_NOT_SUPPORTED`。
