# 后端架构审计报告(逻辑 Bug 与安全漏洞)

> 审计对象:`jieqi_backend`(FastAPI + SQLAlchemy 2 + SQLite/PostgreSQL)
> 审计方式:逐文件通读全部 8,485 行服务/API/核心代码 + 关键路径事实核查
> 审计日期:2026-08-15 · 审计人:Hermes Agent(全自主)

---

## 一、安全漏洞(按严重度排序)

### S1. JWT 密钥硬编码默认值(高危)

**位置**:`server/app/core/config.py:18`

```python
jwt_secret: str = "dev-secret-change-me-please-0123456789abcdef"
```

**事实**:`.env` 中**未配置** `JWT_SECRET`(已核查,`.env` 无该键),服务实际使用这个公开的默认密钥签发/校验全部玩家 JWT 与 admin JWT。

**影响**:任何知道该默认值的人都可以:
- 伪造任意玩家的登录 token(`sub=<任意 user_id>`)→ 冒充任意玩家;
- 伪造 admin token(`role=admin`)→ 直接接管管理后台(改资产/发兑换码/看全服数据)。

**修复**:启动时若 `JWT_SECRET` 未配置或等于默认值 → 随机生成并打印警告(与 ADMIN_PASSWORD 同款模式),或直接拒绝启动。

---

### S2. 调试接口默认开启且仅需玩家 token(高危)

**位置**:`server/app/core/config.py:21`(`debug_enabled: bool = True`);`server/app/api/debug.py` 全部端点仅 `Depends(get_current_player)`。

**事实**:`.env` 中 `DEBUG_ENABLED` 已显式配置(值已脱敏,但默认值就是 `True`)。任何注册玩家都能调用:
- `POST /v1/debug/config` → **改任意 game_config**(含 `ai.api_key`、`pest.reward_coins`、`world.offline_factor` 等);
- `POST /v1/debug/term/advance` → 推进自己的世界(刷节气);
- `POST /v1/debug/grow` → 催熟作物;
- `POST /v1/debug/pest/trigger` / `weed/trigger` → 刷虫害/杂草事件。

**影响**:玩家可自改 AI 配置(改 `ai.api_key` 指向自己服务器 → 窃取后续所有 AI 请求的 key 用途)、刷金币(改 `pest.reward_coins` 后触发虫害领奖)、绕过全部成长曲线。上线若忘关 = 灾难。

**修复**:`debug_enabled` 默认改 `False`;`/debug/config` 端点要求 admin token(改配置是运营行为,不该玩家可调)。

---

### S3. 登录/注册/管理端登录无任何限速(中危)

**位置**:`server/app/api/auth.py`(register/login)、`server/app/api/admin.py:39`(admin login)。

**事实**:已核查,三个入口均无频率限制、无失败计数、无验证码。密码为 PBKDF2(10 万次迭代,强度尚可),但:
- 注册接口可被脚本无限刷(每账号送 200 金币 + 20 格地 → 批量小号刷资源);
- 登录接口可被无限爆破(名字可重名,爆破面更大);
- admin 登录可被无限爆破(admin 密码若为弱密码,2 小时 token 即被接管)。

**修复**:注册/登录按 IP + 名字做滑动窗口限速(如 5 次/分钟);admin 登录失败计数 + 指数退避。

---

### S4. X-Forwarded-For 直接信任(中危)

**位置**:`server/app/api/auth.py:13-20` `_client_ip()`。

```python
xff = request.headers.get("x-forwarded-for")
if xff:
    first = xff.split(",")[0].strip()
    if first:
        return first
```

**事实**:直接取 `X-Forwarded-For` 首值,无任何校验。若服务直连公网(未置于可信反代后),攻击者可伪造任意 IP → 注册/登录的 `register_ip`/`last_login_ip`/地理位置全部可伪造(污染运营数据、绕过基于 IP 的限速)。

