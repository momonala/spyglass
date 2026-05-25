"""Pure aggregation helpers for building dashboards on top of Spyglass data.

All functions here are stateless and take plain dicts (as returned by the
/metrics and /logs HTTP endpoints). No SQLAlchemy, no Flask, no I/O.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterator

from spyglass.dashboard.schemas import LogHistogram, PreparedLogEntry

# ── Constants ─────────────────────────────────────────────────────────────────

DEFAULT_WINDOW_AMOUNT: int = 6
DEFAULT_ROLLUP: str = "2"  # minutes; "auto" is also accepted

_VALID_UNITS = ("hours", "days", "weeks", "months")
_VALID_ROLLUPS = ("auto", "1", "2", "5", "10", "15", "30", "60", "120", "360", "720", "1440")
_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


# ── Window helpers ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TimeWindow:
    """A fixed time range divided into equal-width buckets."""

    start: datetime
    end: datetime
    bucket_minutes: int

    @classmethod
    def from_hours(cls, window_hours: int, now: datetime, rollup_minutes: int) -> "TimeWindow":
        end = now.replace(tzinfo=None) if now.tzinfo else now
        start = end - timedelta(hours=window_hours)
        return cls(start=start, end=end, bucket_minutes=rollup_minutes)

    def bucket_starts(self) -> list[datetime]:
        """Return the start datetime of every bucket in order."""
        buckets = []
        cursor = self.start
        delta = timedelta(minutes=self.bucket_minutes)
        while cursor < self.end:
            buckets.append(cursor)
            cursor += delta
        return buckets

    def labels(self) -> list[str]:
        """ISO-8601 label for each bucket start (UTC, no timezone suffix)."""
        return [b.isoformat() + "Z" for b in self.bucket_starts()]

    def bucket_index(self, ts: datetime) -> int | None:
        """Return which bucket a timestamp falls into, or None if out of range."""
        if ts < self.start or ts >= self.end:
            return None
        elapsed = (ts - self.start).total_seconds()
        return int(elapsed // (self.bucket_minutes * 60))

    def bucket_count(self) -> int:
        span = (self.end - self.start).total_seconds()
        return max(1, math.ceil(span / (self.bucket_minutes * 60)))


# ── Parameter parsing ─────────────────────────────────────────────────────────


def parse_window_amount(amount: int | str) -> int:
    value = int(amount)
    if value < 1:
        raise ValueError(f"window amount must be >= 1, got {value}")
    return value


def parse_window_unit(unit: str) -> str:
    if unit not in _VALID_UNITS:
        raise ValueError(f"window unit must be one of {_VALID_UNITS}, got {unit!r}")
    return unit


def parse_rollup(rollup: str) -> str:
    if str(rollup) not in _VALID_ROLLUPS:
        raise ValueError(f"rollup must be one of {_VALID_ROLLUPS}, got {rollup!r}")
    return str(rollup)


def window_hours_from(amount: int, unit: str) -> int:
    """Convert (amount, unit) to a total number of hours."""
    if unit == "hours":
        return amount
    if unit == "days":
        return amount * 24
    if unit == "weeks":
        return amount * 24 * 7
    if unit == "months":
        return amount * 24 * 30
    raise ValueError(f"unknown unit: {unit!r}")


def resolve_rollup_minutes(rollup: str, window_hours: int) -> int:
    """Resolve 'auto' to a sensible bucket size, or parse the explicit value."""
    if rollup == "auto":
        # Target ~60 buckets; pick a nice round interval.
        target_minutes = (window_hours * 60) / 60
        for candidate in (1, 2, 5, 10, 15, 30, 60, 120, 360, 720, 1440):
            if candidate >= target_minutes:
                return candidate
        return 1440
    return int(rollup)


# ── Metric time helpers ───────────────────────────────────────────────────────


def parse_metric_time(timestamp: str) -> datetime:
    """Parse an ISO-8601 metric timestamp to a naive UTC datetime."""
    dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def _metric_matches(point: dict, suffix: str, tags: dict | None) -> bool:
    if not point["name"].endswith(suffix):
        return False
    if tags:
        point_tags = point.get("tags") or {}
        if not all(point_tags.get(k) == v for k, v in tags.items()):
            return False
    return True


# ── Series builders ───────────────────────────────────────────────────────────


def counter_series(
    metrics: list[dict],
    suffix: str,
    window: TimeWindow,
    tags: dict | None = None,
) -> list[float]:
    """Sum counter values per bucket. Returns zeros for empty buckets."""
    buckets: list[float] = [0.0] * window.bucket_count()
    for point in metrics:
        if point.get("metric_type") != "counter":
            continue
        if not _metric_matches(point, suffix, tags):
            continue
        idx = window.bucket_index(parse_metric_time(point["timestamp"]))
        if idx is not None and idx < len(buckets):
            buckets[idx] += point["value"]
    return buckets


def timing_p50_series(
    metrics: list[dict],
    suffix: str,
    window: TimeWindow,
    tags: dict | None = None,
) -> list[float | None]:
    """Compute p50 of timing values per bucket. None for empty buckets."""
    bucket_values: list[list[float]] = [[] for _ in range(window.bucket_count())]
    for point in metrics:
        if point.get("metric_type") != "timing":
            continue
        if not _metric_matches(point, suffix, tags):
            continue
        idx = window.bucket_index(parse_metric_time(point["timestamp"]))
        if idx is not None and idx < len(bucket_values):
            bucket_values[idx].append(point["value"])

    result: list[float | None] = []
    for values in bucket_values:
        if not values:
            result.append(None)
        else:
            sorted_v = sorted(values)
            p50_idx = min(int(len(sorted_v) * 0.5), len(sorted_v) - 1)
            result.append(sorted_v[p50_idx])
    return result


def ratio_series(
    numerators: list[float],
    totals: list[float],
) -> list[float | None]:
    """Element-wise ratio as percentage. None where total is zero."""
    return [
        (n / t * 100) if t > 0 else None
        for n, t in zip(numerators, totals)
    ]


def latest_gauge(metrics: list[dict], suffix: str) -> float | None:
    """Return the most recent gauge value matching the suffix, or None."""
    candidates = [
        (parse_metric_time(p["timestamp"]), p["value"])
        for p in metrics
        if p.get("metric_type") == "gauge" and p["name"].endswith(suffix)
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda x: x[0])[1]


# ── Uptime computation ────────────────────────────────────────────────────────


@dataclass
class UptimeResult:
    seconds: dict[str, float] = field(default_factory=dict)
    pcts: dict[str, float] = field(default_factory=dict)
    event_count: int = 0


def compute_state_uptime(
    events: list[tuple[datetime, str]],
    window_start: datetime,
    window_end: datetime,
    states: list[str],
) -> UptimeResult:
    """Compute time spent in each state over a window from a sequence of events.

    Events are (timestamp, state) pairs. Between events, the system is assumed
    to remain in the state of the last event. Before the first event the state
    is "unknown".
    """
    result = UptimeResult(
        seconds={s: 0.0 for s in states},
        pcts={s: 0.0 for s in states},
        event_count=len(events),
    )
    total_seconds = (window_end - window_start).total_seconds()
    if total_seconds <= 0 or not events:
        return result

    sorted_events = sorted(events, key=lambda e: e[0])
    current_state = "unknown"
    cursor = window_start

    for ts, state in sorted_events:
        # Clamp to window
        segment_end = min(ts, window_end)
        segment_end = max(segment_end, window_start)
        if segment_end > cursor and current_state in result.seconds:
            result.seconds[current_state] += (segment_end - cursor).total_seconds()
        cursor = max(cursor, segment_end)
        current_state = state

    # Remaining time after last event
    if cursor < window_end and current_state in result.seconds:
        result.seconds[current_state] += (window_end - cursor).total_seconds()

    result.pcts = {
        s: round(secs / total_seconds * 100, 1)
        for s, secs in result.seconds.items()
    }
    return result


# ── Log helpers ───────────────────────────────────────────────────────────────


def prepare_logs(logs: list[dict]) -> list[PreparedLogEntry]:
    """Convert raw log dicts to typed PreparedLogEntry objects, newest first."""
    entries = []
    for log in logs:
        entries.append(
            PreparedLogEntry(
                timestamp=log.get("timestamp", ""),
                level=(log.get("level") or "INFO").upper(),
                logger_name=log.get("logger_name", ""),
                message=log.get("message", ""),
                function=log.get("function"),
                extra=log.get("extra"),
            )
        )
    entries.sort(key=lambda e: e.timestamp, reverse=True)
    return entries


def build_log_histogram(
    logs: list[PreparedLogEntry],
    window: TimeWindow,
) -> LogHistogram:
    """Bucket log counts by level across a TimeWindow."""
    n = window.bucket_count()
    counts: dict[str, list[int]] = {level: [0] * n for level in _LOG_LEVELS}
    total = 0

    for log in logs:
        try:
            ts = parse_metric_time(log.timestamp)
        except (ValueError, AttributeError):
            continue
        idx = window.bucket_index(ts)
        if idx is None or idx >= n:
            continue
        level = log.level if log.level in counts else "INFO"
        counts[level][idx] += 1
        total += 1

    return LogHistogram(labels=window.labels(), counts=counts, total=total)
