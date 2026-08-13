"""种子数据导入(幂等):term_config / crops / items / game_clock。

用法:uv run python -m scripts.seed
"""
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.models import Crop, GameClock, Item, TermConfig

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def _load(name: str):
    return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))


def crop_uuid(name: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"crop:{name}")


def item_uuid(code: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"item:{code}")


def seed_if_empty(db: Session) -> bool:
    """仅在 term_config 为空时导入;返回是否执行了导入。"""
    if db.query(TermConfig).count() > 0:
        return False

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

    db.commit()
    return True


def main() -> None:
    from app.core.db import SessionLocal

    with SessionLocal() as db:
        seeded = seed_if_empty(db)
    print("seed 完成:已导入数据" if seeded else "seed 跳过:数据已存在")


if __name__ == "__main__":
    main()