**修复**:仅当存在可信反代时启用 XFF(配置 `trusted_proxy` 白名单),否则用 `request.client.host`。

---

### S5. AI API Key 明文存 DB 且管理端可读回显(中危)

**位置**:`server/app/services/ai_service.py:16`(`ai.api_key` 存 `game_config` 表);`server/app/static/admin.html:847`(管理端输入框回显 `cfg.api_key` 明文)。

**事实**:`game_config` 表无加密;`masked_config()` 只对**非管理端**接口打码,管理端 `GET /v1/admin/ai/config` 返回明文 key(前端回显)。DB 泄露 = AI key 泄露;且 S2 下玩家可经 `/debug/config` 直接改 `ai.api_key`。

**修复**:key 加密存储(如 Fernet,密钥来自环境变量)或至少管理端也打码(只显示前 4 后 4,改时才重填);`/debug/config` 禁止写 `ai.*` 键。

---

### S6. CORS 全开(低危)

**位置**:`server/app/main.py:172` `allow_origins=["*"]`。

**事实**:任意网站可跨域调用本 API。玩家 token 在 Authorization 头,浏览器跨域需预检且不能带自定义头(除非 `allow_headers=["*"]` 也开了——这里确实开了),意味着恶意网页可**在用户已登录状态下**以用户身份调用 API(CSRF 式攻击面,虽无 cookie 但 token 若被前端存 localStorage 则不受影响;若存 cookie 则高危)。

**修复**:上线配置白名单域名;至少 `allow_credentials=False` 时收紧 `allow_headers`。

---

### S7. WS 连接数无上限(低危)

**位置**:`server/app/ws/__init__.py`(ConnectionManager 无连接数限制);`server/app/api/router.py:75`(WS 端点无并发限制)。

**事实**:每个玩家可开任意多个 WS 连接(manager.players 是 set,同 player 多连接合法),攻击者可开大量连接耗尽内存/文件描述符。

**修复**:每玩家连接数上限(如 5)+ 全局连接数上限。

---

## 二、逻辑 Bug(按影响排序)

### B1. 商店购买并发下金币扣减与库存抢占顺序缺陷(中危)

**位置**:`server/app/services/shop_service.py:184-252` `buy()`。

**事实**:先 `player.coins < price` 检查(行 207),再条件 UPDATE 抢库存(行 210-218),**然后**才 `player.coins -= price`(行 225)。两个并发请求同时通过余额检查后,各自扣库存成功,但 `player.coins -= price` 是**读改写**(非原子),SQLite 串行化下虽不会负余额,但 PostgreSQL 下两个事务可同时读到相同 coins → 都写回 `coins - price` → **少扣一次**(双花)。

**修复**:扣金币也走条件 UPDATE(`UPDATE players SET coins = coins - :price WHERE id=:id AND coins >= :price`),rowcount=0 则回滚库存。

---

### B2. 兑换码并发下"每人限领"检查与次数抢占顺序缺陷(中危)

**位置**:`server/app/services/redeem_service.py:207-231`。

**事实**:先原子抢占 `used_count+1`(行 207-218),**再**查 `RedeemClaim` 判断每人限领(行 220-227),超限时手动 `rc.used_count -= 1` 回滚(行 229)。但回滚不是条件更新:两个并发请求 A/B 同时抢占成功(used_count 2),A 查 claim 发现超限回滚(used_count 1),B 查 claim 也超限回滚(used_count 0)——**次数被回滚两次,实际只发了一次奖励但扣了两次次数**;反之若 A 成功 B 超限,B 回滚会把 A 的占用也回滚掉 → **超发**。

**修复**:先查 claim(每人限领)再抢占次数;或把 claim 插入与次数抢占放进同一条件更新(INSERT ... ON CONFLICT / 先插 claim 再抢次数,失败回滚 claim)。

---

### B3. 大虫害成绩提交:miss_count 无上限(低危)

