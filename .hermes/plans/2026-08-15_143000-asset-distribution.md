# 通用资源分发系统(资源请求可扩展)实现计划

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** 把当前"仅图片"的统一资源接口(`/v1/art`)泛化为**任意类型资源**(图片/音频/JSON 配置/视频…)的统一分发系统,并新增"WS 推送资源地址 → 客户端按地址拉取强制更新"的通用机制,让增改资源零代码。

**Architecture:** 保留现有 art.py 的成熟机制(预渲染/内容哈希版本/manifest/HTTP 缓存),在其上做三层泛化:①资源接口从 `kind∈{crops,terms}` 泛化为 `type∈{images,audio,config,…}`;②manifest 按资源类型分组,每种类型带 url_template + 版本哈希;③新增通用 WS 事件 `asset_update`(带 url+version),客户端按 url 拉取强制更新,与现有语义化事件并存。

**Tech Stack:** FastAPI + SQLAlchemy 2 + SQLite(既有);资源注册表用 JSON 声明式(assets.json),增改资源只改文件+注册表,零代码。

---

## 0. 现状盘点(已实现 80%)

| 能力 | 现状 | 缺口 |
|---|---|---|
| 统一资源接口 | `GET /v1/art/{kind}/{key}/{name}.png?w=`(crops/terms) | **仅图片**,kind 硬编码 `_KINDS={"crops","terms"}` |
| 相对地址请求 | manifest 返回 `url_templates`(相对路径) | 只对图片 |
| 版本/缓存 | `/v1/art/version` 内容哈希 + `/v1/art/manifest` 清单 | 只覆盖 crops/terms |
| 预渲染 | 32/64/128/256 四档,请求零渲染 | 仅图片适用 |
| WS 资源更新 | 语义化事件(solar_term_change/resources_changed/pest_big/pest_small/weed_growth) | **无"资源地址驱动"的通用更新事件** |
| 静态挂载 | `/static`(StaticFiles) | 与 `/v1/art` 并存,未纳入统一清单 |

**关键文件**:`server/app/api/art.py`(统一接口)、`server/app/core/svg_art.py`(ART_ROOT/TERM_ART_ROOT/PRERENDER_SIZES)、`server/app/main.py:172-173`(static 挂载)、`server/app/ws/__init__.py`(ConnectionManager)、`server/app/services/admin_service.py`(资产编辑推 resources_changed)、`ASSETS.md`、`API.md` §9.2。

---

## 1. 用户方案评估

用户三点设想,逐条评估:

| 用户设想 | 评估 | 结论 |
|---|---|---|
| ① 所有资源(不止图片)放一个文件夹,方便增改 | 已实现(assets/),但**只支持图片**;需泛化支持任意类型 | ✅ 采纳,需泛化 |
| ② 客户端用相对地址请求 | 已实现(manifest url_templates),但只对图片 | ✅ 采纳,需泛化 |
| ③ WS update 指定资源地址,客户端按地址拉取强制更新 | **未实现**;现有 WS 是语义化事件(带业务数据),不是"资源地址驱动" | ⚠️ 采纳,但需设计 |

**比用户方案更优的三点改进**:

1. **资源注册表(assets.json)声明式**:不硬编码 kind,用 JSON 声明每种资源类型的目录/扩展名/url_template/是否预渲染。增改资源 = 放文件 + 改注册表,零代码。这比"放一个文件夹"更可扩展(文件夹只管文件,注册表管"怎么取")。

2. **通用 WS 事件 `asset_update` 与语义化事件并存**:用户想要的"WS 指定资源地址"是**纯资源变更**场景(美术/音频/配置更新);而现有语义化事件(solar_term_change/resources_changed)还带**业务数据**,客户端需要这些数据本身。两者不冲突,各司其职 —— 新增 `asset_update` 用于纯资源,保留现有事件用于带数据的业务推送。

3. **资源接口向后兼容**:`/v1/art` 保留为 `images` 类型的别名(旧客户端不断),新增 `/v1/assets/{type}/{key}/{name}` 通用接口。避免破坏性变更(API 铁律:只加不减)。

---

## 2. 目标设计

### 2.1 资源注册表 `server/data/assets.json`

```json
{
  "images": {
    "root": "static/assets",
    "ext": ["png", "svg", "jpg", "webp"],
    "prerender": [32, 64, 128, 256],
    "url_template": "/v1/assets/images/{key}/{name}.{ext}?w={w}",
    "names": { "crops": ["seed","1","2","3"], "terms": ["main"] }
  },
  "audio": {
    "root": "static/assets/audio",
    "ext": ["ogg", "mp3", "wav"],
    "prerender": [],
    "url_template": "/v1/assets/audio/{key}/{name}.{ext}"
  },
  "config": {
    "root": "static/assets/config",
    "ext": ["json"],
    "prerender": [],
    "url_template": "/v1/assets/config/{key}/{name}.{ext}"
  }
}
```

