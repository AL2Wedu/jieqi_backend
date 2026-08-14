"""种子数据导入(幂等):term_config / crops / items / game_clock。

用法:uv run python -m scripts.seed
"""
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.models import Achievement, Crop, GameClock, Item, Quest, TermConfig

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def _load(name: str):
    return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))


def crop_uuid(name: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"crop:{name}")


def item_uuid(code: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"item:{code}")


def quest_uuid(code: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"quest:{code}")


def achievement_uuid(code: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"achievement:{code}")


def crop_png_art(slug: str) -> dict:
    """作物美术路径:seed(独立种子图标)+ stages[3](苗期/生长期/成熟,与种子图无关)。"""
    return {
        "seed": f"/static/assets/crops/{slug}/seed.png",
        "stages": [f"/static/assets/crops/{slug}/{i}.png" for i in (1, 2, 3)],
    }


_ART: dict = {}


def sync_crops(db: Session) -> int:
    """每株植物 JSON → DB 幂等同步(新增 + 更新设定字段)。

    - 以文件为事实源:改 data/crops/<slug>.json → 重启/重跑 seed 即生效
    - 不覆盖 active 状态(管理后台停用的作物不会被文件重新激活)
    - 返回发生变更的作物数
    """
    from scripts.crop_loader import load_crops

    changed = 0
    for c in load_crops():
        slug = c.get("slug", "")
        fields = dict(
            category=c["category"],
            sow_window=c.get(
                "sow_window", {"type": "term", "start": 1, "end": 24, "grace": 0}
            ),
            grow_seconds=c["grow_seconds"],
            yield_base=c.get("yield_base", 1),
            base_price=c.get("base_price", 1),
            unlock_level=c.get("unlock_level", 1),
            unlock_exp=c.get("unlock_exp", 0),
            description=c.get("description"),
            art=c.get("art") or crop_png_art(slug),
            settings=c.get("settings") or {},
            sort_order=c.get("sort_order", 0),
        )
        row = db.query(Crop).filter(Crop.name == c["name"]).first()
        if row is None:
            db.add(Crop(id=crop_uuid(c["name"]), name=c["name"], **fields))
            changed += 1
        else:
            for k, v in fields.items():
                if getattr(row, k) != v:
                    setattr(row, k, v)
                    changed += 1
    db.commit()
    return changed


def seed_if_empty(db: Session) -> bool:
    """幂等导入;返回是否执行了导入(各域独立判断)。"""
    seeded = False

    # 作物设定始终同步(每株植物 JSON → DB upsert):改文件 → 重启即生效
    sync_crops(db)

    if db.query(TermConfig).count() == 0:
        _seed_base(db)
        seeded = True

    if db.query(Quest).count() == 0:
        for q in _load("quests.json"):
            db.add(
                Quest(
                    id=quest_uuid(q["code"]),
                    code=q["code"],
                    name=q["name"],
                    description=q.get("description"),
                    category=q.get("category", "daily"),
                    objective=q["objective"],
                    reward=q.get("reward"),
                    sort_order=q.get("sort_order", 0),
                )
            )
        seeded = True

    if db.query(Achievement).count() == 0:
        for a in _load("achievements.json"):
            db.add(
                Achievement(
                    id=achievement_uuid(a["code"]),
                    code=a["code"],
                    name=a["name"],
                    description=a.get("description"),
                    category=a.get("category", "成长"),
                    target=a.get("target"),
                    reward=a.get("reward"),
                    sort_order=a.get("sort_order", 0),
                )
            )
        seeded = True

    if seeded:
        db.commit()
    return seeded


def _seed_base(db: Session) -> None:
    """基础数据:节气 / 作物 / 道具 / 游戏时钟。"""
    for t in _load("term_config.json"):
        db.add(
            TermConfig(
                term_index=t["term_index"],
                name=t["name"],
                duration_seconds=t.get("duration_seconds", 300),
                sort_order=t["term_index"],
            )
        )

    for it in _load("items.json"):
        eff = dict(it["effect"])
        if eff.get("type") == "seed" and eff.get("crop_name"):
            eff["crop_id"] = str(crop_uuid(eff.pop("crop_name")))
        db.add(
            Item(
                id=item_uuid(it["code"]),
                code=it["code"],
                name=it["name"],
                category=it["category"],
                effect=eff,
                buy_price=it.get("buy_price"),
                sell_price=it.get("sell_price"),
                sort_order=it.get("sort_order", 0),
            )
        )

    if db.query(GameClock).count() == 0:
        db.add(GameClock(id=1, epoch=datetime.now(timezone.utc), time_scale=1.0))


def main() -> None:
    from app.core.db import SessionLocal

    with SessionLocal() as db:
        seeded = seed_if_empty(db)
    print("seed 完成:已导入数据" if seeded else "seed 跳过:数据已存在")


if __name__ == "__main__":
    main()
