# 数据库 Schema 说明 v0.3(节气种田 · 教育+AI+模拟经营)

> 说明:本文档说明数据库表结构设计。配套文档:`01-AL2Wedu-backend-framework.md` / `03-API契约与扩展性设计.md`
> 技术底座:PostgreSQL 16+ / pgvector / Redis

## 1. 变更记录

| 版本 | 变更 | 原因 |
|---|---|---|
| v0.1 | 初版(真实日期节气表、手机号/微信登录、防沉迷) | 初始设计 |
| v0.2 | 主键改 UUID;移除微信与防沉迷;节气改轮转制(5 分钟切换);新增定价规则、头衔、道具 | 团队决策 |
| v0.3 | 定价简化(去掉浮动价表,静态价+调试端口);成就解锁头衔;users 增加 IP;播种窗定为精细节气窗 | 团队决策 |

## 2. 设计约定

1. **配置与实例分离**:作物/知识/题目/节气/道具/成就/头衔为配置数据;玩家相关为实例数据。配置演进通过 `active` 标记 + 新增行完成。
2. **节气为轮转时钟**:24 节气按节拍循环(默认每节气 300 秒),当前节气由游戏时钟公式计算,无年份表。
3. **主键使用 UUID**(生产环境 UUIDv7:时间有序;PG17 内置 `uuidv7()`,低版本使用 `gen_random_uuid()` v4)。
4. **时间统一 `timestamptz`(UTC)存储**,展示层转 UTC+8。
5. **账本模式**:货币与道具余额可重建,变动全部记流水(coin_transactions / item_transactions)。
6. **快照入实例**:播种节气、结算加成写入实例表,可审计、可做丰收记录。
7. **删除策略**:配置表 `active` 软删;实例数据保留历史。
8. **背景大数据可运维**:`game_config` KV + 配置表,调试端口热改,不发版。

## 3. ER 总览

```
users ──1:1── players ──1:1── farms ──1:N── plots ──0..1── crop_instances ──N:1── crops(配置)
 │                   │            │                                          └─播种窗/加成
 │                   ├──1:N── coin_transactions(流水)
 │                   ├──1:N── item_transactions(道具流水)
 │                   ├──1:N── term_progress(学习进度)
 │                   ├──1:N── user_quiz_records ──N:1── quiz_questions(配置) ──knowledge_items(配置)
 │                   ├──1:N── ai_sessions ──1:N── ai_messages(审核留痕)
 │                   ├──1:N── event_logs(埋点)
 │                   ├──N:M── user_titles ──N:1── titles(配置,头衔)
 │                   ├──N:M── user_achievements ──N:1── achievements(配置)
 │                   ├──N:M── user_items ──N:1── items(道具,配置)
 │                   ├──N:M── friendships
 │                   ├──N:M── classes / class_members(P2)
 │                   └──N:M── user_quests ──N:1── quests(配置)

背景大数据(配置域,运营热加载):
term_config(节气节拍) · game_clock(游戏时钟,单行) · game_config(KV) · items(道具目录)
crops · knowledge_items · quiz_questions · titles · achievements · quests
```

## 4. 表结构

### 4.1 账号与玩家

```sql
-- 账号(demo 版):登录使用 名字 + 密码
CREATE TABLE users (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name          VARCHAR(32) UNIQUE NOT NULL,   -- 登录名(也是显示名)
    password_hash VARCHAR(255) NOT NULL,
    status        SMALLINT NOT NULL DEFAULT 1,   -- 1正常 0封禁
    register_ip   INET,                          -- 注册 IP(审计/风控)
    last_login_ip INET,                          -- 最近登录 IP
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_login_at TIMESTAMPTZ
);
-- 正式版演进:phone(家长绑定)、display_name/real_name 分离(隐私)、第三方登录

-- 玩家档案:游戏进度 + 用户资产(农田见 farms,钱财见 coins,道具见 user_items)
CREATE TABLE players (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID NOT NULL UNIQUE REFERENCES users(id),
    level               INT NOT NULL DEFAULT 1,
    exp                 BIGINT NOT NULL DEFAULT 0,   -- 学识值(经验)
    coins               BIGINT NOT NULL DEFAULT 0,   -- 钱财(余额,以流水重建)
    head_title_id       UUID,                        -- 当前佩戴头衔
    unlocked_term_index SMALLINT NOT NULL DEFAULT 1, -- 教学进度:已解锁学习的节气上限(1-24)
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_active_at      TIMESTAMPTZ
);

-- 货币流水:一切 coins 变动记账(审计/对账)
CREATE TABLE coin_transactions (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    player_id  UUID NOT NULL REFERENCES players(id),
    amount     BIGINT NOT NULL,               -- 正=收入 负=支出
    reason     VARCHAR(32) NOT NULL,          -- sow/harvest/quest/quiz_reward/sell/adjust
    ref_id     UUID,                          -- 关联单据
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_coin_tx_player ON coin_transactions (player_id, created_at DESC);
```

