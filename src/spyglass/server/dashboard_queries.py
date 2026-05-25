"""Dashboard query helpers: metric aggregation and layout persistence."""

import json
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from pathlib import Path
from typing import Any

from sqlalchemy import Integer
from sqlalchemy import cast
from sqlalchemy import func
from sqlalchemy import select

from spyglass.db.models import MetricPoint
from spyglass.db.models import MetricType
from spyglass.db.store import ProjectStore
from spyglass.server.util import parse_timestamp
from spyglass.server.util import utcnow

LAYOUT_VERSION = 1
ALLOWED_WIDGET_TYPES = frozenset({"timeseries", "counter", "histogram"})
DEFAULT_SERIES_BUCKETS = 60
DEFAULT_HISTOGRAM_BINS = 20

_NICE_INTERVALS_SECONDS = (
    1,
    5,
    15,
    30,
    60,
    300,
    900,
    1800,
    3600,
    7200,
    14400,
    86400,
)




def auto_interval_seconds(from_ts: datetime, to_ts: datetime, max_buckets: int = DEFAULT_SERIES_BUCKETS) -> int:
    """Pick a bucket width that keeps the series near max_buckets points."""
    span = max((to_ts - from_ts).total_seconds(), 1)
    target = span / max_buckets
    for interval in _NICE_INTERVALS_SECONDS:
        if target <= interval:
            return interval
    return _NICE_INTERVALS_SECONDS[-1]


def _bucket_expr(interval_seconds: int) -> Any:
    epoch = cast(func.strftime("%s", MetricPoint.timestamp), Integer)
    return (epoch / interval_seconds) * interval_seconds


def _aggregate_expr(metric_type: str) -> Any:
    if metric_type == MetricType.COUNTER.value:
        return func.sum(MetricPoint.value).label("value")
    if metric_type == MetricType.SET.value:
        return func.count().label("value")
    return func.avg(MetricPoint.value).label("value")


def list_projects(store: ProjectStore) -> list[dict[str, str]]:
    """Return project slugs with optional display names from settings.json."""
    projects = []
    for slug in sorted(store.all_slugs()):
        settings_path = store.project_dir(slug) / "settings.json"
        display_name = slug
        if settings_path.exists():
            settings = json.loads(settings_path.read_text())
            display_name = settings.get("project", slug)
        projects.append({"slug": slug, "name": display_name})
    return projects


def list_metric_names(store: ProjectStore, project: str) -> list[dict[str, str]]:
    """Return distinct metric names and types for a project."""
    slug = store.get_slug(project)
    stmt = select(MetricPoint.name, MetricPoint.metric_type).distinct().order_by(MetricPoint.name)
    with store.metrics_session(slug) as session:
        rows = session.execute(stmt).all()
    return [{"name": name, "metric_type": metric_type} for name, metric_type in rows]


def _metric_type_for_name(store: ProjectStore, slug: str, name: str) -> str | None:
    stmt = (
        select(MetricPoint.metric_type)
        .where(MetricPoint.name == name)
        .order_by(MetricPoint.timestamp.desc())
        .limit(1)
    )
    with store.metrics_session(slug) as session:
        return session.execute(stmt).scalar_one_or_none()


def query_metric_series(
    store: ProjectStore,
    project: str,
    name: str,
    from_ts: datetime,
    to_ts: datetime,
    interval_seconds: int | None = None,
) -> dict[str, Any]:
    """Return bucketed time-series points for one metric."""
    slug = store.get_slug(project)
    metric_type = _metric_type_for_name(store, slug, name)
    if metric_type is None:
        return {
            "name": name,
            "metric_type": None,
            "interval_seconds": interval_seconds or 60,
            "points": [],
        }

    bucket_width = interval_seconds or auto_interval_seconds(from_ts, to_ts)
    bucket = _bucket_expr(bucket_width).label("bucket")
    stmt = (
        select(bucket, _aggregate_expr(metric_type))
        .where(
            MetricPoint.name == name,
            MetricPoint.timestamp >= from_ts,
            MetricPoint.timestamp <= to_ts,
        )
        .group_by(bucket)
        .order_by(bucket)
    )

    with store.metrics_session(slug) as session:
        rows = session.execute(stmt).all()

    points = [
        {
            "timestamp": datetime.fromtimestamp(int(bucket_epoch), tz=timezone.utc)
            .replace(tzinfo=None)
            .isoformat()
            + "Z",
            "value": float(value),
        }
        for bucket_epoch, value in rows
    ]
    return {
        "name": name,
        "metric_type": metric_type,
        "interval_seconds": bucket_width,
        "points": points,
    }


