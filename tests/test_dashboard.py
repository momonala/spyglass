"""Tests for spyglass.dashboard aggregate functions, SummaryBuilder, and SpyglassQueryClient."""

from datetime import UTC
from datetime import datetime
from datetime import timedelta
from datetime import timezone

import pytest
import requests

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


NOW = datetime(2026, 5, 27, 12, 0, tzinfo=UTC)
WINDOW_START = NOW - timedelta(hours=1)

_APP_A_METRICS = [
    _point("app-a.worker.requests", "counter", 10, "2026-05-27T11:50:00Z"),
    _point("app-a.worker.requests", "counter", 5, "2026-05-27T11:55:00Z"),
    _point("app-a.worker.latency", "timing", 100, "2026-05-27T11:48:00Z"),
    _point("app-a.worker.latency", "timing", 200, "2026-05-27T11:50:00Z"),
    _point("app-a.worker.latency", "timing", 400, "2026-05-27T11:55:00Z"),
    _point("app-a.worker.queue_depth", "gauge", 7, "2026-05-27T11:59:00Z"),
    _point("app-a.worker.queue_depth", "gauge", 3, "2026-05-27T11:45:00Z"),
]


# ---------------------------------------------------------------------------
# Window parsing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("amount,expected", [(None, 6), (0, 1), (3, 3)])
def test_parse_window_amount(amount, expected):
    assert parse_window_amount(amount) == expected


@pytest.mark.parametrize("unit,expected", [("days", "days"), ("bad", "hours")])
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


@pytest.mark.parametrize("rollup,expected", [("15", "15"), ("bad", DEFAULT_ROLLUP), (None, DEFAULT_ROLLUP)])
def test_parse_rollup(rollup, expected):
    assert parse_rollup(rollup) == expected


@pytest.mark.parametrize("rollup,expected", [("30", 30), ("auto", 15)])
def test_resolve_rollup_minutes(rollup, expected):
    assert resolve_rollup_minutes(rollup, window_hours=6) == expected


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
    assert w.bucket_index(NOW - timedelta(minutes=10)) == 10


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


def test_match_points_by_suffix_and_type():
    pts = match_points(_APP_A_METRICS, ".requests", metric_type="counter")
    assert len(pts) == 2

    pts_timing = match_points(_APP_A_METRICS, ".requests", metric_type="timing")
    assert len(pts_timing) == 0


# ---------------------------------------------------------------------------
# Scalar aggregation
# ---------------------------------------------------------------------------


def test_counter_sum_app_a():
    assert counter_sum(_APP_A_METRICS, ".requests") == 15.0


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
    window_start = datetime(2026, 5, 27, 11, 0, tzinfo=UTC)
    window_end = datetime(2026, 5, 27, 12, 0, tzinfo=UTC)
    events = [
        (datetime(2026, 5, 27, 11, 10, tzinfo=UTC), "healthy"),
        (datetime(2026, 5, 27, 11, 40, tzinfo=UTC), "degraded"),
    ]
    result = compute_state_uptime(events, window_start, window_end, ["healthy", "degraded", "unknown"])

    assert result.event_count == 2
    assert result.current == "degraded"
    assert result.seconds["unknown"] == pytest.approx(600.0)  # 10 min before first event
    assert result.seconds["healthy"] == pytest.approx(1800.0)  # 30 min
    assert result.seconds["degraded"] == pytest.approx(1200.0)  # 20 min
    total = sum(result.seconds.values())
    assert total == pytest.approx(3600.0)
    assert result.pcts == {"healthy": 50.0, "degraded": 33.3, "unknown": 16.7}


def test_compute_state_uptime_empty_events():
    window_start = datetime(2026, 5, 27, 11, 0, tzinfo=UTC)
    window_end = datetime(2026, 5, 27, 12, 0, tzinfo=UTC)
    result = compute_state_uptime([], window_start, window_end, ["healthy", "unknown"])

    assert result.current == "unknown"
    assert result.event_count == 0
    assert result.seconds["unknown"] == pytest.approx(3600.0)
    assert result.pcts["unknown"] == pytest.approx(100.0)


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


def test_summary_builder_without_state_rules_reports_no_state():
    builder = SummaryBuilder(selectors=_SELECTORS, state_rules=[], charts=[], states=[])
    result = builder.build(_APP_A_METRICS, [], window_amount=1, window_unit="hours", rollup="auto", now=NOW)
    assert result.state is None


# ---------------------------------------------------------------------------
# SpyglassQueryClient
# ---------------------------------------------------------------------------


class _FakeQueryResponse:
    def raise_for_status(self):
        pass

    def json(self):
        return []


