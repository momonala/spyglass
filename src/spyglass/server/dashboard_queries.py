"""Dashboard query helpers: metric aggregation and layout persistence."""

import json
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from pathlib import Path
from typing import Any

from sqlalchemy import Float
from sqlalchemy import Integer
from sqlalchemy import cast
from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from spyglass.db.metric_names import get_name_id
from spyglass.db.models import LogEntry
from spyglass.db.models import MetricName
from spyglass.db.models import MetricPoint
from spyglass.db.models import MetricType
from spyglass.db.store import ProjectStore

_ERROR_LEVELS = ("ERROR", "CRITICAL")
_STALE_AFTER = timedelta(hours=24)
ACTIVITY_HOURS = 48

LAYOUT_VERSION = 1
ALLOWED_WIDGET_TYPES = frozenset({"series", "summary", "histogram"})
DEFAULT_SERIES_BUCKETS = 60
DEFAULT_HISTOGRAM_BINS = 20
_NICE_INTERVALS_SECONDS = (60, 300, 600, 900, 1800, 3600, 7200, 21600, 43200, 86400)


def auto_interval_seconds(
    from_ts: datetime, to_ts: datetime, max_buckets: int = DEFAULT_SERIES_BUCKETS
) -> int:
    """Pick a bucket width that keeps the series near max_buckets points."""
    span = max((to_ts - from_ts).total_seconds(), 1)
    target = span / max_buckets
    for interval in _NICE_INTERVALS_SECONDS:
        if interval >= target:
            return interval
    return _NICE_INTERVALS_SECONDS[-1]


def _bucket_expr(interval_seconds: int) -> Any:
    # Cast to plain Float first: dividing the EpochDateTime column directly would make
    # SQLAlchemy coerce interval_seconds's bind param through EpochDateTime.process_bind_param.
    epoch_seconds = cast(MetricPoint.timestamp, Float)
    return cast(epoch_seconds / interval_seconds, Integer).label("bucket")


def _aggregate_expr(metric_type: str) -> Any:
    if metric_type == MetricType.COUNTER.value:
        return func.sum(MetricPoint.value).label("value")
    elif metric_type == MetricType.SET.value:
        return func.count(MetricPoint.value).label("value")
    elif metric_type in (MetricType.GAUGE.value, MetricType.TIMING.value):
        return func.avg(MetricPoint.value).label("value")
    else:
        return func.avg(MetricPoint.value).label("value")


def _tag_filter_clauses(tags: dict[str, str] | None) -> list[Any]:
    """Build WHERE clauses matching json_extract(tags, '$.{key}') = value."""
    if not tags:
        return []
    return [func.json_extract(MetricPoint.tags, f"$.{key}") == value for key, value in tags.items()]


def _select_values_stmt(
    name_id: int | None, from_ts: datetime, to_ts: datetime, tag_clauses: list[Any]
) -> Any:
    """Build a SELECT for a metric's raw values within a time window."""
    return (
        select(MetricPoint.value)
        .where(MetricPoint.name_id == name_id)
        .where(MetricPoint.timestamp >= from_ts)
        .where(MetricPoint.timestamp <= to_ts)
        .where(*tag_clauses)
    )


def _equal_width_bin_edges(lo: float, width: float, bins: int) -> list[float]:
    return [lo + i * width for i in range(bins + 1)]


def _bin_value_counts(values: list[float], lo: float, width: float, bins: int) -> list[int]:
    """Assign each value to one of `bins` equal-width buckets starting at `lo`."""
    counts = [0] * bins
    for v in values:
        counts[min(int((v - lo) / width), bins - 1)] += 1
    return counts


def _timing_percentiles(values: list[float]) -> dict[str, float | int | None]:
    """Compute count/p50/p95 over sorted timing values."""
    if not values:
        return {"count": 0, "p50": None, "p95": None}
    sorted_values = sorted(values)
    n = len(sorted_values)
    return {
        "count": n,
        "p50": sorted_values[min(int(n * 0.50), n - 1)],
        "p95": sorted_values[min(int(n * 0.95), n - 1)],
    }


