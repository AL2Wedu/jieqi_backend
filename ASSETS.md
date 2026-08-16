# 游戏资源获取指南(ASSETS)

> 给 Godot / 前端用的**唯一**素材速查:全部图片素材(作物图 + 24 节气图)走**同一个资源接口**,一份清单(`/v1/art/manifest`)拉全量,版本接口判断缓存刷新。

> **通用资源接口(任意类型)**:除图片外,音频/配置等任意类型资源统一走 `/v1/assets`(见 §9)。`/v1/art` 保留为 `images` 别名(向后兼容)。

## 1. 统一资源接口(一个端点取全部素材)

```
GET /v1/art/{kind}/{key}/{name}.png?w=<目标宽度像素>
```

| 参数 | 取值 | 说明 |
|---|---|---|
| `kind` | `crops` / `terms` | 资源类别:作物素材 / 24 节气图 |
| `key` | crops 用 slug;terms 用节气序号 1-24 | 见下方完整清单 |
| `name` | crops:`seed`/`1`/`2`/`3`;terms:`main` | 素材名 |
| `w` | 8-1024,默认 128 | 目标宽度;服务端自动取**最小不小于 w** 的预渲染档(32/64/128/256),超出取最大档 |

- 响应:`image/png` + `Cache-Control: public, max-age=86400`(客户端/Nginx 均可放心缓存)
- 素材不存在 → `404`(`28001 ART_NOT_FOUND`)
- **兼容**:旧路径 `GET /v1/art/terms/{term_index}.png` 仍可用(等价 `terms/{index}/main.png`)

示例:

```
GET /v1/art/crops/shuidao/2.png?w=128     # 水稻 生长期图,128px
GET /v1/art/crops/shuidao/seed.png?w=64   # 水稻 种子图标,64px
GET /v1/art/terms/5/main.png?w=256        # 清明 节气图,256px
```

## 2. 素材清单与调用名称

| 调用名称 `name` | 含义 | 用途 |
|---|---|---|
| `seed` | **种子图标**(独立生成,非阶段图) | 背包 / 商店 / 选择种子 |
| `1` | **苗期**(第一阶段) | 地块 `crop.stage == 1` 时 |
| `2` | **生长期**(第二阶段) | 地块 `crop.stage == 2` 时 |
| `3` | **成熟期**(第三阶段) | 地块 `crop.stage == 3` 时 |
| `main` | 节气主图 | 节气界面(当前节气/轮转展示) |

> ⚠️ `seed` 与阶段图是**不同素材**,服务端绝不互相回退;缺 `seed` 源返回 404(宁可 404 不混用)。

## 3. 完整资源清单(15 作物 + 24 节气)

### 3.1 作物素材(15 种 × 4 张)

| 作物 | slug | 素材名 | 取图 URL |
|---|---|---|---|
| 水稻 | `shuidao` | `seed`·`1`·`2`·`3` | `/v1/art/crops/shuidao/{name}.png?w=128` |
| 小麦 | `xiaomai` | `seed`·`1`·`2`·`3` | `/v1/art/crops/xiaomai/{name}.png?w=128` |
| 谷子 | `guzi` | `seed`·`1`·`2`·`3` | `/v1/art/crops/guzi/{name}.png?w=128` |
| 高粱 | `gaoliang` | `seed`·`1`·`2`·`3` | `/v1/art/crops/gaoliang/{name}.png?w=128` |
| 荞麦 | `qiaomai` | `seed`·`1`·`2`·`3` | `/v1/art/crops/qiaomai/{name}.png?w=128` |
| 玉米 | `yumi` | `seed`·`1`·`2`·`3` | `/v1/art/crops/yumi/{name}.png?w=128` |
| 大豆 | `dadou` | `seed`·`1`·`2`·`3` | `/v1/art/crops/dadou/{name}.png?w=128` |
| 花生 | `huasheng` | `seed`·`1`·`2`·`3` | `/v1/art/crops/huasheng/{name}.png?w=128` |
| 油菜 | `youcai` | `seed`·`1`·`2`·`3` | `/v1/art/crops/youcai/{name}.png?w=128` |
| 芝麻 | `zhima` | `seed`·`1`·`2`·`3` | `/v1/art/crops/zhima/{name}.png?w=128` |
| 白菜 | `baicai` | `seed`·`1`·`2`·`3` | `/v1/art/crops/baicai/{name}.png?w=128` |
| 大葱 | `dacong` | `seed`·`1`·`2`·`3` | `/v1/art/crops/dacong/{name}.png?w=128` |
| 萝卜 | `luobo` | `seed`·`1`·`2`·`3` | `/v1/art/crops/luobo/{name}.png?w=128` |
| 红薯 | `hongshu` | `seed`·`1`·`2`·`3` | `/v1/art/crops/hongshu/{name}.png?w=128` |
| 棉花 | `mianhua` | `seed`·`1`·`2`·`3` | `/v1/art/crops/mianhua/{name}.png?w=128` |

