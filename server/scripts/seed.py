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


_ART: dict = {}


def seed_if_empty(db: Session) -> bool:
    """幂等导入;返回是否执行了导入(各域独立判断)。"""
    seeded = False

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
    # 生成 6 种初始作物的美术资产(SVG),写入 static/assets/crops/<slug>/
    from app.core.svg_art import generate_all

    global _ART
    _ART = generate_all()

    for t in _load("term_config.json"):
        db.add(
            TermConfig(
                term_index=t["term_index"],
                name=t["name"],
                duration_seconds=t.get("duration_seconds", 300),
                sort_order=t["term_index"],
            )
        )

    for c in _load("crops.json"):
        db.add(
            Crop(
                id=crop_uuid(c["name"]),
                name=c["name"],
                category=c["category"],
                sow_window=c["sow_window"],
                grow_seconds=c["grow_seconds"],
                yield_base=c["yield_base"],
                base_price=c["base_price"],
                description=c.get("description"),
                art=_ART.get(c.get("slug"), {}),
                sort_order=c.get("sort_order", 0),
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