**位置**:`server/app/services/pest_service.py:376` `miss_count = max(0, int(miss_count))`。

**事实**:`miss_count` 只 clamp 下限不 clamp 上限。客户端可提交 `miss_count=10^9` → 惩罚 `_spawn_small(count=max(1, miss_count//2))` 内部 `n = min(count, len(plots))` 有兜底,但 `ev.penalty` 记录的是 `len(payload["targets"])`(有兜底),实际不炸。**但** `miss_count` 无上限仍属输入校验缺失,且 `score`/`max_score` 虽 clamp 但 `max_score` 可被提交为 1 而 score 为 1 → ratio=1 恒达标(已 clamp score ≤ max_score,但玩家可自报 max_score=1,score=1 → 恒过)。**这是设计缺陷**:max_score 应由服务端按音游时长/难度推导,而非客户端自报。

**修复**:`max_score` 由服务端按 `duration_seconds` 推导(如 `max_score = duration * 10`),客户端提交的 max_score 仅作参考或忽略;`miss_count` clamp 到合理上限(如 1000)。

---

### B4. 枯萎作物收割后 `wilted_quantity` 与 `quantity` 的入仓分支在并发下可能重复入仓(低危)

**位置**:`server/app/services/farm_service.py:369-470` `harvest()`。

**事实**:`claimed` 条件更新(行 390-410)已防重复收割(并发第二个请求返回 yield=0),但**入仓发生在条件更新之后**(行 427-447),且入仓不是条件更新——若 `claimed==1` 后、`db.commit()` 前进程崩溃,事务回滚,无问题;但若 `_settle` 与 `apply_exp` 之间(行 448-452)异常,`harvested_at` 已提交而 `storage` 未提交 → 作物消失无收成。**事务边界不完整**:`db.commit()` 在行 448(入仓后)与行 452(经验后)各一次,中间无原子性保障。

**修复**:harvest 全程单事务(一个 commit),入仓与经验发放与 harvested_at 同事务提交。

---

### B5. `_settle_sale` 混合单价计算误导(低危)

**位置**:`server/app/services/shop_service.py:291` `"unit_price": price // quantity`。

**事实**:正常+枯萎混合出售时,`unit_price` 是混合均价(整除),客户端若用它乘 quantity 会得到与 `price` 不一致的值(整除截断)。非安全 bug,但易误导前端。

**修复**:返回 `normal_unit_price` 与 `wilted_unit_price` 两个字段,去掉混合均价。

---

### B6. 任务/成就 `evaluate` 的 `spend_coins` 用绝对值(低危)

**位置**:`server/app/services/goal_service.py:63-70`。

**事实**:`spent = sum(amount < 0)`,`cur = abs(int(spent))`。若管理端 `admin_edit` 扣过金币(amount<0),会计入"消费";若管理端加金币(amount>0)不计。语义上"消费"应只统计玩家主动消费(shop_buy/use),`admin_edit` 扣减不应算消费。**影响**:管理端扣币会意外推进"消费 X 金币"任务进度。

**修复**:`spend_coins` 只统计 `reason LIKE 'shop_buy%'` 或排除 `admin_edit`。

---

### B7. 改名后 `Player.name` 与 `User.name` 双写,但 `player_summary` 只读 `User.name`(低危)

**位置**:`server/app/services/player_service.py:58-59`(双写)、`server/app/services/auth_service.py:40`(只读 User.name)。

**事实**:`Player.name` 列实际无业务读取方(已核查,`player_summary` 用 `user.name`),双写是冗余且可能不一致(管理端 `rename_user` 也双写)。非 bug 但属死代码/不一致风险。

**修复**:统一只写 `User.name`,`Player.name` 列废弃(或保留但不再写)。

---

### B8. `list_quests` 中 daily 任务重置后 `completed_at` 清空但 `progress` 未重置(低危)

**位置**:`server/app/services/quest_service.py:17-30`。

