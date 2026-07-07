"""Tests for spyglass.dashboard aggregate functions, SummaryBuilder, and SpyglassQueryClient."""

from datetime import datetime
from datetime import timedelta
from datetime import timezone

import pytest

from spyglass.client.query import SpyglassQueryClient
from spyglass.dashboard.aggregate import DEFAULT_ROLLUP
from spyglass.dashboard.aggregate import TimeWindow
from spyglass.dashboard.aggregate import build_log_histogram
from spyglass.dashboard.aggregate import compute_state_uptime
from spyglass.dashboard.aggregate import counter_series
from spyglass.dashboard.aggregate import counter_sum
from spyglass.dashboard.aggregate import latest_gauge
from spyglass.dashboard.aggregate import match_points
from spyglass.dashboard.aggregate import parse_rollup
from spyglass.dashboard.aggregate import parse_window_amount
from spyglass.dashboard.aggregate import parse_window_unit
from spyglass.dashboard.aggregate import prepare_logs
from spyglass.dashboard.aggregate import ratio_series
from spyglass.dashboard.aggregate import resolve_rollup_minutes
from spyglass.dashboard.aggregate import timing_p50_series
from spyglass.dashboard.aggregate import timing_summary
from spyglass.dashboard.aggregate import window_hours_from
from spyglass.dashboard.builder import SummaryBuilder
from spyglass.dashboard.config import ChartDefinition
from spyglass.dashboard.config import ChartSeries
from spyglass.dashboard.config import MetricSelector
from spyglass.dashboard.config import StateTransitionRule

# ---------------------------------------------------------------------------
# Fixtures shared by aggregate and builder tests
# ---------------------------------------------------------------------------


def _point(
    name: str, metric_type: str, value: float, ts: str = "2026-05-27T10:00:00Z", tags: dict | None = None
) -> dict:
    return {"timestamp": ts, "name": name, "metric_type": metric_type, "value": value, "tags": tags}


NOW = datetime(2026, 5, 27, 12, 0, tzinfo=timezone.utc)
WINDOW_START = NOW - timedelta(hours=1)

# Two synthetic app profiles so no Trainspotter-specific assumptions leak in.
_APP_A_METRICS = [
    _point("app-a.worker.requests", "counter", 10, "2026-05-27T11:50:00Z"),
    _point("app-a.worker.requests", "counter", 5, "2026-05-27T11:55:00Z"),
    _point("app-a.worker.latency", "timing", 100, "2026-05-27T11:48:00Z"),
    _point("app-a.worker.latency", "timing", 200, "2026-05-27T11:50:00Z"),
    _point("app-a.worker.latency", "timing", 400, "2026-05-27T11:55:00Z"),
    _point("app-a.worker.queue_depth", "gauge", 7, "2026-05-27T11:59:00Z"),
    _point("app-a.worker.queue_depth", "gauge", 3, "2026-05-27T11:45:00Z"),
]

_APP_B_METRICS = [
    _point("svc-b.api.hits", "counter", 20, "2026-05-27T11:50:00Z"),
    _point("svc-b.api.hits", "counter", 30, "2026-05-27T11:55:00Z"),
    _point("svc-b.api.duration_ms", "timing", 50, "2026-05-27T11:48:00Z"),
    _point("svc-b.api.duration_ms", "timing", 100, "2026-05-27T11:50:00Z"),
    _point("svc-b.api.duration_ms", "timing", 150, "2026-05-27T11:55:00Z"),
]


# ---------------------------------------------------------------------------
# Window parsing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("amount,expected", [(None, 6), (0, 1), (3, 3), (10, 10)])
def test_parse_window_amount(amount, expected):
    assert parse_window_amount(amount) == expected


@pytest.mark.parametrize(
    "unit,expected",
    [("hours", "hours"), ("days", "days"), ("weeks", "weeks"), ("bad", "hours"), (None, "hours")],
)
def test_parse_window_unit(unit, expected):
    assert parse_window_unit(unit) == expected