### 4.2 头衔与成就

```sql
-- 头衔配置(节气主题头衔:如"立春小农""谷雨布谷"),由成就解锁
CREATE TABLE titles (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name             VARCHAR(32) NOT NULL,
    icon             TEXT,
    description      TEXT,
    unlock_condition JSONB,                  -- {"achievement_id":"..."} 由成就解锁
    sort_order       INT NOT NULL DEFAULT 0,
    active           BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE user_titles (
    player_id   UUID NOT NULL REFERENCES players(id),
    title_id    UUID NOT NULL REFERENCES titles(id),
    unlocked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (player_id, title_id)
);

CREATE TABLE achievements (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        VARCHAR(64) NOT NULL,
    description TEXT,
    category    VARCHAR(16) NOT NULL,         -- sow/harvest/quiz/term/collect
    target      JSONB,                        -- {"count":6,"terms":[1,2,3,4,5,6]}
    reward      JSONB,                        -- {"coins":200,"title_id":"..."}
    hidden      BOOLEAN NOT NULL DEFAULT FALSE,
    active      BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE user_achievements (
    player_id      UUID NOT NULL REFERENCES players(id),
    achievement_id UUID NOT NULL REFERENCES achievements(id),
    progress       JSONB NOT NULL DEFAULT '{}',
    completed      BOOLEAN NOT NULL DEFAULT FALSE,
    completed_at   TIMESTAMPTZ,
    PRIMARY KEY (player_id, achievement_id)
);
```

### 4.3 农田与作物

```sql
CREATE TABLE farms (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id   UUID NOT NULL UNIQUE REFERENCES players(id),
    name       VARCHAR(32) NOT NULL DEFAULT '我的农场',
    plot_count SMALLINT NOT NULL DEFAULT 6,
    theme      SMALLINT,                      -- 场景皮肤(后续)
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 农田状态 = plots 列表(API 按 idx 返回 list)
-- 播种规则:每个格子独立选择种什么(玩家播种时自选 crop_id)
CREATE TABLE plots (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    farm_id      UUID NOT NULL REFERENCES farms(id),
    idx          SMALLINT NOT NULL,           -- 地块编号 1..N
    soil_quality SMALLINT NOT NULL DEFAULT 1,
    locked       BOOLEAN NOT NULL DEFAULT FALSE,
    UNIQUE (farm_id, idx)
);

-- 作物配置:每个植物可种的季节/节气窗;种植状态见 crop_instances
-- sow_window 采用精细节气窗写法(term 类型):
--   {"type":"term","start":5,"end":7,"grace":2}  谷雨前后可种,错过可延后 2 轮
-- 季节映射仅作展示辅助:春=1-6 夏=7-12 秋=13-18 冬=19-24(见枚举字典)
CREATE TABLE crops (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name         VARCHAR(32) NOT NULL,
    category     VARCHAR(16) NOT NULL,        -- 谷物/蔬菜/瓜果/花卉
    icon         TEXT,
    sow_window   JSONB NOT NULL,              -- 可种节气窗定义
    grow_seconds INT NOT NULL,                -- 生长时长(按节气节拍配:900=3个节气)
    yield_base   INT NOT NULL,
    base_price   INT NOT NULL,                -- 基础价(静态定价)
    unlock_level INT NOT NULL DEFAULT 1,
    description  TEXT,                        -- 农谚/百科
    sort_order   INT NOT NULL DEFAULT 0,
    active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 作物实例(玩家种下的)= 每一株植物的完整种植状态机:
--   生命周期: stage(苗期→生长期→成熟) + growth_progress(0-100)
--   养护状态: water_level(需浇水) + soil_quality(地块提供)
--   节气影响: sowed_term_index(播种节气快照) + term_bonus_applied(加成结算快照)
--   收获状态: predicted_harvest_at / harvested_at / yield_actual
CREATE TABLE crop_instances (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    plot_id              UUID NOT NULL UNIQUE REFERENCES plots(id), -- 一地一株(MVP)
    crop_id              UUID NOT NULL REFERENCES crops(id),
    sowed_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    sowed_term_index     SMALLINT NOT NULL,   -- 播种时节气快照
    stage                SMALLINT NOT NULL DEFAULT 1, -- 1苗期 2生长期 3成熟
    water_level          SMALLINT NOT NULL DEFAULT 100,
    growth_progress      INT NOT NULL DEFAULT 0,
    predicted_harvest_at TIMESTAMPTZ,
    term_bonus_applied   JSONB,               -- 结算加成快照(审计)
    harvested_at         TIMESTAMPTZ,         -- 非空=已收获
    yield_actual         INT,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_crop_inst_plot ON crop_instances (plot_id) WHERE harvested_at IS NULL;
```