### 3.2 节气图(24 张)

| 节气 | 序号 | 素材名 | 取图 URL |
|---|---|---|---|
| 立春 | `1` | `main` | `/v1/art/terms/1/main.png?w=128` |
| 雨水 | `2` | `main` | `/v1/art/terms/2/main.png?w=128` |
| 惊蛰 | `3` | `main` | `/v1/art/terms/3/main.png?w=128` |
| 春分 | `4` | `main` | `/v1/art/terms/4/main.png?w=128` |
| 清明 | `5` | `main` | `/v1/art/terms/5/main.png?w=128` |
| 谷雨 | `6` | `main` | `/v1/art/terms/6/main.png?w=128` |
| 立夏 | `7` | `main` | `/v1/art/terms/7/main.png?w=128` |
| 小满 | `8` | `main` | `/v1/art/terms/8/main.png?w=128` |
| 芒种 | `9` | `main` | `/v1/art/terms/9/main.png?w=128` |
| 夏至 | `10` | `main` | `/v1/art/terms/10/main.png?w=128` |
| 小暑 | `11` | `main` | `/v1/art/terms/11/main.png?w=128` |
| 大暑 | `12` | `main` | `/v1/art/terms/12/main.png?w=128` |
| 立秋 | `13` | `main` | `/v1/art/terms/13/main.png?w=128` |
| 处暑 | `14` | `main` | `/v1/art/terms/14/main.png?w=128` |
| 白露 | `15` | `main` | `/v1/art/terms/15/main.png?w=128` |
| 秋分 | `16` | `main` | `/v1/art/terms/16/main.png?w=128` |
| 寒露 | `17` | `main` | `/v1/art/terms/17/main.png?w=128` |
| 霜降 | `18` | `main` | `/v1/art/terms/18/main.png?w=128` |
| 立冬 | `19` | `main` | `/v1/art/terms/19/main.png?w=128` |
| 小雪 | `20` | `main` | `/v1/art/terms/20/main.png?w=128` |
| 大雪 | `21` | `main` | `/v1/art/terms/21/main.png?w=128` |
| 冬至 | `22` | `main` | `/v1/art/terms/22/main.png?w=128` |
| 小寒 | `23` | `main` | `/v1/art/terms/23/main.png?w=128` |
| 大寒 | `24` | `main` | `/v1/art/terms/24/main.png?w=128` |

## 4. 一键拉全量:manifest 清单

```
GET /v1/art/manifest
```

返回全部资源的 slug / 中文名 / 素材名 + 当前版本 + URL 模板,客户端启动时拉一次即可知道所有资源怎么取:

