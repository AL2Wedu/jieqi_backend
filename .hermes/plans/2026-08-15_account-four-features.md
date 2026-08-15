# 账号体系四件套实现计划:数字 ID / 注销留档 / 改名限速 / 兑换码

> **Goal:** ①用户增加对外纯数字 ID(uid_num)与查询接口;②增加"注销"状态(留档不删、冻结世界);③改名接口(单位时间限速,后台无限速);④兑换码(仅后台发布管理,单位时间限速)。全部按并发安全/账本/防爆破标准实现。

**Architecture:** 数据改动集中在 `users`(加列)+ 两张新表(redeem_codes / redeem_claims);行为改动集中在 `auth_service`(数字ID生成/注销/改名)+ 新 `redeem_service`(兑换码)+ `admin_service`(管理面);鉴权守卫与 `sync_world` 加注销拦截;限速统一走 `game_config`(rename.* / redeem.*)+ 用户列时间戳;奖励发放复用 `goal_service.grant_reward`(账本一致)。

**Tech Stack:** FastAPI + SQLAlchemy 2 + SQLite(既有);安全:码值 SHA-256 哈希存储、条件 UPDATE 原子抢占、防枚举统一报错、admin JWT 双体系。

---

## 0. 前置约定

- 状态枚举:`User.status`: `1` 正常 / `0` 封禁 / **`2` 注销**(新)
- 错误码(200xx 区,20005 及 20007+ 空闲):`20007 USER_DEACTIVATED`、`20008 RENAME_TOO_FREQUENT`、`20009 REDEEM_RATE_LIMITED`、`20010 REDEEM_INVALID`、`20011 REDEEM_CLAIMED`、`20012 REDEEM_EXHAUSTED`、`20013 UID_NOT_FOUND`
- 限速配置(game_config 可后台热改):`rename.cooldown_seconds`(默认 604800 = 7 天)、`redeem.cooldown_seconds`(默认 60)
- 迁移:所有新列走 `main.py` `_ensure_*` 幂等 ALTER 模式;老用户 uid_num 启动时补分配

## 功能一:纯数字外部 ID(uid_num)+ 查询接口

### 设计
- `users.uid_num BIGINT UNIQUE`(随机 7 位,1000000-9999999;**随机防枚举**,唯一冲突重试 ≤5 次,仍冲突扩位到 8 位)
- 注册时生成;老用户启动迁移批量补分配
- 对外展示:注册/登录/`/player/me`/社交公开资料均带 `uid_num`
- 新端点 `GET /v1/player/uid/{uid_num}` 🔐:按数字 ID 查任意玩家公开资料(与 `/social/players/{id}` 同构:name/level/农场/关系);不存在 → `20013`

### 任务
1. models: `users.uid_num` 列(unique,nullable)+ `main.py` `_ensure_uid_num_column()` 幂等 ALTER + 老用户补分配(启动时扫 NULL,逐个随机分配,幂等)
2. auth_service: `_gen_uid_num(db)`(随机+重试);register 接入;player_summary 加 `uid_num`
3. player.py: `GET /v1/player/uid/{uid_num}`(校验纯数字、查用户、返回公开资料)
4. 测试:注册带 uid_num、唯一性、查询命中/未命中、老用户迁移回填
5. API.md 同步 + verify_api_docs

## 功能二:注销状态(留档冻结)

### 设计
- `status=2` 注销;**数据绝不删除**(留档);世界冻结
- 冻结实现:①`get_current_player` 守卫(登录/存量 token)统一拦截 `status==2 → 20007`(与 20004 封禁同机制);②`sync_world` 对注销用户**不推进 world_accum**(冻结在注销时刻)
- 玩家侧:`POST /v1/auth/deactivate` 🔐(需当前密码 + `confirm: true`,防盗号注销);注销即 token 失效
- 管理侧:`PUT /v1/admin/users/{user_id}/status`(既有封禁端点扩为支持 2 注销 + 恢复 1;管理后台用户弹窗加"注销/恢复")

### 任务
1. 守卫:`core/deps.py` `get_current_player` 加 `status==2 → 20007`;登录同理
2. `sync_world` 冻结:注销用户直接返回不推进(查询 user.status)
3. auth_service.deactivate(密码校验 + confirm + 置 status=2 + 注销时间列 `deactivated_at`)
4. admin_service:status 端点支持 2(注销)+ 恢复;admin.html 用户操作按钮
5. 测试:注销后登录拒(20007)、存量 token 拒、世界不推进、管理端注销/恢复、数据仍在
6. API.md 同步

## 功能三:改名接口(限速 + 后台无限)

### 设计
- `POST /v1/player/rename {new_name}` 🔐:校验(去空白、1-16 字符、与旧名不同)→ 限速(`rename.cooldown_seconds`,读 `players.rename_last_at` 列)→ 同步改 `users.name` + `players.name`
- 管理端:`PUT /v1/admin/users/{user_id}/rename`(无限速,admin JWT);管理后台用户弹窗加改名输入
- 限速未达 → `20008 RENAME_TOO_FREQUENT`(响应带剩余秒数)