### 4.4 道具系统

```sql
-- 道具目录(配置):所有道具统一一张表,效果用 JSONB 定义;新增道具 = 新增一行,零迁移
CREATE TABLE items (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code         VARCHAR(32) UNIQUE NOT NULL,   -- 稳定业务码:seed_rice / fertilizer / term_card
    name         VARCHAR(32) NOT NULL,
    category     VARCHAR(16) NOT NULL,          -- seed种子/fertilizer肥料/tool工具/card卡/deco装饰/material材料
    icon         TEXT,
    stackable    BOOLEAN NOT NULL DEFAULT TRUE,
    max_stack    INT NOT NULL DEFAULT 999,
    effect       JSONB NOT NULL DEFAULT '{}',   -- 效果定义(开放 schema)
    buy_price    INT,                           -- 商店售价(NULL=不可购买)
    sell_price   INT,                           -- 回收价
    unlock_level INT NOT NULL DEFAULT 1,
    active       BOOLEAN NOT NULL DEFAULT TRUE,
    sort_order   INT NOT NULL DEFAULT 0,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- effect 示例(开放 schema,新增玩法不改表):
--   种子:  {"type":"seed","crop_id":"<crops.id>"}      播种时消耗 1 个
--   肥料:  {"type":"boost","growth_pct":50}            生长加速 50%
--   浇水:  {"type":"water","amount":100}               补满水分
--   节气卡: {"type":"term_lock","lock_terms":3}        锁定当前节气 3 轮(防错过播种窗)
--   装饰:  {"type":"deco","theme":2}                   农场皮肤

-- 玩家道具(实例):一玩家一道具一行,数量累加
CREATE TABLE user_items (
    player_id  UUID NOT NULL REFERENCES players(id),
    item_id    UUID NOT NULL REFERENCES items(id),
    quantity   INT NOT NULL DEFAULT 0,
    extra      JSONB NOT NULL DEFAULT '{}',     -- 扩展位:绑定状态/有效期/自定义属性
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (player_id, item_id)
);

-- 道具流水(账本,与 coin_transactions 同模式):获得/消耗都记账
CREATE TABLE item_transactions (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    player_id  UUID NOT NULL REFERENCES players(id),
    item_id    UUID NOT NULL REFERENCES items(id),
    delta      INT NOT NULL,                    -- 正=获得 负=消耗
    reason     VARCHAR(32) NOT NULL,            -- buy/sow/use/reward/quest/gift
    ref_id     UUID,                            -- 关联单据(crop_instances.id 等)
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_item_tx_player ON item_transactions (player_id, created_at DESC);
```

### 4.5 节气轮转时钟