```json
{
  "code": 0, "message": "ok",
  "data": {
    "version": "a1b2c3d4e5f6",
    "sizes": [32, 64, 128, 256],
    "crops": [ { "slug": "shuidao", "name": "水稻", "assets": ["1","2","3","seed"] }, ... 15 个 ],
    "terms": [ { "index": 1, "slug": "lichun", "name": "立春" }, ... 24 个 ],
    "url_templates": {
      "crop": "/v1/art/crops/{slug}/{name}.png?w={w}",
      "term": "/v1/art/terms/{index}/main.png?w={w}"
    },
    "updated_at": "..."
  }
}
```

## 5. 版本与缓存刷新

```
GET /v1/art/version
```

- `version`:全局内容哈希(12 位 md5);**变了 = 全量素材有更新,清空本地缓存**
- `crops[slug]` / `terms[slug]`:逐资源哈希;**只有某个变了 = 只刷新那一个**
- 客户端建议:启动时 + 每次进主界面时轮询;素材响应本身带 `Cache-Control: public, max-age=86400`(HTTP 缓存层兜底)

## 6. slug 从哪来(农场状态链路)

```json
// GET /v1/farm/state → 每个地块:
{ "crop": { "stage": 2,
            "art": { "seed": "/static/assets/crops/shuidao/seed.png",
                     "stages": ["/static/assets/crops/shuidao/1.png",
                                "/static/assets/crops/shuidao/2.png",
                                "/static/assets/crops/shuidao/3.png"] } } }
```

取图时从 `art` 路径里截出 slug(如 `shuidao`),再按当前 `stage` 拼统一接口:

```
GET /v1/art/crops/<slug>/<stage>.png?w=128
```

种子/商店场景直接用种子道具 `code`(如 `seed_shuidao` → 前缀 `seed_` 去掉 = slug)。

## 7. Godot 快速示例

```gdscript
# 取水稻生长期图(128px)
var tex = await fetch_texture("/v1/art/crops/shuidao/2.png?w=128")

# 启动时拉 manifest + version,按版本决定是否清缓存
var manifest = await fetch_json("/v1/art/manifest")
var ver = await fetch_json("/v1/art/version")
if ver.version != cached_version:
    clear_asset_cache()

# 节气界面:当前节气序号从 /v1/calendar/current 的 term_index 拿
var term_url = "/v1/art/terms/%d/main.png?w=256" % cal.term_index
```

## 8. 素材文件组织(后端目录)

```
server/app/static/assets/
├── crops/<slug>/          # 15 个作物目录:seed/1/2/3 的 PNG(真实素材)+ {name}_{32,64,128,256}.png(预渲染档)
└── terms/<slug>/          # 24 个节气目录(lichun…dahan):main.png + main_{32,64,128,256}.png
```

- 素材源优先级:同名 PNG(真实美术)→ 同名 SVG(程序生成兜底,仅管理端新建作物)
- 预渲染:启动/创建时按 32/64/128/256 四档生成,请求零渲染开销
- 版本接口基于文件内容哈希 + mtime 缓存,素材文件增删改自动触发版本变化,无需重启

## 9. 通用资源接口(任意类型:图片/音频/配置)

> 除图片外,音频/配置等任意类型资源统一走 `/v1/assets`。`/v1/art` 保留为 `images` 别名(向后兼容)。

### 9.1 资源类型注册表 `server/data/assets.json`

声明式定义每种资源类型(目录/扩展名/预渲染/URL 模板/命名空间)。**增改资源 = 放文件到对应 root + 改注册表,零代码。**

```json
{
  "images": { "root": "app/static/assets", "ext": ["png","svg","jpg","webp"],
              "prerender": [32,64,128,256],
              "url_template": "/v1/assets/images/{key}/{name}.{ext}?w={w}",
              "namespaces": { "crops": {"names":["seed","1","2","3"]}, "terms": {"names":["main"]} } },
  "audio":  { "root": "app/static/assets/audio", "ext": ["ogg","mp3","wav"],
              "prerender": [], "url_template": "/v1/assets/audio/{key}/{name}.{ext}" },
  "config": { "root": "app/static/assets/config", "ext": ["json"],
              "prerender": [], "url_template": "/v1/assets/config/{key}/{name}.{ext}" }
}
```

