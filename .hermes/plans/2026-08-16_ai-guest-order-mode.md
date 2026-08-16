# AI 客人"点菜购买"模式实现计划

> **For Hermes:** 按此计划逐步实现,每步 TDD + 提交。

**Goal:** 在保留现有议价接口(`/v1/shop/guest/*`)基础上,新增一套"点菜购买"模式的 AI 客人接口,前端可选接入。

**Architecture:** 新增独立路由前缀 `/v1/shop/order`(与议价 `/v1/shop/guest` 并存),复用现有 `AiGuestSession`/`AiGuestMessage` 表(加字段区分模式),复用 `shop_service._settle_sale` 结算。AI 客人从"讨价还价"改为"点菜购买":客人报出想买的菜+总价,玩家核对后成交。

**Tech Stack:** FastAPI + SQLAlchemy 2 + ai_service(OpenAI 兼容转发)+ 现有 guest 素材(guests.json + animals 情绪图)。

---

## 需求梳理(用户原话转译)

### 流程
1. **请求生成 AI 客人**时,给 AI 的输入:
   - 所有菜的种类 + 相应价格
   - 默认提示词模板
   - 客人独立提示词
   - 客人名称、年龄
2. **AI 输出 JSON**:`{raw_text, items:[crop.id...], total_price}`
3. **回传前端**:哪位客人、客人名、AI 生成的 `raw_text`
4. **前端回复后保持同一上下文**(多轮对话)
5. **AI 客人返回**:`{raw_text, emotion(四选一,见客人素材配置), is_complete}`
6. **多轮对话,极限 4 轮**:
   - 4 轮后仍错误 → 客人 `emotion=失望`, `is_complete=true`, `is_right=false`
7. **成交判定**:
   - 若 `items` = 前端用户选的菜 且 价格 = price → 提示词加入"摊主给的是正确的,请…",让 LLM 自行抉择
   - 若 `is_complete=true, is_right=true` → 扣除相应蔬菜,金币增加 price
   - 若没有对应的菜(用户和 LLM 沟通说没菜了)→ `emotion=失望, is_complete=true, is_right=false`,不扣菜不加钱

### 关键字段
- **emotion 四选一**:`happy / calm / sad / confused`(对应 animals 素材情绪,见 assets.json)
- **is_complete**: 会话是否结束
- **is_right**: 是否成交正确(决定是否结算)

---

## 数据模型改动

### `AiGuestSession` 加字段(幂等迁移)
```python
mode: Mapped[str] = mapped_column(String(16), default="bargain")  # bargain=议价 / order=点菜
# 点菜模式专用:
order_items: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # AI 报的菜单 {crop_id: qty}
order_total: Mapped[int | None] = mapped_column(Integer, nullable=True)  # AI 报的总价
is_right: Mapped[bool | None] = mapped_column(Boolean, nullable=True)  # 是否成交正确
```
- `main.py` 幂等 ALTER 补齐(与现有列迁移同款)。

### `guests.json` 加字段
```json
{
  "key": "thrifty_granny",
  "name": "王奶奶",
  "age": 68,
  "personality": "...",
  "order_prompt": "你是一位节俭的老奶奶,想买点菜回家做饭,会精打细算。",
  "emotions": { "happy": "animals/happy/owl.png", "calm": "animals/calm/owl.png", "sad": "animals/sad/owl.png", "confused": "animals/confused/owl.png" }
}
```
- 每个客人配 4 张情绪图(复用 animals 素材,不同情绪不同动物或同动物不同情绪)。

---

## 新接口设计(`/v1/shop/order`,全部 🔐)

### 1. `POST /v1/shop/order/start` — 开始点菜会话
**请求体:** `{ }`(无参,或可选 `guest_key` 指定客人)
**流程:**
- 冷却/单活跃会话校验(复用议价逻辑,但查 `mode="order"` 的活跃会话)
- 随机/锁定客人(复用 `encounter_guest` 的锁定逻辑)
- 收集所有菜:从 `Crop` 表取 active 作物 + 当前季节价(`shop_service._crop_price`)
- 构造 AI 输入:菜种类+价格 + 默认提示词 + 客人独立提示词 + 客人名/年龄
- 调 AI → 解析 `{raw_text, items:[crop.id], total_price}`
- 存会话 + 首条消息
- **返回:** `{session_id, guest_key, guest_name, guest_age, avatar_url, raw_text, items, total_price}`

### 2. `POST /v1/shop/order/{session_id}/chat` — 多轮对话
**请求体:** `{ message: str }`(前端用户回复)
**流程:**
- 校验会话属于我 + 状态 bargaining
- 追加用户消息 → 调 AI(带完整上下文)→ 解析 `{raw_text, emotion, is_complete}`
- 若 `is_complete=true`:
  - 校验 `is_right`(服务端权威:比对 AI 报的 items/total_price 与玩家实际选择)
  - 成交 → 扣菜 + 加金币(`_settle_sale` 逐项)
  - 未成交 → 不结算
- 轮数 ≥ 4 且未完成 → 强制 `emotion=sad, is_complete=true, is_right=false`
- **返回:** `{raw_text, emotion, is_complete, is_right, settle?}`

### 3. `POST /v1/shop/order/{session_id}/confirm` — 玩家确认成交
**请求体:** `{ items: [{crop_id, quantity}], total_price: int }`
**流程:**
- 玩家提交实际选择的菜 + 总价
- 服务端校验:库存足够、价格 = AI 报的 total_price
- 若匹配 → 提示词注入"摊主给的是正确的" → 让 LLM 最终抉择
- 成交 → 扣菜 + 加金币
- **返回:** `{is_right, settle?}`

### 4. `POST /v1/shop/order/{session_id}/cancel` — 取消
复用议价 cancel 逻辑。

### 5. `GET /v1/shop/order/{session_id}` — 快照
复用议价 snapshot 逻辑(含 history)。

---

## 服务层改动(`guest_service.py` 或新 `order_service.py`)

**建议新建 `order_service.py`**(与议价解耦,避免 guest_service 膨胀),复用:
- `guest_service.load_guests` / `_guest_by_key` / `_avatar_url` / `encounter_guest` 的锁定逻辑
- `shop_service._crop_price` / `_settle_sale`
- `ai_service.chat`

**核心函数:**
```python
def start_order(db, player) -> dict          # 开始点菜会话
async def chat_order(db, player, session_id, message) -> dict  # 多轮对话
def confirm_order(db, player, session_id, items, total_price) -> dict  # 玩家确认
def cancel_order(db, player, session_id) -> dict
def get_order(db, player, session_id) -> dict
```

**AI 提示词构造(核心):**
```python
def _build_order_system_prompt(guest, crops_with_price, history) -> str:
    # 菜种类+价格表
    # 默认提示词模板
    # 客人独立提示词 + 名称 + 年龄
    # 输出 JSON 格式约束
```

---

## 测试计划

### 新增 `tests/test_order.py`
- `test_start_order_returns_guest_and_menu` — start 返回客人+菜单+AI raw_text
- `test_chat_order_keeps_context` — 多轮对话保持上下文
- `test_chat_order_4_turns_fail` — 4 轮后仍错误 → emotion=sad, is_complete=true, is_right=false
- `test_confirm_order_correct_settles` — 正确成交 → 扣菜+加金币
- `test_confirm_order_wrong_no_settle` — 错误 → 不结算
- `test_no_stock_no_settle` — 没菜 → emotion=sad, is_complete=true, is_right=false, 不扣不加
- `test_order_requires_login` — 未登录 401
- `test_order_guest_locked` — 会话结束前锁定同一位客人

### 复用现有测试
- 议价接口(`test_guest.py`)不受影响(两套并存)

---

## 文件改动清单

| 文件 | 改动 |
|---|---|
| `server/app/models/__init__.py` | AiGuestSession 加 mode/order_items/order_total/is_right 字段 |
| `server/app/main.py` | 幂等迁移补齐新列 |
| `server/app/services/order_service.py` | **新建**:点菜核心逻辑 |
| `server/app/api/order.py` | **新建**:/v1/shop/order 路由 |
| `server/app/api/router.py` | 挂载 order 路由 |
| `server/data/guests.json` | 加 age/order_prompt/emotions 字段 |
| `server/tests/test_order.py` | **新建**:点菜测试 |
| `server/scripts/verify_api_docs.py` | PREFIX 加 order.py |
| `API.md` | §3.2 索引 + §5.18 点菜详解 |
| `server/scripts/run_tests.py` | BOARDS 加 order 板块 |

---

## 验证步骤

1. `python -m scripts.run_tests order` — 点菜板块全绿
2. `python -m scripts.run_tests guest` — 议价板块不受影响
3. `python -m scripts.run_tests --all` — 全量
4. `python -m scripts.verify_api_docs check` — 文档三查
5. 真机冒烟:start → chat 多轮 → confirm 成交/失败

---

## 风险与开放问题

1. **AI 输出稳定性**:items 用 crop.id(UUID),LLM 可能输出错格式 → 服务端强校验 + 重试 + 兜底(复用议价 `_parse_reply`/`_validate_reply` 模式)。
2. **价格权威**:total_price 必须服务端按 `_crop_price` 重算校验,不能信 AI 报的价(防作弊)。
3. **is_right 判定**:由服务端比对(玩家 confirm 的 items/price vs AI 报的),不依赖 LLM 自报。
4. **两套并存**:议价接口保留,前端可选;新接口独立前缀,互不干扰。
5. **emotion 素材**:guests.json 每个客人配 4 情绪图,需确认 animals 素材有对应情绪文件。