def list_projects(store: ProjectStore) -> list[dict]:
    """Return project slugs with optional display names from settings.json."""
    return [{"slug": slug, "project": store.get_project_name(slug)} for slug in sorted(store.all_slugs())]


def _hourly_counts(session: Any, model: Any, since: datetime, hours: int) -> list[int]:
    """Count rows per clock hour since `since`, as a dense list of length `hours`."""
    hour_col = cast(cast(model.timestamp, Float) / 3600, Integer).label("hour")
    rows = session.execute(
        select(hour_col, func.count()).where(model.timestamp >= since).group_by(hour_col)
    ).all()
    first_hour = int(since.replace(tzinfo=timezone.utc).timestamp() // 3600)
    counts = [0] * hours
    for hour, count in rows:
        index = int(hour) - first_hour
        if 0 <= index < hours:
            counts[index] = count
    return counts


def project_health(store: ProjectStore, slug: str) -> dict:
    """Compute DB size, row counts, and freshness for one project.

    status is "error" if any ERROR/CRITICAL log landed in the last 24h,
    "stale" if nothing has been written in that window, else "healthy".
    """
    db_size_bytes = sum(f.stat().st_size for f in store.project_dir(slug).glob("*.db"))
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    activity_since = now - timedelta(hours=ACTIVITY_HOURS - 1)

    try:
        with store.logs_session(slug) as session:
            log_count, last_log_at = session.execute(
                select(func.count(LogEntry.id), func.max(LogEntry.timestamp))
            ).one()
            error_count_24h = session.execute(
                select(func.count(LogEntry.id))
                .where(LogEntry.level.in_(_ERROR_LEVELS))
                .where(LogEntry.timestamp >= now - _STALE_AFTER)
            ).scalar_one()
            log_activity = _hourly_counts(session, LogEntry, activity_since, ACTIVITY_HOURS)
        logs_ok = True
    except OperationalError:
        log_count, last_log_at, error_count_24h, logs_ok = 0, None, 0, False
        log_activity = [0] * ACTIVITY_HOURS

    try:
        with store.metrics_session(slug) as session:
            metric_count, last_metric_at = session.execute(
                select(func.count(MetricPoint.id), func.max(MetricPoint.timestamp))
            ).one()
            metric_activity = _hourly_counts(session, MetricPoint, activity_since, ACTIVITY_HOURS)
        metrics_ok = True
    except OperationalError:
        metric_count, last_metric_at, metrics_ok = 0, None, False
        metric_activity = [0] * ACTIVITY_HOURS

    last_activity = max(filter(None, (last_log_at, last_metric_at)), default=None)
    if not (logs_ok and metrics_ok):
        status = "error"
    elif error_count_24h:
        status = "error"
    elif last_activity is None or now - last_activity > _STALE_AFTER:
        status = "stale"
    else:
        status = "healthy"

    return {
        "slug": slug,
        "project": store.get_project_name(slug),
        "db_size_bytes": db_size_bytes,
        "log_count": log_count,
        "metric_count": metric_count,
        "error_count_24h": error_count_24h,
        "last_activity": last_activity,
        "activity": [logs + metrics for logs, metrics in zip(log_activity, metric_activity)],
        "retention_days": store.get_retention_days(slug),
        "status": status,
    }


def list_project_health(store: ProjectStore) -> list[dict]:
    """Return project_health() for every known project, sorted by slug."""
    return [project_health(store, slug) for slug in sorted(store.all_slugs())]


def list_metric_names(store: ProjectStore, project: str) -> list[dict]:
    """Return distinct metric names and types for a project."""
    slug = store.get_slug(project)
    stmt = (
        select(MetricName.name, MetricPoint.metric_type)
        .join(MetricPoint, MetricPoint.name_id == MetricName.id)
        .distinct()
        .order_by(MetricName.name)
    )
    with store.metrics_session(slug) as session:
        rows = session.execute(stmt).all()
    return [{"name": r.name, "metric_type": r.metric_type} for r in rows]


def _metric_type_for_name(store: ProjectStore, slug: str, name: str) -> str | None:
    with store.metrics_session(slug) as session:
        name_id = get_name_id(session, name)
        stmt = (
            select(MetricPoint.metric_type)
            .where(MetricPoint.name_id == name_id)
            .order_by(MetricPoint.timestamp.desc())
            .limit(1)
        )
        return session.execute(stmt).scalar_one_or_none()


def query_metric_series(
    store: ProjectStore,
    project: str,
    name: str,
    from_ts: datetime,
    to_ts: datetime,
    interval_seconds: int | None = None,
    tags: dict[str, str] | None = None,
) -> dict:
    """Return bucketed time-series points for one metric."""
    slug = store.get_slug(project)
    metric_type = _metric_type_for_name(store, slug, name)
    if interval_seconds is None:
        interval_seconds = auto_interval_seconds(from_ts, to_ts)

    bucket_col = _bucket_expr(interval_seconds)
    agg_col = _aggregate_expr(metric_type or MetricType.COUNTER.value)

    with store.metrics_session(slug) as session:
        name_id = get_name_id(session, name)
        stmt = (
            select(bucket_col, agg_col)
            .where(MetricPoint.name_id == name_id)
            .where(MetricPoint.timestamp >= from_ts)
            .where(MetricPoint.timestamp <= to_ts)
            .where(*_tag_filter_clauses(tags))
            .group_by(bucket_col)
            .order_by(bucket_col)
        )
        rows = session.execute(stmt).all()

    points = [
        {
            "timestamp": datetime.fromtimestamp(int(row.bucket) * interval_seconds, tz=timezone.utc)
            .replace(tzinfo=None)
            .isoformat()
            + "Z",
            "value": float(row.value),
        }
        for row in rows
    ]
    return {"metric_type": metric_type, "points": points}


def query_metric_summary(
    store: ProjectStore,
    project: str,
    name: str,
    from_ts: datetime,
    to_ts: datetime,
    tags: dict[str, str] | None = None,
) -> dict:
    """Return latest value, window sum, and window min/avg/max for a metric."""
    slug = store.get_slug(project)
    metric_type = _metric_type_for_name(store, slug, name)
    tag_clauses = _tag_filter_clauses(tags)

    with store.metrics_session(slug) as session:
        name_id = get_name_id(session, name)

        window_filter = [
            MetricPoint.name_id == name_id,
            MetricPoint.timestamp >= from_ts,
            MetricPoint.timestamp <= to_ts,
            *tag_clauses,
        ]

        latest_stmt = (
            select(MetricPoint.value)
            .where(MetricPoint.name_id == name_id, *tag_clauses)
            .order_by(MetricPoint.timestamp.desc())
            .limit(1)
        )
        agg_stmt = select(
            func.sum(MetricPoint.value).label("total"),
            func.min(MetricPoint.value).label("minimum"),
            func.avg(MetricPoint.value).label("average"),
            func.max(MetricPoint.value).label("maximum"),
        ).where(*window_filter)

        latest = session.execute(latest_stmt).scalar_one_or_none()
        agg = session.execute(agg_stmt).one_or_none()
        timing_values: list[float] | None = None
        if metric_type == MetricType.TIMING.value:
            timing_values = [
                float(v)
                for v in session.execute(_select_values_stmt(name_id, from_ts, to_ts, tag_clauses)).scalars()
            ]

    total = agg.total if agg else None
    minimum = agg.minimum if agg else None
    average = agg.average if agg else None
    maximum = agg.maximum if agg else None

    def _f(v: float | None) -> float | None:
        return float(v) if v is not None else None

    result = {
        "metric_type": metric_type,
        "latest_value": _f(latest),
        "sum": _f(total),
        "min": _f(minimum),
        "avg": _f(average),
        "max": _f(maximum),
    }
    if metric_type == MetricType.TIMING.value:
        percentiles = _timing_percentiles(timing_values or [])
        result["count"] = percentiles["count"]
        result["p50"] = _f(percentiles["p50"])
        result["p95"] = _f(percentiles["p95"])
    return result


def query_metric_tag_values(
    store: ProjectStore,
    project: str,
    name: str,
    key: str,
) -> dict:
    """Return distinct tag values for one key on a metric name."""
    slug = store.get_slug(project)
    path = f"$.{key}"
    tag_col = func.json_extract(MetricPoint.tags, path).label("tag_value")
    with store.metrics_session(slug) as session:
        name_id = get_name_id(session, name)
        stmt = (
            select(tag_col)
            .where(MetricPoint.name_id == name_id)
            .where(MetricPoint.tags.isnot(None))
            .where(tag_col.isnot(None))
            .distinct()
            .order_by(tag_col)
        )
        values = [row.tag_value for row in session.execute(stmt).all()]
    return {"key": key, "values": values}


def query_metric_histogram_multi(
    store: ProjectStore,
    project: str,
    names: list[str],
    from_ts: datetime,
    to_ts: datetime,
    bins: int = DEFAULT_HISTOGRAM_BINS,
    tags: dict[str, str] | None = None,
) -> dict:
    """Return equal-width histogram bins shared across several metrics, one count series per metric."""
    slug = store.get_slug(project)
    tag_clauses = _tag_filter_clauses(tags)

    with store.metrics_session(slug) as session:
        values_by_name = {
            name: [
                float(v)
                for v in session.execute(
                    _select_values_stmt(get_name_id(session, name), from_ts, to_ts, tag_clauses)
                ).scalars()
            ]
            for name in names
        }

    all_values = [v for values in values_by_name.values() for v in values]
    if not all_values:
        return {"bins": bins, "edges": [], "series": [{"name": name, "counts": []} for name in names]}

    lo, hi = min(all_values), max(all_values)
    width = (hi - lo) / bins if hi > lo else 1.0
    edges = _equal_width_bin_edges(lo, width, bins)
    series = [
        {"name": name, "counts": _bin_value_counts(values_by_name[name], lo, width, bins)} for name in names
    ]
    return {"bins": bins, "edges": edges, "series": series}


def query_metric_histogram(
    store: ProjectStore,
    project: str,
    name: str,
    from_ts: datetime,
    to_ts: datetime,
    bins: int = DEFAULT_HISTOGRAM_BINS,
    tags: dict[str, str] | None = None,
) -> dict:
    """Return equal-width histogram bins for one metric's values (single-metric case of query_metric_histogram_multi)."""
    multi = query_metric_histogram_multi(store, project, [name], from_ts, to_ts, bins, tags)
    counts = multi["series"][0]["counts"] if multi["series"] else []
    return {"bins": multi["bins"], "edges": multi["edges"], "counts": counts}


def _layout_path(project_dir: Path) -> Path:
    return project_dir / "dashboard.json"


def default_layout() -> dict:
    return {"version": LAYOUT_VERSION, "widgets": []}


def validate_layout(data: dict) -> dict:
    """Validate and normalize a dashboard layout payload."""
    if not isinstance(data, dict):
        raise ValueError("layout must be a JSON object")
    version = data.get("version")
    if version != LAYOUT_VERSION:
        raise ValueError(f"unsupported layout version; expected {LAYOUT_VERSION}")
    widgets = data.get("widgets")
    if not isinstance(widgets, list):
        raise ValueError("widgets must be a list")
    cleaned = []
    for w in widgets:
        if not isinstance(w, dict):
            raise ValueError("each widget must be an object")
        if not all(k in w for k in ("id", "type", "metric_name")):
            raise ValueError("each widget requires id, type, and metric_name")
        if w["type"] not in ALLOWED_WIDGET_TYPES:
            raise ValueError(
                f"unknown widget type: {w['type']}. Allowed: {', '.join(sorted(ALLOWED_WIDGET_TYPES))}"
            )
        widget: dict = {"id": str(w["id"]), "type": w["type"], "metric_name": w["metric_name"]}
        if "title" in w:
            widget["title"] = w["title"]
        cleaned.append(widget)
    return {"version": LAYOUT_VERSION, "widgets": cleaned}


def load_layout(store: ProjectStore, project: str) -> dict:
    """Load a project's dashboard layout, or return the default empty layout."""
    slug = store.get_slug(project)
    path = _layout_path(store.project_dir(slug))
    if not path.exists():
        return default_layout()
    return validate_layout(json.loads(path.read_text()))


def save_layout(store: ProjectStore, project: str, data: dict) -> None:
    """Validate and persist a dashboard layout for a project."""
    slug = store.get_slug(project)
    validated = validate_layout(data)
    path = _layout_path(store.project_dir(slug))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(validated))
