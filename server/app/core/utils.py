from datetime import datetime, timezone


def ensure_aware(dt: datetime | None) -> datetime | None:
    """SQLite 读出的 DateTime 不带时区,统一补 UTC;已是 aware 的原样返回。"""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt
