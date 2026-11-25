"""Datetime normalization and validation helpers."""

from datetime import UTC, datetime


def to_utc_naive(dt: datetime | None) -> datetime | None:
    """Normalize datetime to UTC naive datetime."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(UTC).replace(tzinfo=None)
    return dt