```sql
-- 节气节拍配置(24 行):轮转制的全部定义
CREATE TABLE term_config (
    term_index       SMALLINT PRIMARY KEY,    -- 1-24
    name             VARCHAR(8) NOT NULL,     -- 立春..大寒
    icon             TEXT,
    duration_seconds INT NOT NULL DEFAULT 300, -- 每节气停留(默认 5 分钟,运营可调)
    sort_order       SMALLINT NOT NULL
);

-- 游戏时钟(单行,服务端权威):epoch + 倍速 + 暂停
CREATE TABLE game_clock (
    id         SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    epoch      TIMESTAMPTZ NOT NULL,          -- 游戏纪元起点(第 0 轮立春)
    time_scale NUMERIC(6,3) NOT NULL DEFAULT 1.0, -- 倍速(运营可调)
    paused_at  TIMESTAMPTZ,                   -- 非空=暂停(暂停期间时钟冻结)
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 当前节气(公式,无表查询):
--   elapsed_sec = (now() - epoch) × time_scale   (暂停时冻结)
--   term_index  = floor(elapsed_sec / duration_seconds) % 24 + 1
--   cycle       = floor(elapsed_sec / (duration_seconds × 24))  -- 轮次(成就/统计用)

-- 背景大数据 KV:运营热加载,不改代码
CREATE TABLE game_config (
    key         VARCHAR(64) PRIMARY KEY,
    value       JSONB NOT NULL,
    description TEXT,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- 示例键: sow.grace_terms=2(播种宽限轮数) / ai.quiz_daily=1 / event.spring_fair=on
```

### 4.6 定价策略

```sql
-- 定价策略:静态价,不常变
-- 价格在配置表字段上:items.buy_price / items.sell_price / crops.base_price
-- demo 调试:调试端口直接改配置表字段,即时生效,不发版(见 03 文档 §7 调试接口)
-- 正式版如做"应季溢价"教育玩法,再启用 price_rules(节气系数)表;当前不建表
```

### 4.7 教育内容

```sql
CREATE TABLE knowledge_items (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    term_index SMALLINT NOT NULL,            -- 挂节气(1-24)
    category   VARCHAR(16) NOT NULL,         -- origin起源/agronomy农谚/poetry诗词/custom习俗/food食养
    title      VARCHAR(64) NOT NULL,
    content    TEXT NOT NULL,
    audio_url  TEXT,
    source     VARCHAR(128),                 -- 来源标注(合规)
    difficulty SMALLINT NOT NULL DEFAULT 1,
    active     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_knowledge_term ON knowledge_items (term_index, category);

CREATE TABLE knowledge_embeddings (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    knowledge_item_id UUID NOT NULL REFERENCES knowledge_items(id),
    model             VARCHAR(32) NOT NULL,  -- bge-m3 / text-embedding-v3
    embedding         vector(1024) NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (knowledge_item_id, model)
);
CREATE INDEX idx_knowledge_emb ON knowledge_embeddings
    USING hnsw (embedding vector_cosine_ops);

CREATE TABLE quiz_questions (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    term_index        SMALLINT NOT NULL,
    difficulty        SMALLINT NOT NULL DEFAULT 1,
    question          TEXT NOT NULL,
    options           JSONB NOT NULL,
    answer            SMALLINT NOT NULL,
    explanation       TEXT,
    knowledge_item_id UUID REFERENCES knowledge_items(id),
    active            BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE user_quiz_records (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    player_id   UUID NOT NULL REFERENCES players(id),
    question_id UUID NOT NULL REFERENCES quiz_questions(id),
    answer      SMALLINT,
    correct     BOOLEAN,
    answered_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_quiz_rec_player ON user_quiz_records (player_id, answered_at DESC);

-- 教学进度:学习不绑轮转(已解锁节气随时可学),答题/活动绑"当前节气"
CREATE TABLE term_progress (
    player_id    UUID NOT NULL REFERENCES players(id),
    term_index   SMALLINT NOT NULL,
    cards_read   INT NOT NULL DEFAULT 0,
    quiz_best    INT NOT NULL DEFAULT 0,
    unlocked_at  TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,                -- 学完可解锁下一节气(players.unlocked_term_index 推进)
    PRIMARY KEY (player_id, term_index)
);
```

### 4.8 AI 会话

