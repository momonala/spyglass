"""Pure aggregation helpers for building dashboards on top of Spyglass data.

All functions are stateless and take plain dicts (as returned by the /metrics
and /logs HTTP endpoints). No SQLAlchemy, no Flask, no I/O.
"""

from __future__ import annotations

import math
import re
from datetime import datetime
from datetime import timedelta
from datetime import timezone

from spyglass.dashboard.schemas import LogHistogram
from spyglass.dashboard.schemas import PreparedLogEntry
from spyglass.dashboard.schemas import StateUptime
from spyglass.dashboard.schemas import TimingSummary

# ── Constants ─────────────────────────────────────────────────────────────────

DEFAULT_WINDOW_AMOUNT: int = 6
DEFAULT_ROLLUP: str = "2"  # minutes; "auto" is also accepted

_VALID_UNITS = ("hours", "days", "weeks", "months")
_VALID_ROLLUPS = ("auto", "1", "2", "5", "10", "15", "30", "60", "120", "360", "720", "1440")
_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")

# Matches the Spyglass log format: "<date> <time> <LEVEL> [<func>] <logger> <msg>"
_LOG_MSG_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d+ \w+ \[(\w+)\] \S+ (.+)$")


# ── TimeWindow ────────────────────────────────────────────────────────────────