@pytest.mark.parametrize(
    "amount,unit,expected",
    [
        (6, "hours", 6),
        (2, "days", 48),
        (1, "weeks", 168),
        (3, "months", 2160),
        (0, "hours", 1),
        (20, "months", 8640),
    ],
)
def test_window_hours_from(amount, unit, expected):
    assert window_hours_from(amount, unit) == expected


@pytest.mark.parametrize(
    "rollup,expected",
    [("auto", "auto"), ("15", "15"), ("bad", DEFAULT_ROLLUP), (None, DEFAULT_ROLLUP)],
)
def test_parse_rollup(rollup, expected):
    assert parse_rollup(rollup) == expected


def test_resolve_rollup_minutes_explicit():
    assert resolve_rollup_minutes("30", window_hours=6) == 30


def test_resolve_rollup_minutes_auto():
    assert resolve_rollup_minutes("auto", window_hours=6) == 15


# ---------------------------------------------------------------------------
# TimeWindow
# ---------------------------------------------------------------------------


def test_time_window_bucket_count():
    w = TimeWindow.from_hours(6, NOW, rollup_minutes=15)
    assert w.bucket_count == 24
    assert w.bucket_minutes == 15
    assert w.window_hours == 6


def test_time_window_bucket_index_in_range():
    w = TimeWindow.from_hours(1, NOW, rollup_minutes=5)
    ts = NOW - timedelta(minutes=10)
    idx = w.bucket_index(ts)
    assert idx is not None
    assert 0 <= idx < w.bucket_count


def test_time_window_bucket_index_out_of_range():
    w = TimeWindow.from_hours(1, NOW, rollup_minutes=5)
    assert w.bucket_index(NOW - timedelta(hours=2)) is None
    assert w.bucket_index(NOW + timedelta(minutes=1)) is None


def test_time_window_labels_hourly_format():
    w = TimeWindow.from_hours(6, NOW, rollup_minutes=15)
    labels = w.labels()
    assert len(labels) == w.bucket_count
    assert ":" in labels[0]
    assert "-" not in labels[0]


def test_time_window_labels_multi_day_format():
    w = TimeWindow.from_hours(48, NOW, rollup_minutes=60)
    labels = w.labels()
    assert "-" in labels[0]


# ---------------------------------------------------------------------------
# match_points
# ---------------------------------------------------------------------------


def test_match_points_by_suffix():
    pts = match_points(_APP_A_METRICS, ".requests")
    assert len(pts) == 2
    assert all(p["name"].endswith(".requests") for p in pts)


def test_match_points_by_suffix_and_type():
    pts = match_points(_APP_A_METRICS, ".requests", metric_type="counter")
    assert len(pts) == 2

    pts_timing = match_points(_APP_A_METRICS, ".requests", metric_type="timing")
    assert len(pts_timing) == 0


def test_match_points_by_tags():
    metrics = [
        _point("app.req", "counter", 3, tags={"route": "a"}),
        _point("app.req", "counter", 7, tags={"route": "b"}),
    ]
    assert len(match_points(metrics, ".req", tags={"route": "a"})) == 1
    assert len(match_points(metrics, ".req", tags={"route": "b"})) == 1


def test_match_points_different_app_no_cross_contamination():
    # App A metrics should not match App B suffixes
    assert match_points(_APP_A_METRICS, ".hits") == []
    assert match_points(_APP_B_METRICS, ".requests") == []


# ---------------------------------------------------------------------------
# Scalar aggregation
# ---------------------------------------------------------------------------


def test_counter_sum_app_a():
    assert counter_sum(_APP_A_METRICS, ".requests") == 15.0


def test_counter_sum_app_b():
    assert counter_sum(_APP_B_METRICS, ".hits") == 50.0


def test_counter_sum_no_match():
    assert counter_sum(_APP_A_METRICS, ".nonexistent") == 0.0


def test_counter_sum_with_tags():
    metrics = [
        _point("app.req", "counter", 3, tags={"route": "x"}),
        _point("app.req", "counter", 7, tags={"route": "y"}),
    ]
    assert counter_sum(metrics, ".req", tags={"route": "x"}) == 3.0