def test_query_client_scopes_fetch_to_project_and_utc_since(monkeypatch):
    calls = []

    def _fake_get(self, url, params=None, timeout=None):
        calls.append((url, params))
        return _FakeQueryResponse()

    monkeypatch.setattr("requests.Session.get", _fake_get)
    client = SpyglassQueryClient(host="localhost:5013", project="test", limit=50)

    client.fetch_metrics(since=datetime(2026, 5, 27, 14, 30, 15, 999, tzinfo=timezone(timedelta(hours=2))))

    assert calls == [
        ("http://localhost:5013/metrics", {"project": "test", "from": "2026-05-27T12:30:15Z", "limit": 50})
    ]


def test_query_client_status_returns_none_when_server_unreachable(monkeypatch):
    def _refuse(self, url, timeout=None):
        raise requests.ConnectionError("server down")

    monkeypatch.setattr("requests.Session.get", _refuse)

    assert SpyglassQueryClient(host="localhost:5013", project="test").status() is None


# ---------------------------------------------------------------------------
# Dashboard metrics API (tag filtering, timing percentiles, tag-values)
# ---------------------------------------------------------------------------


def _ingest_points(client, project: str, points: list[dict]) -> None:
    resp = client.post("/metrics", json={"project": project, "points": points})
    assert resp.status_code == 201


def test_dashboard_summary_tag_filter(client):
    project = "tag-test"
    metric = f"{project}.fn.vbb.error"
    _ingest_points(
        client,
        project,
        [
            {"name": metric, "metric_type": "counter", "value": 5, "tags": {"kind": "http_503"}},
            {"name": metric, "metric_type": "counter", "value": 2, "tags": {"kind": "timeout"}},
        ],
    )

    all_resp = client.get(f"/dashboard/api/metrics/summary?project={project}&name={metric}")
    assert all_resp.status_code == 200
    assert all_resp.get_json()["sum"] == 7.0

    filtered = client.get(f"/dashboard/api/metrics/summary?project={project}&name={metric}&tag_kind=http_503")
    assert filtered.status_code == 200
    assert filtered.get_json()["sum"] == 5.0


def test_dashboard_series_tag_filter(client):
    project = "tag-series"
    metric = f"{project}.fn.vbb.error"
    _ingest_points(
        client,
        project,
        [
            {"name": metric, "metric_type": "counter", "value": 3, "tags": {"kind": "http_503"}},
            {"name": metric, "metric_type": "counter", "value": 9, "tags": {"kind": "timeout"}},
        ],
    )

    resp = client.get(f"/dashboard/api/metrics/series?project={project}&name={metric}&tag_kind=timeout")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["metric_type"] == "counter"
    points = body["points"]
    assert len(points) >= 1
    assert sum(p["value"] for p in points) == 9.0


def test_dashboard_series_averages_timings_per_bucket(client):
    project = "series-timing"
    metric = f"{project}.fn.latency"
    _ingest_points(
        client,
        project,
        [
            {"name": metric, "metric_type": "timing", "value": 10, "timestamp": "2026-05-27T10:00:05Z"},
            {"name": metric, "metric_type": "timing", "value": 20, "timestamp": "2026-05-27T10:00:10Z"},
        ],
    )

    resp = client.get(
        "/dashboard/api/metrics/series",
        query_string={
            "project": project,
            "name": metric,
            "from": "2026-05-27T10:00:00Z",
            "to": "2026-05-27T11:00:00Z",
        },
    )

    body = resp.get_json()
    assert body["metric_type"] == "timing"
    assert [p["value"] for p in body["points"]] == [15.0]


def test_dashboard_summary_timing_percentiles(client):
    project = "timing-pct"
    metric = f"{project}.fn.vbb.fetch"
    _ingest_points(
        client,
        project,
        [
            {"name": metric, "metric_type": "timing", "value": 100},
            {"name": metric, "metric_type": "timing", "value": 200},
            {"name": metric, "metric_type": "timing", "value": 400},
        ],
    )

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
    _ingest_points(
        client,
        project,
        [
            {"name": metric, "metric_type": "counter", "value": 1, "tags": {"kind": "http_503"}},
            {"name": metric, "metric_type": "counter", "value": 1, "tags": {"kind": "timeout"}},
            {"name": metric, "metric_type": "counter", "value": 1, "tags": {"kind": "http_503"}},
        ],
    )

    resp = client.get(f"/dashboard/api/metrics/tag-values?project={project}&name={metric}&key=kind")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["key"] == "kind"
    assert set(data["values"]) == {"http_503", "timeout"}
