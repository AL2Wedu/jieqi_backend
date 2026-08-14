# 图片素材获取(前端速查)

> 给 Godot / 前端用的最短版。每个作物 4 个素材,`seed` 与生长阶段图是**不同素材**。

## 1. 素材清单与调用名称

| 调用名称 `name` | 含义 | 用途 |
|---|---|---|
| `seed` | **种子图标**(独立生成,非阶段图) | 背包 / 商店 / 选择种子 |
| `1` | **苗期**(第一阶段) | 地块 `crop.stage == 1` 时 |
| `2` | **生长期**(第二阶段) | 地块 `crop.stage == 2` 时 |
| `3` | **成熟期**(第三阶段) | 地块 `crop.stage == 3` 时 |

## 2. 获取方式(一个接口)

```
GET /v1/art/crops/{slug}/{name}.png?w=<目标宽度像素>
```

- `name`:`seed` / `1` / `2` / `3`(见上表)
- `w`:目标宽度;服务端自动取**最小不小于 w** 的预渲染档(32 / 64 / 128 / 256),超出取最大档
- 响应:`image/png` + `Cache-Control: public, max-age=86400`(可放心缓存)
- 素材不存在:`404`(`28001`)

## 3. slug 从哪来(农场状态链路)

```json
// GET /v1/farm/state → 每个地块:
{ "crop": { "stage": 2,
            "art": { "seed": "/static/assets/crops/shuidao/seed.png",
                     "stages": ["/static/assets/crops/shuidao/1.png",
                                "/static/assets/crops/shuidao/2.png",
                                "/static/assets/crops/shuidao/3.png"] } } }
```

1. `slug` = `art.stages[0]` 路径的倒数第二段(如 `shuidao`)
2. 种子图标 → `GET /v1/art/crops/{slug}/seed.png?w=64`
3. 地块作物 → `GET /v1/art/crops/{slug}/{crop.stage}.png?w=128`(`crop.stage` 就是 1/2/3)

## 4. 素材更新判断

```
GET /v1/art/version
→ { "version": "a1b2c3d4e5f6", "crops": {"shuidao": "9f8e...", ...}, "sizes": [32,64,128,256] }
```

- 本地缓存素材时,登录后 / 节气切换时对比:`version` 变 → 全量刷新;仅某作物 `crops[slug]` 变 → 只刷新该作物

## 5. 示例

```
GET /v1/art/crops/shuidao/seed.png?w=64     # 水稻种子(背包)
GET /v1/art/crops/shuidao/1.png?w=128       # 水稻苗期(地块)
GET /v1/art/crops/yumi/3.png?w=256          # 玉米成熟(大图)
GET /v1/art/crops/zhima/seed.png?w=64       # 芝麻种子
```

## 6. 素材文件位置(服务器)

```
server/app/static/assets/crops/<slug>/
  ├── seed.png / 1.png / 2.png / 3.png      # 源素材
  └── <name>_32.png _64.png _128.png _256.png  # 预渲染档
```

> slug 列表:baicai dacong dadou gaoliang guzi hongshu huasheng luobo mianhua qiaomai shuidao xiaomai youcai yumi zhima

## 7. 24 节气图(节气切换/界面背景)

同一个预渲染管线,按节气序号取图(与 `GET /v1/calendar/current` 返回的 `term_index` 一致):

```
GET /v1/art/terms/{term_index}.png?w=<目标宽度像素>
```

- `term_index`:**1-24**(1=立春 … 24=大寒,与节气轮转顺序一致)
- `w`:同作物规则,取**最小不小于 w** 的预渲染档(32/64/128/256),超出取最大档
- 响应:`image/png` + `Cache-Control: public, max-age=86400`
- 越界(`0` / `>24`):`404`(`28001`)

```json
// 客户端用法:节气切换事件 payload.term_index → 直接取图
GET /v1/art/terms/7.png?w=256      // 立夏大图(节气界面)
GET /v1/art/terms/1.png?w=64       // 立春小图(图标)
```

节气图版本已并入素材版本接口(新增 `terms` 字段):

```
GET /v1/art/version
→ { "version": "…", "crops": {"shuidao": "…", ...},
    "terms": {"lichun": "…", "guyu": "…", ..., "dahan": "…"}, "sizes": [32,64,128,256] }
```

- `terms[slug]` 变 → 只刷新该节气图;`version` 变 → 全量刷新(节气图与作物图一起)
- slug ↔ 节气名映射见 `app/core/svg_art.py` 的 `TERM_SLUGS`(lichun/yushui/jingzhe/…/dahan)