```sql
CREATE TABLE ai_sessions (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    player_id    UUID NOT NULL REFERENCES players(id),
    session_type VARCHAR(16) NOT NULL,       -- chat/quiz/help
    context      JSONB,                      -- 当前节气/进度快照(注入 prompt)
    token_usage  JSONB,                      -- 成本统计
    status       SMALLINT NOT NULL DEFAULT 1,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE ai_messages (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id    UUID NOT NULL REFERENCES ai_sessions(id),
    role          VARCHAR(8) NOT NULL,       -- user/assistant
    content       TEXT NOT NULL,
    reviewed      BOOLEAN NOT NULL DEFAULT FALSE,
    review_result JSONB,                     -- 审核详情(未成年人合规留痕)
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_ai_msg_session ON ai_messages (session_id, created_at);
```

### 4.9 社交 / 任务 / 埋点(P1-P2)

```sql
CREATE TABLE friendships (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    player_a   UUID NOT NULL REFERENCES players(id),
    player_b   UUID NOT NULL REFERENCES players(id),
    status     SMALLINT NOT NULL DEFAULT 0,  -- 0待接受 1好友
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (player_a, player_b)
);

CREATE TABLE classes (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        VARCHAR(64) NOT NULL,
    school_name VARCHAR(64),
    invite_code VARCHAR(8) UNIQUE,
    teacher_uid UUID REFERENCES users(id),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE class_members (
    class_id  UUID NOT NULL REFERENCES classes(id),
    player_id UUID NOT NULL REFERENCES players(id),
    role      SMALLINT NOT NULL DEFAULT 1,   -- 1学生 2教师
    joined_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (class_id, player_id)
);

CREATE TABLE quests (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title      VARCHAR(64) NOT NULL,
    description TEXT,
    quest_type VARCHAR(16) NOT NULL,         -- sow/harvest/quiz/ai_chat/term_complete
    target     JSONB,                        -- {"count":3} / {"term_index":6}
    reward     JSONB,                        -- {"coins":100,"exp":50}
    term_index SMALLINT,                     -- 可挂节气(节气主题活动)
    active     BOOLEAN NOT NULL DEFAULT TRUE
);
CREATE TABLE user_quests (
    quest_id     UUID NOT NULL REFERENCES quests(id),
    player_id    UUID NOT NULL REFERENCES players(id),
    progress     JSONB NOT NULL DEFAULT '{}',
    completed    BOOLEAN NOT NULL DEFAULT FALSE,
    completed_at TIMESTAMPTZ,
    PRIMARY KEY (quest_id, player_id)
);

-- 埋点(运营/教研分析;量大后迁 ClickHouse)
CREATE TABLE event_logs (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    player_id  UUID,
    event_name VARCHAR(64) NOT NULL,  -- solar_term_change/plant/harvest/quiz_answer/ai_chat
    payload    JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_event_name_time ON event_logs (event_name, created_at DESC);
```

## 5. 枚举字典

| 枚举 | 取值 |
|---|---|
| term_index | 1立春 2雨水 3惊蛰 4春分 5清明 6谷雨 7立夏 8小满 9芒种 10夏至 11小暑 12大暑 13立秋 14处暑 15白露 16秋分 17寒露 18霜降 19立冬 20小雪 21大雪 22冬至 23小寒 24大寒 |
| season ↔ term | 春=1-6 夏=7-12 秋=13-18 冬=19-24(按 term_index 整除 6 分组) |
| crops.category | 谷物 / 蔬菜 / 瓜果 / 花卉 |
| items.category | seed 种子 / fertilizer 肥料 / tool 工具 / card 卡 / deco 装饰 / material 材料 |
| knowledge_items.category | origin 起源 / agronomy 农谚 / poetry 诗词 / custom 习俗 / food 食养 |
| crop_instances.stage | 1 苗期 / 2 生长期 / 3 成熟 |
| ai_sessions.session_type | chat / quiz / help |
| coin_transactions.reason | sow / harvest / sell / quest / quiz_reward / adjust |
| quests.quest_type | sow / harvest / quiz / ai_chat / term_complete |

## 6. 查询路径与 Redis

