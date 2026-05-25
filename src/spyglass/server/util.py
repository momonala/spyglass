"""Shared server utilities."""

from datetime import datetime
from datetime import timedelta
from datetime import timezone


def utcnow() -> datetime:
    """Return the current UTC time as a naive datetime (SQLite-compatible)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def parse_timestamp(ts: str | None) -> datetime:
    """Parse an ISO-8601 string to a naive UTC datetime.

    Args:
        ts: ISO-8601 string with or without timezone offset, or None.

    Returns:
        Naive datetime in UTC. Returns utcnow() if ts is None.
    """
    if ts is None:
        return utcnow()
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def parse_time_range(from_arg: str | None, to_arg: str | None) -> tuple[datetime, datetime]:
    """Parse a dashboard query window; defaults to the last 24 hours."""
    to_ts = parse_timestamp(to_arg) if to_arg else utcnow()
    from_ts = parse_timestamp(from_arg) if from_arg else to_ts - timedelta(hours=24)
    return from_ts, to_ts