### 9.2 通用资源接口

```
GET /v1/assets/{type}/{key}/{name}.{ext}[?w=<目标像素>]
```

| 参数 | 取值 | 说明 |
|---|---|---|
| `type` | `images`/`audio`/`config`… | 资源类型(注册表声明) |
| `key` | 资源子目录,可多级 | 如 `crops/shuidao`、`bgm`、`terms` |
| `name` | 素材名 | 如 `2`、`main`、`welcome` |
| `ext` | 扩展名 | 须在注册表允许列表内 |
| `w` | 8-1024,默认 128 | 仅图片类型;服务端取最小不小于 w 的预渲染档 |

- 图片类型走预渲染选档(与 `/v1/art` 一致);非图片直接返回
- 响应带 `Cache-Control: public, max-age=86400`
- 不存在 → `404`(`28001 ASSET_NOT_FOUND`)

示例:
```
GET /v1/assets/images/crops/shuidao/2.png?w=128   # 水稻生长期图(等价 /v1/art/crops/shuidao/2.png)
GET /v1/assets/audio/bgm/main.ogg                 # 背景音乐
GET /v1/assets/config/terms/welcome.json          # 配置 JSON
```

### 9.3 清单与版本

```
GET /v1/assets/manifest   # 按类型分组:ext/prerender/url_template/namespaces + 版本
GET /v1/assets/version    # 全局版本 + 逐类型/逐资源哈希
```

### 9.4 资源更新推送(WS asset_update)

管理端替换/新增资源文件后,调用:

```
POST /v1/assets/notify?asset_type=audio&key=bgm&name=main   # 👑 需 admin token
```

向全服广播 `asset_update` 事件:

```json
{ "type": "asset_update",
  "payload": { "asset_type": "audio", "key": "bgm", "name": "main",
                "url": "/v1/assets/audio/bgm/main.ogg", "version": "a1b2c3d4e5f6" } }
```

客户端收到后按 `url` 拉取;若 `version` 与本地缓存不同则**强制更新该资源**。

### 9.5 动物素材(商店 NPC)

`animals` 注册在 `images` 命名空间下(英文情绪/动物名),**走预渲染选档**(32/64/128/256,缺档首次请求自动补渲染)。

```
GET /v1/assets/images/animals/{情绪}/{动物名}.png?w=<目标像素>
```

| 参数 | 说明 |
|---|---|
| `情绪` | `happy` / `calm` / `sad` / `confused` |
| `动物名` | bear/cat/cat2/chicken/crow/deer/dog/dog2/fox/frog/hedgehog/horse/mouse/owl/ox/panda/penguin/pig/rabbit/raccoon/sheep/sheep2/squirrel/wolf |
| `w` | 8-1024,默认 128;取最小不小于 w 的预渲染档 |

示例(Godot):

```gdscript
var tex = await Backend.fetch_texture("%s/v1/assets/images/animals/happy/%s.png?w=128" % [Backend.base_url, "crow"])
```

### 9.6 害虫素材(大虫害音游)

`pests` 是注册表中新声明的资源类型:按用途分目录,**原图直发、无预渲染**。

```
GET /v1/assets/pests/{key}/{害虫名}.png
```

| key | 说明 |
|---|---|
| `main` | 6 种害虫:蚜虫/蝗虫/螟虫/菜青虫/棉铃虫/稻飞虱(音游下落害虫、小虫害图标) |
| `banner` | 大虫害开场横幅配图(音游开场横幅) |

示例(Godot):

```gdscript
# 音游下落害虫(按害虫名取图)
var tex = await Backend.fetch_texture("%s/v1/assets/pests/main/%s.png" % [Backend.base_url, "蚜虫".uri_encode()])
# 大虫害开场横幅
var banner = await Backend.fetch_texture("%s/v1/assets/pests/banner/%s.png" % [Backend.base_url, "大虫害开场横幅配图".uri_encode()])
```