| 场景 | 实现 | 索引 |
|---|---|---|
| 登录/取玩家 | users by name → players by user_id | users.name UNIQUE |
| 农田状态 list | farms by owner_id → plots 按 idx | UNIQUE(farm_id, idx) |
| 种地/收菜 | crop_instances by plot_id(未收) | 部分索引 WHERE harvested_at IS NULL |
| 当前节气 | 公式计算,无表查询 | Redis `solar:current` 缓存,每 5 分钟刷新 |
| 节气知识卡片 | knowledge_items by (term_index, category) | idx_knowledge_term |
| AI 检索 | pgvector HNSW cosine | idx_knowledge_emb |
| 学习进度 | term_progress by player_id | PK(player_id, term_index) |
| 每日一题 | quiz_questions by term_index + 已答过滤 | 应用层缓存 |
| 定价 | 静态价:直接读配置表字段 | — |
| 排行榜 | Redis ZSET(level / 节气完成数) | — |
| AI 会话续聊 | ai_messages by session_id 最近 N 条 | idx_ai_msg_session |

Redis 键:

| 键 | 内容 | 失效 |
|---|---|---|
| `solar:current` | 当前节气 + cycle + 剩余秒 | 每节气切换(5 分钟)更新 |
| `rank:level` / `rank:terms` | 排行榜 ZSET | 定期重建 |
| `ai:session:{id}:recent` | 会话最近 10 条 | 30 分钟 |
| `quiz:today:{player}` | 今日答题配额 | 每日重置 |
| `player:{id}:coins` | 余额读缓存 | 写穿透 |
| `player:{id}:items` | 道具数量缓存 | 写穿透 |

## 7. 种子数据

1. `term_config`:24 行(节气名 + 默认 300 秒)。
2. `crops`:首批 6 种(水稻、小麦、白菜、番茄、棉花、菊花),每种含精细节气窗 + 宽限期。
3. `knowledge_items`:每节气 5 类 × 2 条;起步先 3 个节气 × 5 类示范。
4. `quiz_questions`:每节气 5 题起步。
5. `titles`:节气主题头衔 6 个起步;`achievements` 与头衔联动(如"集齐 6 节气卡片"解锁头衔)。
6. 定价:静态价写在配置表字段;demo 用调试端口改,不建浮动价表。
7. `items`:首批 3 类(水稻种子、肥料、节气卡);产出/消耗走 item_transactions 账本。
8. seed 与代码同仓 `server/data/*.json`,幂等导入(`ON CONFLICT DO NOTHING`)。

## 8. 决策记录

| 决策项 | 结论 |
|---|---|
| 主键 | UUID(生产 UUIDv7) |
| 登录 | demo:名字+密码;正式版扩展手机号/第三方 |
| 节气机制 | 轮转制,默认每节气 300 秒(5 分钟),时长可配置 |
| 播种窗口 | 精细节气窗(term 类型)+ grace 宽限期;季节映射仅展示 |
| 教学解锁 | 学习不绑轮转;答题/活动绑当前节气;完成本节气学习解锁下一个 |
| 定价 | 静态价 + 调试端口热改,不做浮动价 |
| 头衔 | 成就解锁头衔(非商城) |
| 道具(MVP) | 种子/肥料/节气卡三类;获取 = 商店购买 + 任务奖励,账本记录 |
| 用户 IP | users 记录注册 IP 与最近登录 IP |

## 9. 后续演进

| 演进 | 做法 |
|---|---|
| 切回真实日期节气 | game_clock 换真实日历实现(双模式开关),term_index 语义不变 |
| 多农场/参观 | farms.owner_id 索引 + 只读接口 |
| 多作物同地块 | 去掉 crop_instances.plot_id UNIQUE |
| 分库分表 | 已是 UUID,按 player_id 分片 |
| 埋点量大 | event_logs 迁 ClickHouse,PG 留 30 天 |
| 天气系统 | weather_config(term_index, 概率) + 实例表 |
| 教师报表 | 从 term_progress / quiz_records / event_logs 聚合 |
| 家长绑定 | users.phone 已有,加 parent 关联表即可 |
| 应季溢价 | 如需"应季"教育玩法,启用 price_rules(节气系数)表 |
