"""Integration tests for the Flask API using test_client().

Covers registration, ingest, read queries, and validation errors.
"""

import logging
from datetime import UTC
from datetime import datetime

import pytest

from spyglass.client.collector import MetricsCollector
from spyglass.client.logging import SpyglassHandler


def test_status_reports_ok(client):
    resp = client.get("/status")
    assert resp.get_json() == {"status": "ok"}


def test_register_project(client):
    resp = client.post("/projects/register", json={"project": "my-api", "retention_days": 14})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["slug"] == "my-api"
    assert data["retention_days"] == 14


@pytest.mark.parametrize(
    "method, path, body",
    [
        ("post", "/projects/register", {}),
        ("post", "/metrics", {"name": "x.y.z", "metric_type": "counter", "value": 1}),
        ("post", "/logs", {"message": "oops"}),
        ("get", "/metrics", None),
        ("get", "/logs", None),
    ],
)
def test_requests_without_project_are_rejected(client, method, path, body):
    resp = getattr(client, method)(path, json=body)
    assert resp.status_code == 400


def test_ingest_accepts_a_single_unwrapped_point(client):
    resp = client.post(
        "/metrics",
        json={"project": "my-api", "name": "my-api.fn.requests", "metric_type": "counter", "value": 1},
    )

    assert resp.status_code == 201
    rows = client.get("/metrics?project=my-api").get_json()
    assert [(r["name"], r["metric_type"], r["value"]) for r in rows] == [
        ("my-api.fn.requests", "counter", 1.0)
    ]


def test_ingest_metric_invalid_type(client):
    resp = client.post(
        "/metrics",
        json={"project": "p", "name": "p.f.s", "metric_type": "histogram", "value": 1},
    )
    assert resp.status_code == 400


def _seed_metrics(client, project="my-api"):
    client.post(
        "/metrics",
        json={
            "project": project,
            "points": [
                {"name": f"{project}.fn.counter", "metric_type": "counter", "value": 1},
                {"name": f"{project}.fn.latency", "metric_type": "timing", "value": 55.0},
                {"name": f"{project}.fn.queue", "metric_type": "gauge", "value": 7},
            ],
        },
    )


def test_read_metrics_filter_by_type(client):
    _seed_metrics(client)
    resp = client.get("/metrics?project=my-api&metric_type=counter")
    rows = resp.get_json()
    assert all(r["metric_type"] == "counter" for r in rows)
    assert len(rows) == 1


def test_read_metrics_filter_by_name_prefix(client):
    _seed_metrics(client)
    resp = client.get("/metrics?project=my-api&name=my-api.fn.lat")
    rows = resp.get_json()
    assert len(rows) == 1
    assert rows[0]["name"] == "my-api.fn.latency"


def test_read_metrics_limit_caps_rows_and_zero_means_unlimited(client):
    _seed_metrics(client)
    assert len(client.get("/metrics?project=my-api&limit=1").get_json()) == 1
    assert len(client.get("/metrics?project=my-api&limit=0").get_json()) == 3


def _seed_logs(client, project="my-api"):
    client.post(
        "/logs",
        json={
            "project": project,
            "entries": [
                {"message": "info msg", "level": "INFO"},
                {"message": "error msg", "level": "ERROR"},
                {"message": "debug msg", "level": "DEBUG"},
            ],
        },
    )


def test_read_logs_limit_caps_rows_and_zero_means_unlimited(client):
    _seed_logs(client)
    assert len(client.get("/logs?project=my-api&limit=1").get_json()) == 1
    assert len(client.get("/logs?project=my-api&limit=0").get_json()) == 3


def test_server_accepts_what_the_client_sends(client, posts):
    collector = MetricsCollector(host="localhost:19999", project="wire")
    collector.increment("hits", tags={"route": "/a"})
    collector.gauge("depth", 3)
    collector.timing("latency", 5.0)
    collector.set("users", 1)
    collector.flush()
    handler = SpyglassHandler(host="localhost:19999", project="wire")
    handler.emit(logging.LogRecord("app", logging.WARNING, __file__, 1, "hello", None, None))
    handler.flush()

    paths = [url.removeprefix("http://localhost:19999") for url, _ in posts]
    assert {"/metrics", "/logs"} <= set(paths)
    for path, (_, body) in zip(paths, posts, strict=True):
        expected = 200 if path == "/projects/register" else 201
        assert client.post(path, json=body).status_code == expected, path

    assert len(client.get("/metrics?project=wire").get_json()) == 4
    assert len(client.get("/logs?project=wire").get_json()) == 1


def test_read_logs_filter_by_level(client):
    _seed_logs(client)
    resp = client.get("/logs?project=my-api&level=error")
    rows = resp.get_json()
    assert len(rows) == 1
    assert rows[0]["level"] == "ERROR"


def test_projects_are_isolated(client):
    client.post(
        "/metrics", json={"project": "alpha", "name": "alpha.f.c", "metric_type": "counter", "value": 1}
    )
    client.post(
        "/metrics", json={"project": "beta", "name": "beta.f.c", "metric_type": "counter", "value": 99}
    )

    alpha_rows = client.get("/metrics?project=alpha").get_json()
    beta_rows = client.get("/metrics?project=beta").get_json()

    assert len(alpha_rows) == 1
    assert alpha_rows[0]["value"] == 1.0
    assert len(beta_rows) == 1
    assert beta_rows[0]["value"] == 99.0


def test_metric_summary_reports_when_the_latest_matching_point_landed(client):
    name = "my-api.post.received"
    client.post(
        "/metrics",
        json={
            "project": "my-api",
            "points": [
                {
                    "name": name,
                    "metric_type": "counter",
                    "value": 1,
                    "tags": {"device": "air"},
                    "timestamp": "2026-10-25T08:00:00Z",
                },
                {
                    "name": name,
                    "metric_type": "counter",
                    "value": 1,
                    "tags": {"device": "pro"},
                    "timestamp": "2026-10-25T09:00:00Z",
                },
            ],
        },
    )

    resp = client.get(
        "/dashboard/api/metrics/summary",
        query_string={
            "project": "my-api",
            "name": name,
            "tag_device": "air",
            "from": "2026-10-25T00:00:00Z",
            "to": "2026-10-26T00:00:00Z",
        },
    )

    assert resp.get_json()["latest_at"] == datetime(2026, 10, 25, 8, tzinfo=UTC).timestamp()