def query_metric_summary(
    store: ProjectStore,
    project: str,
    name: str,
    from_ts: datetime,
    to_ts: datetime,
) -> dict[str, Any]:
    """Return latest value and optional window sum for counter tiles."""
    slug = store.get_slug(project)
    metric_type = _metric_type_for_name(store, slug, name)
    if metric_type is None:
        return {
            "name": name,
            "metric_type": None,
            "latest_value": None,
            "window_sum": None,
        }

    latest_stmt = (
        select(MetricPoint.value)
        .where(MetricPoint.name == name)
        .order_by(MetricPoint.timestamp.desc())
        .limit(1)
    )
    window_stmt = (
        select(func.sum(MetricPoint.value))
        .where(
            MetricPoint.name == name,
            MetricPoint.timestamp >= from_ts,
            MetricPoint.timestamp <= to_ts,
        )
    )

    with store.metrics_session(slug) as session:
        latest_value = session.execute(latest_stmt).scalar_one_or_none()
        window_sum = session.execute(window_stmt).scalar_one_or_none()

    return {
        "name": name,
        "metric_type": metric_type,
        "latest_value": float(latest_value) if latest_value is not None else None,
        "window_sum": float(window_sum) if window_sum is not None else None,
    }


def query_metric_histogram(
    store: ProjectStore,
    project: str,
    name: str,
    from_ts: datetime,
    to_ts: datetime,
    bins: int = DEFAULT_HISTOGRAM_BINS,
) -> dict[str, Any]:
    """Return equal-width histogram bins for timing metric values."""
    slug = store.get_slug(project)
    metric_type = _metric_type_for_name(store, slug, name)
    if metric_type is None:
        return {"name": name, "metric_type": None, "bins": [], "count": 0}

    values_stmt = (
        select(MetricPoint.value)
        .where(
            MetricPoint.name == name,
            MetricPoint.timestamp >= from_ts,
            MetricPoint.timestamp <= to_ts,
        )
        .order_by(MetricPoint.value)
    )
    with store.metrics_session(slug) as session:
        values = [float(v) for v in session.execute(values_stmt).scalars().all()]

    if not values:
        return {"name": name, "metric_type": metric_type, "bins": [], "count": 0}

    min_value = values[0]
    max_value = values[-1]
    if min_value == max_value:
        return {
            "name": name,
            "metric_type": metric_type,
            "bins": [{"start": min_value, "end": max_value, "count": len(values)}],
            "count": len(values),
        }

    bin_count = max(bins, 1)
    width = (max_value - min_value) / bin_count
    counts = [0] * bin_count
    for value in values:
        index = min(int((value - min_value) / width), bin_count - 1)
        counts[index] += 1

    histogram_bins = []
    for index, count in enumerate(counts):
        start = min_value + index * width
        end = min_value + (index + 1) * width
        histogram_bins.append({"start": start, "end": end, "count": count})

    return {
        "name": name,
        "metric_type": metric_type,
        "bins": histogram_bins,
        "count": len(values),
    }


def _layout_path(store: ProjectStore, slug: str) -> Path:
    return store.project_dir(slug) / "dashboard.json"


def default_layout() -> dict:
    return {"version": LAYOUT_VERSION, "widgets": []}


def validate_layout(data: dict) -> dict:
    """Validate and normalize a dashboard layout payload."""
    if not isinstance(data, dict):
        raise ValueError("layout must be a JSON object")
    if data.get("version") != LAYOUT_VERSION:
        raise ValueError(f"unsupported layout version; expected {LAYOUT_VERSION}")

    widgets = data.get("widgets")
    if not isinstance(widgets, list):
        raise ValueError("widgets must be a list")

    normalized_widgets = []
    for widget in widgets:
        if not isinstance(widget, dict):
            raise ValueError("each widget must be an object")
        widget_id = widget.get("id")
        widget_type = widget.get("type")
        metric_name = widget.get("metric_name")
        if not widget_id or not widget_type or not metric_name:
            raise ValueError("each widget requires id, type, and metric_name")
        if widget_type not in ALLOWED_WIDGET_TYPES:
            allowed = ", ".join(sorted(ALLOWED_WIDGET_TYPES))
            raise ValueError(f"unknown widget type: {widget_type}. Allowed: {allowed}")

        normalized_widgets.append(
            {
                "id": str(widget_id),
                "type": widget_type,
                "metric_name": str(metric_name),
                "title": str(widget.get("title") or metric_name),
            }
        )

    return {"version": LAYOUT_VERSION, "widgets": normalized_widgets}


def load_layout(store: ProjectStore, project: str) -> dict:
    """Load a project's dashboard layout, or return the default empty layout."""
    slug = store.get_slug(project)
    path = _layout_path(store, slug)
    if not path.exists():
        return default_layout()
    return validate_layout(json.loads(path.read_text()))


def save_layout(store: ProjectStore, project: str, data: dict) -> dict:
    """Validate and persist a dashboard layout for a project."""
    slug = store.get_slug(project)
    normalized = validate_layout(data)
    path = _layout_path(store, slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(normalized, indent=2))
    return normalized
