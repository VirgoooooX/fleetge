"""UTC timestamp helpers for database and API boundaries."""

from datetime import datetime, timezone
from typing import overload


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@overload
def as_utc(value: datetime) -> datetime: ...


@overload
def as_utc(value: None) -> None: ...


def as_utc(value: datetime | None) -> datetime | None:
    """Normalize timestamps, treating SQLite's timezone-naive values as UTC."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