- 每种类型声明:根目录、允许扩展名、是否预渲染、URL 模板、命名空间(可选)
- 增改资源 = 放文件到对应 root + 注册表加条目(或复用现有目录),**零代码**

### 2.2 通用资源接口 `GET /v1/assets/{type}/{key}/{name}.{ext}`

- 按注册表校验 type/key/name/ext
- 图片类型走预渲染选档(复用现有 `_pick_size`/`ensure_prerendered`)
- 非图片类型直接 FileResponse(带 Cache-Control)
- 404 → `28001 ASSET_NOT_FOUND`(复用现有码)
- `/v1/art/{kind}/{key}/{name}.png` 保留为 `images` 别名(向后兼容)

### 2.3 泛化 manifest/version

- `GET /v1/assets/manifest`:按类型分组,每种类型返回资源清单 + url_template + 版本
- `GET /v1/assets/version`:全局版本 + 逐类型/逐资源哈希(复用现有 `_compute_versions` 逻辑,泛化到任意 root)
- 保留 `/v1/art/manifest`、`/v1/art/version` 为 images 别名

### 2.4 通用 WS 事件 `asset_update`

```json
{ "type": "asset_update",
  "payload": { "asset_type": "images", "key": "shuidao", "name": "2",
                "url": "/v1/assets/images/shuidao/2.png?w=128",
                "version": "a1b2c3d4e5f6" } }
```

- 客户端收到后:按 `url` 拉取 → 若 `version` 与本地缓存不同则强制更新该资源
- 触发场景:管理后台替换/新增资源文件后,向全服(或指定玩家)推送
- 与现有语义化事件并存(见 §1 改进 2)

---

## 3. 任务分解(TDD,每任务 2-5 分钟)

### Task 1: 资源注册表加载器

**Objective:** 从 `data/assets.json` 加载资源类型配置,提供查询接口。

**Files:**
- Create: `server/app/core/assets_registry.py`
- Test: `server/tests/test_assets.py`

**Step 1: 写失败测试**
```python
def test_registry_loads_types():
    reg = load_registry()
    assert "images" in reg and "audio" in reg and "config" in reg
    assert reg["images"]["prerender"] == [32, 64, 128, 256]
```

**Step 2: 运行确认失败** — `pytest tests/test_assets.py::test_registry_loads_types -v` → FAIL(模块不存在)

**Step 3: 实现**
```python
# assets_registry.py
import json
from pathlib import Path
_REG = Path(__file__).resolve().parent.parent.parent / "data" / "assets.json"
_CACHE = None
def load_registry() -> dict:
    global _CACHE
    if _CACHE is None:
        _CACHE = json.loads(_REG.read_text(encoding="utf-8"))
    return _CACHE
```

**Step 4: 运行确认通过** — PASS

**Step 5: 提交** — `git add server/data/assets.json server/app/core/assets_registry.py server/tests/test_assets.py && git commit -m "feat(assets): 资源注册表加载器"`

---

### Task 2: 通用资源接口 `GET /v1/assets/{type}/{key}/{name}.{ext}`

**Objective:** 按注册表分发任意类型资源;图片走预渲染,非图片直接返回。

**Files:**
- Create: `server/app/api/assets.py`
- Modify: `server/app/api/router.py`(挂载 assets router)
- Test: `server/tests/test_assets.py`

**Step 1: 写失败测试**
```python
def test_assets_image_serves(client):
    r = client.get("/v1/assets/images/shuidao/2.png?w=128")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"

def test_assets_unknown_type_404(client):
    r = client.get("/v1/assets/video/x/y.mp4")
    assert r.status_code == 404 and r.json()["code"] == 28001
```

**Step 2: 运行确认失败** — FAIL(路由不存在)

**Step 3: 实现** — 复用 `_serve_asset` 逻辑,按注册表校验;图片委托 svg_art 预渲染,非图片 FileResponse

**Step 4: 运行确认通过** — PASS

**Step 5: 提交**

---

### Task 3: `/v1/art` 保留为 images 别名(向后兼容)

**Objective:** 旧客户端不断;`/v1/art/{kind}/{key}/{name}.png` 委托到 assets 的 images 类型。

**Files:**
- Modify: `server/app/api/art.py`(asset 端点委托 assets_service)
- Test: `server/tests/test_assets.py`