class TimeWindow:
    """A fixed time range divided into equal-width buckets."""

    def __init__(self, start: datetime, end: datetime, bucket_minutes: int) -> None:
        self.start = start
        self.end = end
        self.bucket_minutes = bucket_minutes

    @classmethod
    def from_hours(cls, window_hours: int, now: datetime, rollup_minutes: int) -> "TimeWindow":
        end = now.replace(tzinfo=None) if now.tzinfo else now
        start = end - timedelta(hours=window_hours)
        return cls(start=start, end=end, bucket_minutes=rollup_minutes)

    @property
    def window_hours(self) -> int:
        return int((self.end - self.start).total_seconds() / 3600)

    @property
    def bucket_count(self) -> int:
        span = (self.end - self.start).total_seconds()
        return max(1, math.ceil(span / (self.bucket_minutes * 60)))

    def bucket_starts(self) -> list[datetime]:
        buckets = []
        cursor = self.start
        delta = timedelta(minutes=self.bucket_minutes)
        while cursor < self.end:
            buckets.append(cursor)
            cursor += delta
        return buckets

    def labels(self) -> list[str]:
        span_hours = (self.end - self.start).total_seconds() / 3600
        fmt = "%Y-%m-%dT%H:%MZ" if span_hours > 24 else "%H:%MZ"
        return [b.strftime(fmt) for b in self.bucket_starts()]

    def bucket_index(self, ts: datetime) -> int | None:
        ts_naive = ts.replace(tzinfo=None) if ts.tzinfo else ts
        if ts_naive < self.start or ts_naive >= self.end:
            return None
        elapsed = (ts_naive - self.start).total_seconds()
        return int(elapsed // (self.bucket_minutes * 60))


# ── Parameter parsing ─────────────────────────────────────────────────────────


def parse_window_amount(amount: int | str | None) -> int:
    if amount is None:
        return DEFAULT_WINDOW_AMOUNT
    return max(1, int(amount))


def parse_window_unit(unit: str | None) -> str:
    if unit in _VALID_UNITS:
        return unit
    return "hours"


def parse_rollup(rollup: str | None) -> str:
    if str(rollup) in _VALID_ROLLUPS:
        return str(rollup)
    return "10"


_MAX_HOURS = 8640  # 360 days


def window_hours_from(amount: int, unit: str) -> int:
    if unit == "hours":
        return max(1, amount)
    if unit == "days":
        return amount * 24
    if unit == "weeks":
        return amount * 24 * 7
    if unit == "months":
        return min(amount * 24 * 30, _MAX_HOURS)
    return max(1, amount)


_TARGET_BUCKETS = 24


def resolve_rollup_minutes(rollup: str, window_hours: int) -> int:
    if rollup == "auto":
        target_minutes = (window_hours * 60) / _TARGET_BUCKETS
        for candidate in (1, 2, 5, 10, 15, 30, 60, 120, 360, 720, 1440):
            if candidate >= target_minutes:
                return candidate
        return 1440
    return int(rollup)


# ── Metric time helpers ───────────────────────────────────────────────────────


def parse_metric_time(timestamp: str) -> datetime:
    dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def match_points(
    metrics: list[dict],
    suffix: str,
    metric_type: str | None = None,
    tags: dict | None = None,
) -> list[dict]:
    """Filter metric points by name suffix, optional type, and optional tags."""
    result = []
    for point in metrics:
        if not point["name"].endswith(suffix):
            continue
        if metric_type and point.get("metric_type") != metric_type:
            continue
        if tags:
            point_tags = point.get("tags") or {}
            if not all(point_tags.get(k) == v for k, v in tags.items()):
                continue
        result.append(point)
    return result


def _metric_matches(point: dict, suffix: str, tags: dict | None) -> bool:
    if not point["name"].endswith(suffix):
        return False
    if tags:
        point_tags = point.get("tags") or {}
        if not all(point_tags.get(k) == v for k, v in tags.items()):
            return False
    return True


# ── Scalar aggregation ────────────────────────────────────────────────────────


def counter_sum(metrics: list[dict], suffix: str, tags: dict | None = None) -> float:
    """Sum all counter values matching the suffix."""
    return sum(
        p["value"] for p in metrics if p.get("metric_type") == "counter" and _metric_matches(p, suffix, tags)
    )


def timing_summary(metrics: list[dict], suffix: str, tags: dict | None = None) -> TimingSummary:
    """Compute count/p50/p95/max over all timing points matching the suffix."""
    values = sorted(
        p["value"] for p in metrics if p.get("metric_type") == "timing" and _metric_matches(p, suffix, tags)
    )
    if not values:
        return TimingSummary(count=0, p50=None, p95=None, max=None)
    n = len(values)
    return TimingSummary(
        count=n,
        p50=values[min(int(n * 0.50), n - 1)],
        p95=values[min(int(n * 0.95), n - 1)],
        max=values[-1],
    )


def latest_gauge(metrics: list[dict], suffix: str) -> float | None:
    candidates = [
        (parse_metric_time(p["timestamp"]), p["value"])
        for p in metrics
        if p.get("metric_type") == "gauge" and p["name"].endswith(suffix)
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda x: x[0])[1]


# ── Series builders ───────────────────────────────────────────────────────────


def counter_series(
    metrics: list[dict],
    suffix: str,
    window: TimeWindow,
    tags: dict | None = None,
) -> list[float]:
    buckets: list[float] = [0.0] * window.bucket_count
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
    bucket_values: list[list[float]] = [[] for _ in range(window.bucket_count)]
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
            sv = sorted(values)
            result.append(sv[min(int(len(sv) * 0.5), len(sv) - 1)])
    return result


def ratio_series(
    numerators: list[float],
    totals: list[float],
) -> list[float | None]:
    return [(n / t * 100) if t > 0 else None for n, t in zip(numerators, totals)]


# ── Uptime computation ────────────────────────────────────────────────────────


def compute_state_uptime(
    events: list[tuple[datetime, str]],
    window_start: datetime,
    window_end: datetime,
    states: list[str],
) -> StateUptime:
    """Compute time spent in each state over a window from a sequence of events.

    Before the first event the system is assumed to be in "unknown" state.
    """
    # Normalize to naive UTC so arithmetic works regardless of caller's tz-awareness
    window_start = window_start.replace(tzinfo=None) if window_start.tzinfo else window_start
    window_end = window_end.replace(tzinfo=None) if window_end.tzinfo else window_end

    total_seconds = (window_end - window_start).total_seconds()
    seconds: dict[str, float] = {s: 0.0 for s in states}

    if not events or total_seconds <= 0:
        if total_seconds > 0 and "unknown" in seconds:
            seconds["unknown"] = total_seconds
        pcts = {
            s: round(secs / total_seconds * 100, 1) if total_seconds > 0 else 0.0
            for s, secs in seconds.items()
        }
        return StateUptime(current="unknown", event_count=0, seconds=seconds, pcts=pcts)

    sorted_events = sorted(events, key=lambda e: e[0])
    current_state = "unknown"
    cursor = window_start

    for ts_raw, state in sorted_events:
        ts = ts_raw.replace(tzinfo=None) if ts_raw.tzinfo else ts_raw
        segment_end = min(max(ts, window_start), window_end)
        if segment_end > cursor and current_state in seconds:
            seconds[current_state] += (segment_end - cursor).total_seconds()
        cursor = max(cursor, segment_end)
        current_state = state

    if cursor < window_end and current_state in seconds:
        seconds[current_state] += (window_end - cursor).total_seconds()

    pcts = {s: round(secs / total_seconds * 100, 1) for s, secs in seconds.items()}
    return StateUptime(
        current=current_state,
        event_count=len(events),
        seconds=seconds,
        pcts=pcts,
    )


# ── Log helpers ───────────────────────────────────────────────────────────────


def prepare_logs(logs: list[dict]) -> list[PreparedLogEntry]:
    """Convert raw log dicts to typed PreparedLogEntry objects, newest first."""
    entries = []
    for log in logs:
        raw_message = log.get("message", "")
        match = _LOG_MSG_RE.match(raw_message)
        if match:
            function = match.group(1)
            message = match.group(2)
        else:
            function = log.get("function")
            message = raw_message
        entries.append(
            PreparedLogEntry(
                timestamp=log.get("timestamp", ""),
                level=(log.get("level") or "INFO").upper(),
                logger_name=log.get("logger_name", ""),
                message=message,
                function=function,
                extra=log.get("extra"),
            )
        )
    entries.sort(key=lambda e: e.timestamp, reverse=True)
    return entries


def build_log_histogram(
    logs: list[PreparedLogEntry],
    window: TimeWindow,
) -> LogHistogram:
    n = window.bucket_count
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

    return LogHistogram(labels=window.labels(), by_level=counts, total=total)