### 任务
1. models: `players.rename_last_at` 列 + 幂等 ALTER
2. auth_service/player_service.rename_player(校验+限速+双表更新,事务)
3. player.py 路由;admin_service + admin.py 路由(无限速)
4. 测试:改名成功(两表同步)、限速拒(20008)、后台无限速改名、重名改名合法(放开重名后)
5. API.md 同步

## 功能四:兑换码(仅后台发布管理,限速)

### 设计
- 表 `redeem_codes`:id UUID PK / `code_hash`(SHA-256,唯一)/ `reward` JSONB(与任务奖励同构:{coins, exp, items:[{code,quantity}]})/ `batch_name` / `max_uses`(0=不限)/ `used_count` / `per_player_limit`(默认 1)/ `expires_at` / `active` / `created_by` / `created_at`
- 表 `redeem_claims`:id / player_id / redeem_code_id / claimed_at;`UNIQUE(player_id, redeem_code_id)` 防重复
- 管理端(admin JWT,全部带 created_by 留痕):
  - `POST /v1/admin/redeem/codes`:生成 1 个码(可指定 code 或随机 `RNG-XXXXXX` 风格,仅 [A-Z0-9] 6-24 位)或 `count=N` 批量;存哈希不存明文,**创建响应只回明文一次**
  - `GET /v1/admin/redeem/codes`(列表+用量/剩余)
  - `PUT /v1/admin/redeem/codes/{id}`(停用/启用/改次数/过期时间)
- 玩家端 `POST /v1/redeem {code}` 🔐:
  1. 限速:`redeem.cooldown_seconds`(成功失败都算,`players.redeem_last_attempt_at` 列)→ `20009`
  2. 查 `code_hash`;**无效/停用/过期统一 `20010 REDEEM_INVALID`**(不泄露码是否存在,防枚举)
  3. **原子抢占**(学过的模式):条件 UPDATE `used_count < max_uses → used_count+1`,rowcount!=1 → `20012 REDEEM_EXHAUSTED`
  4. per_player_limit:claims 计数 < limit 否则 `20011 REDEEM_CLAIMED`
  5. 发奖励:复用 `goal_service.grant_reward`(账本/防注入)→ 写 claims
- 安全要点:码哈希存储、统一错误防枚举、条件更新防并发超发、事务包裹、奖励走账本

### 任务
1. models 两张表 + 幂等迁移
2. redeem_service:create/issue(管理)/redeem(玩家,上述 5 步)/list/update;`_hash_code`(sha256)
3. admin.py 三个管理路由 + player 端 redeem 路由;`players.redeem_last_attempt_at` 列
4. 测试:发布-兑换成功(金币/经验/道具入账)、重复兑换 20011、次数用尽 20012、并发双兑只中一次(条件更新)、过期/无效 20010、限速 20009、管理端停用生效
5. API.md 同步

## 文件清单
- 改:`server/app/models/__init__.py`(users/players 加列 + 两张新表)、`server/app/main.py`(_ensure_* 迁移)、`server/app/core/deps.py`(守卫 20007)、`server/app/services/auth_service.py`(uid_num/注销/改名)、`server/app/services/world_service.py`(冻结)、`server/app/services/admin_service.py`(注销/改名/兑换码管理)、`server/app/api/auth.py`、`server/app/api/player.py`、`server/app/api/admin.py`、`server/app/static/admin.html`(弹窗按钮)、`API.md`、`README.md`
- 新:`server/app/services/redeem_service.py`
- 测试:`tests/test_auth.py`(或新建 `tests/test_account_features.py`)

## 验证
1. 每功能 TDD:先写测试 → 跑红 → 实现 → 跑绿
2. 全量:`env -u PYTHONPATH uv run python -m pytest -q`(101 → 预计 110+)
3. `env -u PYTHONPATH uv run python -m scripts.verify_api_docs check`(端点/错误码/引用三查)
4. dev.db 迁移实测(uid_num 回填 + 新表建表)
5. 真机冒烟:注册→数字ID查询→改名限速→发布兑换码→兑换→注销→登录被拒

## 风险与取舍
- **随机 uid_num**:防枚举但碰撞重试有(极低)失败率;7 位容量 900 万足够 demo
- **注销不可逆**(设计如此,留档);管理端可恢复(恢复=状态回 1,世界从冻结点继续)
- **兑换码统一 20010**:运营无法区分"码不存在/过期",换取防枚举安全;管理端列表可查真实状态
- **限速键可配**:默认 7 天改名 / 60s 兑换,运营可后台调
- **开放问题**:兑换码奖励是否支持道具(计划支持 items,发放走 grant_reward)—— 若 grant_reward 不支持下发道具则本版只发 coins+exp,文档注明