**Step 1: 写失败测试** — 断言 `/v1/art/crops/shuidao/2.png?w=128` 仍 200
**Step 2: 确认失败**(若已通过则跳过,说明委托天然兼容)
**Step 3: 实现** — art.py 的 `asset` 端点改为调用 assets 的 images 分发
**Step 4: 确认通过**
**Step 5: 提交**

---

### Task 4: 泛化 manifest/version

**Objective:** `/v1/assets/manifest` + `/v1/assets/version` 覆盖所有资源类型;保留 `/v1/art/*` 别名。

**Files:**
- Modify: `server/app/api/assets.py`
- Modify: `server/app/core/assets_registry.py`(加版本计算,泛化 `_compute_versions`)
- Test: `server/tests/test_assets.py`

**Step 1: 写失败测试**
```python
def test_assets_manifest_lists_types(client):
    r = client.get("/v1/assets/manifest")
    d = r.json()["data"]
    assert "images" in d and "audio" in d and "config" in d
    assert "url_templates" in d
```

**Step 2: 确认失败**
**Step 3: 实现** — 泛化 `_compute_versions` 到任意 root;manifest 按类型分组
**Step 4: 确认通过**
**Step 5: 提交**

---

### Task 5: 通用 WS 事件 `asset_update`

**Objective:** 新增 `asset_update` 事件(带 url+version),客户端按地址拉取强制更新;与现有语义化事件并存。

**Files:**
- Modify: `server/app/ws/__init__.py`(加 `broadcast_asset_update` 或复用 push_sync)
- Modify: `server/app/services/admin_service.py`(资源更新后推送)
- Test: `server/tests/test_assets.py`

**Step 1: 写失败测试**
```python
def test_asset_update_event_pushed(client, monkeypatch):
    # 模拟管理端更新资源 → 玩家 WS 收到 asset_update
    ...
    assert msg["type"] == "asset_update"
    assert "url" in msg["payload"] and "version" in msg["payload"]
```

**Step 2: 确认失败**
**Step 3: 实现** — 复用 `manager.push_sync`(线程安全,已存在);新增管理端点或复用现有资源更新路径触发推送
**Step 4: 确认通过**
**Step 5: 提交**

---

### Task 6: 文档同步

**Objective:** ASSETS.md + API.md 补通用资源接口/事件;verify_api_docs 三查通过。

**Files:**
- Modify: `ASSETS.md`(通用资源指南)
- Modify: `API.md`(§3.3 美术素材 → 通用资源;§9.2 加 asset_update 事件)
- Modify: `server/scripts/verify_api_docs.py`(assets.py 加 PREFIX 映射)

**Step 1: 更新文档**
**Step 2: 运行** — `env -u PYTHONPATH uv run python -m scripts.verify_api_docs check` → 三查 PASS
**Step 3: 全量测试** — `env -u PYTHONPATH uv run python -m pytest -q` → 全绿
**Step 4: 提交**

---

## 4. 文件清单

- **Create:** `server/app/core/assets_registry.py`、`server/app/api/assets.py`、`server/data/assets.json`、`server/tests/test_assets.py`
- **Modify:** `server/app/api/router.py`(挂载)、`server/app/api/art.py`(委托别名)、`server/app/ws/__init__.py`(asset_update)、`server/app/services/admin_service.py`(推送)、`server/scripts/verify_api_docs.py`(PREFIX)、`ASSETS.md`、`API.md`
- **数据目录:** `server/app/static/assets/audio/`、`server/app/static/assets/config/`(新增示例资源)

## 5. 验证

1. 每任务 TDD:先写测试 → 跑红 → 实现 → 跑绿
2. 全量:`env -u PYTHONPATH uv run python -m pytest -q`(107 → 预计 115+)
3. `env -u PYTHONPATH uv run python -m scripts.verify_api_docs check`(端点/错误码/引用三查)
4. 真机冒烟:起服务 → `GET /v1/assets/images/shuidao/2.png?w=128` 200 → `GET /v1/assets/audio/...` 200 → 旧 `/v1/art/crops/shuidao/2.png` 仍 200 → WS 收到 asset_update

## 6. 风险与取舍

- **向后兼容**:`/v1/art` 保留为 images 别名,旧客户端零改动;新客户端用 `/v1/assets`
- **注册表 vs 硬编码**:注册表增加一层间接,但换来"增改资源零代码";注册表本身需维护(增类型时改 JSON)
- **asset_update 与语义化事件并存**:不替换现有事件(它们带业务数据);asset_update 只用于纯资源变更
- **开放问题**:① 资源更新推送是"全服广播"还是"指定玩家"?建议管理端可指定(默认全服);② 音频/配置是否本期就加示例资源,还是只搭好框架?建议搭好框架 + 1 个示例音频/配置验证链路