def test_timing_summary_app_a():
    result = timing_summary(_APP_A_METRICS, ".latency")
    assert result.count == 3
    assert result.p50 == 200  # median of [100, 200, 400]
    assert result.p95 == 400
    assert result.max == 400


def test_timing_summary_app_b():
    result = timing_summary(_APP_B_METRICS, ".duration_ms")
    assert result.count == 3
    assert result.p50 == 100  # median of [50, 100, 150]
    assert result.p95 == 150
    assert result.max == 150


def test_timing_summary_empty():
    result = timing_summary(_APP_A_METRICS, ".nonexistent")
    assert result.count == 0
    assert result.p50 is None
    assert result.p95 is None
    assert result.max is None


def test_latest_gauge_returns_most_recent():
    result = latest_gauge(_APP_A_METRICS, ".queue_depth")
    assert result == 7.0  # 11:59 is more recent than 11:45


def test_latest_gauge_no_match():
    assert latest_gauge(_APP_A_METRICS, ".missing") is None


# ---------------------------------------------------------------------------
# Bucketed series
# ---------------------------------------------------------------------------


def test_counter_series_sum_matches_scalar():
    w = TimeWindow.from_hours(1, NOW, rollup_minutes=5)
    series = counter_series(_APP_A_METRICS, ".requests", w)
    assert sum(series) == 15.0
    assert len(series) == w.bucket_count


def test_timing_p50_series_non_none_in_range():
    w = TimeWindow.from_hours(1, NOW, rollup_minutes=5)
    series = timing_p50_series(_APP_A_METRICS, ".latency", w)
    assert len(series) == w.bucket_count
    non_null = [v for v in series if v is not None]
    assert len(non_null) == 3  # three distinct 5-min buckets


def test_ratio_series_basic():
    hits = [10.0, 0.0, 5.0]
    totals = [20.0, 0.0, 10.0]
    result = ratio_series(hits, totals)
    assert result == [50.0, None, 50.0]


# ---------------------------------------------------------------------------
# State-transition uptime
# ---------------------------------------------------------------------------


def test_compute_state_uptime_basic():
    window_start = datetime(2026, 5, 27, 11, 0, tzinfo=timezone.utc)
    window_end = datetime(2026, 5, 27, 12, 0, tzinfo=timezone.utc)
    events = [
        (datetime(2026, 5, 27, 11, 10, tzinfo=timezone.utc), "healthy"),
        (datetime(2026, 5, 27, 11, 40, tzinfo=timezone.utc), "degraded"),
    ]
    result = compute_state_uptime(events, window_start, window_end, ["healthy", "degraded", "unknown"])

    assert result.event_count == 2
    assert result.current == "degraded"
    assert result.seconds["unknown"] == pytest.approx(600.0)  # 10 min before first event
    assert result.seconds["healthy"] == pytest.approx(1800.0)  # 30 min
    assert result.seconds["degraded"] == pytest.approx(1200.0)  # 20 min
    total = sum(result.seconds.values())
    assert total == pytest.approx(3600.0)


def test_compute_state_uptime_empty_events():
    window_start = datetime(2026, 5, 27, 11, 0, tzinfo=timezone.utc)
    window_end = datetime(2026, 5, 27, 12, 0, tzinfo=timezone.utc)
    result = compute_state_uptime([], window_start, window_end, ["healthy", "unknown"])

    assert result.current == "unknown"
    assert result.event_count == 0
    assert result.seconds["unknown"] == pytest.approx(3600.0)
    assert result.pcts["unknown"] == pytest.approx(100.0)


def test_compute_state_uptime_pcts_sum_to_100():
    window_start = datetime(2026, 5, 27, 11, 0, tzinfo=timezone.utc)
    window_end = datetime(2026, 5, 27, 12, 0, tzinfo=timezone.utc)
    events = [
        (datetime(2026, 5, 27, 11, 15, tzinfo=timezone.utc), "a"),
        (datetime(2026, 5, 27, 11, 45, tzinfo=timezone.utc), "b"),
    ]
    result = compute_state_uptime(events, window_start, window_end, ["a", "b", "unknown"])
    assert sum(result.pcts.values()) == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# Log processing