**事实**:`_reset_daily_if_new_day` 把 status 置 0、completed_at/claimed_at 置 None,但 `uq.progress` 保留昨天的值;随后 `evaluate` 会重算覆盖(行 65-66),所以实际无影响。**但**若 `evaluate` 抛异常(如条件类型未知),progress 残留昨天数据。防御性修正:重置时清 progress。

---

### B9. `weed_service.schedule_next` 用 `random.uniform` 但 `random` 未用 SystemRandom(低危)

**位置**:`server/app/services/weed_service.py:72-81`、`pest_service.py:138`。

**事实**:杂草/虫害调度时刻用 `random`(Mersenne Twister,可预测)。虽非安全敏感(调度时刻可预测无直接利益),但既然 guest 已改 SystemRandom,调度类随机也应统一。**一致性修正**。

---

### B10. `admin_set_plot_crop` 的 `sowed_at` 回拨与 `predicted_harvest_at` 在 `growth_progress=0` 时 `sowed_at=now`(无影响,低危)

**位置**:`server/app/services/admin_service.py:909`。

**事实**:`progress=0` → `sowed_at = now - 0 = now`,正确;`progress=100` → `sowed_at = now - grow`,`predicted_harvest_at = now`,正确。无实际 bug,但 `watered_at` 设为 now 而 `water_level` 可能 <100,水分衰减从 now 起算,合理。**无需修复,记录在案**。

---

## 三、架构层面观察(非 bug,记录)

1. **模块化单体结构清晰**:api(路由薄层)→ services(业务)→ models(SQLAlchemy)→ core(安全/配置/错误)。WS 推送经 `manager.push_sync` 线程安全桥接,设计正确。
2. **并发防护模式统一**:条件 UPDATE 抢占(库存/次数/收割/领奖)是正确模式,但 B1/B2 暴露了"检查-抢占-回滚"顺序问题。
3. **每用户世界时钟 + 服务器权威推导**是正确设计;`crop_view` 纯函数化(无副作用)值得保持。
4. **文档纪律优秀**:API.md 与代码双向核对脚本(verify_api_docs)是亮点。
5. **测试覆盖良好**:135 个测试覆盖主要链路;但**缺少并发测试**(B1/B2 正是并发缺陷,现有测试全串行,测不出来)。

---

## 四、修复方案汇总(对应新分支实操)

| 编号 | 修复 | 涉及文件 |
|---|---|---|
| S1 | JWT_SECRET 未配置/默认值 → 启动随机生成 + 警告 | config.py |
| S2 | debug_enabled 默认 False;`/debug/config` 改 admin 门控 | config.py, debug.py |
| S3 | 注册/登录/admin 登录限速(内存滑动窗口,按 IP+名字) | auth.py, admin.py, 新 core/ratelimit.py |
| S4 | XFF 仅可信反代启用(trusted_proxy 配置) | auth.py, config.py |
| S5 | ai.api_key 管理端打码回显;`/debug/config` 禁写 ai.* | ai_service.py, admin.py, debug.py |
| S6 | CORS 白名单配置化(默认 localhost) | main.py, config.py |
| S7 | WS 每玩家连接数上限(5)+ 全局上限(1000) | ws/__init__.py, router.py |
| B1 | 扣金币改条件 UPDATE(coins >= price 原子扣减) | shop_service.py |
| B2 | 兑换码先查限领再抢次数(顺序修正) | redeem_service.py |
| B3 | max_score 服务端推导;miss_count 上限 | pest_service.py |
| B4 | harvest 单事务提交 | farm_service.py |
| B5 | 结算返回 normal/wilted 单价 | shop_service.py |
| B6 | spend_coins 排除 admin_edit | goal_service.py |
| B7 | 统一只写 User.name | player_service.py, admin_service.py |
| B9 | 调度随机统一 SystemRandom | weed_service.py, pest_service.py |

> B8/B10 记录在案,无需代码改动。