# ---------------------------------------------------------------------------


def test_prepare_logs_parses_spyglass_format():
    logs = [
        {
            "timestamp": "2026-05-27T10:00:00Z",
            "level": "INFO",
            "logger_name": "app",
            "message": "2026-05-27 10:00:00,123 INFO [my_func] app.module hello world",
        }
    ]
    result = prepare_logs(logs)
    assert result[0].function == "my_func"
    assert result[0].message == "hello world"
    assert result[0].level == "INFO"


def test_prepare_logs_plain_message():
    logs = [
        {
            "timestamp": "2026-05-27T10:00:00Z",
            "level": "WARNING",
            "logger_name": "app",
            "message": "plain text",
        }
    ]
    result = prepare_logs(logs)
    assert result[0].function is None
    assert result[0].message == "plain text"


def test_build_log_histogram_counts_by_level():
    w = TimeWindow.from_hours(1, NOW, rollup_minutes=5)
    logs = prepare_logs(
        [
            {"timestamp": "2026-05-27T11:50:00Z", "level": "INFO", "logger_name": "a", "message": "x"},
            {"timestamp": "2026-05-27T11:50:00Z", "level": "ERROR", "logger_name": "a", "message": "y"},
            {"timestamp": "2026-05-27T11:55:00Z", "level": "WARNING", "logger_name": "a", "message": "z"},
        ]
    )
    hist = build_log_histogram(logs, w)
    assert len(hist.labels) == w.bucket_count
    assert hist.by_level["INFO"][-2] == 1
    assert hist.by_level["ERROR"][-2] == 1
    assert hist.by_level["WARNING"][-1] == 1
    assert sum(hist.by_level["DEBUG"]) == 0


# ---------------------------------------------------------------------------
# SummaryBuilder (end-to-end with synthetic app)
# ---------------------------------------------------------------------------


_SELECTORS = {
    "requests": MetricSelector(".requests", metric_type="counter"),
    "latency": MetricSelector(".latency", metric_type="timing"),
    "queue": MetricSelector(".queue_depth", metric_type="gauge"),
    "healthy": MetricSelector(".healthy", metric_type="counter"),
    "degraded": MetricSelector(".degraded", metric_type="counter"),
}

_STATE_RULES = [
    StateTransitionRule("healthy", "healthy"),
    StateTransitionRule("degraded", "degraded"),
]

_CHARTS = [
    ChartDefinition("throughput", series=[ChartSeries("reqs", "requests", metric_type="counter")]),
    ChartDefinition("latency_p50", series=[ChartSeries("p50", "latency", metric_type="timing")]),
]


def test_summary_builder_counters_and_timings():
    builder = SummaryBuilder(
        selectors=_SELECTORS,
        state_rules=_STATE_RULES,
        charts=_CHARTS,
        states=["healthy", "degraded", "unknown"],
    )
    result = builder.build(_APP_A_METRICS, [], window_amount=1, window_unit="hours", rollup="auto", now=NOW)

    assert result.counters["requests"] == 15.0
    assert result.timings["latency"].count == 3
    assert result.timings["latency"].p50 == 200
    assert result.gauges["queue"] == 7.0
    assert result.state is not None
    assert len(result.charts) == 2
    assert result.charts[0].name == "throughput"
    assert sum(result.charts[0].series["reqs"]) == 15.0


def test_summary_builder_window_info():
    builder = SummaryBuilder(selectors=_SELECTORS, state_rules=[], charts=[], states=[])
    result = builder.build([], [], window_amount=6, window_unit="hours", rollup="15", now=NOW)
    assert result.window.amount == 6
    assert result.window.unit == "hours"
    assert result.window.hours == 6
    assert result.window.rollup_minutes == 15


def test_summary_builder_log_histogram():
    builder = SummaryBuilder(selectors=_SELECTORS, state_rules=[], charts=[], states=[])
    logs = [{"timestamp": "2026-05-27T11:50:00Z", "level": "INFO", "logger_name": "a", "message": "hi"}]
    result = builder.build([], logs, window_amount=1, window_unit="hours", rollup="5", now=NOW)
    assert result.log_histogram is not None
    assert "INFO" in result.log_histogram.by_level


# ---------------------------------------------------------------------------
# SpyglassQueryClient
# ---------------------------------------------------------------------------


def test_query_client_normalises_host():
    client = SpyglassQueryClient(host="localhost:5013", project="test")
    assert client._base == "http://localhost:5013"

    client_with_scheme = SpyglassQueryClient(host="http://localhost:5013", project="test")
    assert client_with_scheme._base == "http://localhost:5013"


def test_query_client_status_returns_none_on_error():
    client = SpyglassQueryClient(host="localhost:9999", project="test", timeout=0.01)
    result = client.status()
    assert result is None


def test_query_client_fetch_metrics_raises_on_http_error():
    client = SpyglassQueryClient(host="localhost:9999", project="test", timeout=0.01)
    with pytest.raises(Exception):
        client.fetch_metrics(since=datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Dashboard metrics API (tag filtering, timing percentiles, tag-values)
# ---------------------------------------------------------------------------


def _ingest_points(client, project: str, points: list[dict]) -> None:
    resp = client.post("/metrics", json={"project": project, "points": points})
    assert resp.status_code == 201


def test_dashboard_summary_tag_filter(client):
    project = "tag-test"
    metric = f"{project}.fn.vbb.error"
    _ingest_points(client, project, [
        {"name": metric, "metric_type": "counter", "value": 5, "tags": {"kind": "http_503"}},
        {"name": metric, "metric_type": "counter", "value": 2, "tags": {"kind": "timeout"}},
    ])

    all_resp = client.get(f"/dashboard/api/metrics/summary?project={project}&name={metric}")
    assert all_resp.status_code == 200
    assert all_resp.get_json()["sum"] == 7.0

    filtered = client.get(
        f"/dashboard/api/metrics/summary?project={project}&name={metric}&tag_kind=http_503"
    )
    assert filtered.status_code == 200
    assert filtered.get_json()["sum"] == 5.0


def test_dashboard_series_tag_filter(client):
    project = "tag-series"
    metric = f"{project}.fn.vbb.error"
    _ingest_points(client, project, [
        {"name": metric, "metric_type": "counter", "value": 3, "tags": {"kind": "http_503"}},
        {"name": metric, "metric_type": "counter", "value": 9, "tags": {"kind": "timeout"}},
    ])

    resp = client.get(
        f"/dashboard/api/metrics/series?project={project}&name={metric}&tag_kind=timeout"
    )
    assert resp.status_code == 200
    points = resp.get_json()["points"]
    assert len(points) >= 1
    assert sum(p["value"] for p in points) == 9.0


def test_dashboard_summary_timing_percentiles(client):
    project = "timing-pct"
    metric = f"{project}.fn.vbb.fetch"
    _ingest_points(client, project, [
        {"name": metric, "metric_type": "timing", "value": 100},
        {"name": metric, "metric_type": "timing", "value": 200},
        {"name": metric, "metric_type": "timing", "value": 400},
    ])

    resp = client.get(f"/dashboard/api/metrics/summary?project={project}&name={metric}")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["metric_type"] == "timing"
    assert data["count"] == 3
    assert data["p50"] == 200.0
    assert data["p95"] == 400.0


def test_dashboard_tag_values(client):
    project = "tag-values"
    metric = f"{project}.fn.vbb.error"
    _ingest_points(client, project, [
        {"name": metric, "metric_type": "counter", "value": 1, "tags": {"kind": "http_503"}},
        {"name": metric, "metric_type": "counter", "value": 1, "tags": {"kind": "timeout"}},
        {"name": metric, "metric_type": "counter", "value": 1, "tags": {"kind": "http_503"}},
    ])

    resp = client.get(
        f"/dashboard/api/metrics/tag-values?project={project}&name={metric}&key=kind"
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["key"] == "kind"
    assert set(data["values"]) == {"http_503", "timeout"}
