"""Integration tests for the Flask API using test_client().

Covers registration, ingest, read queries, and validation errors.
"""


def test_health(client):
    resp = client.get("/status")
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok"}


def test_register_project(client):
    resp = client.post("/projects/register", json={"project": "my-api", "retention_days": 14})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["slug"] == "my-api"
    assert data["retention_days"] == 14


def test_register_project_missing_name(client):
    resp = client.post("/projects/register", json={})
    assert resp.status_code == 400


def test_ingest_single_metric_point(client):
    resp = client.post(
        "/metrics",
        json={
            "project": "my-api",
            "name": "my-api.handle_request.requests",
            "metric_type": "counter",
            "value": 1,
        },
    )
    assert resp.status_code == 201
    assert resp.get_json()["inserted"] == 1


def test_ingest_batch_metric_points(client):
    resp = client.post(
        "/metrics",
        json={
            "project": "my-api",
            "points": [
                {"name": "my-api.fn.counter", "metric_type": "counter", "value": 1},
                {"name": "my-api.fn.duration", "metric_type": "timing", "value": 42.5},
            ],
        },
    )
    assert resp.status_code == 201
    assert resp.get_json()["inserted"] == 2


def test_ingest_metric_invalid_type(client):
    resp = client.post(
        "/metrics",
        json={"project": "p", "name": "p.f.s", "metric_type": "histogram", "value": 1},
    )
    assert resp.status_code == 400


def test_ingest_metric_missing_project(client):
    resp = client.post("/metrics", json={"name": "x.y.z", "metric_type": "counter", "value": 1})
    assert resp.status_code == 400


def test_ingest_single_log_entry(client):
    resp = client.post(
        "/logs",
        json={"project": "my-api", "message": "Server started", "level": "INFO"},
    )
    assert resp.status_code == 201
    assert resp.get_json()["inserted"] == 1


def test_ingest_batch_log_entries(client):
    resp = client.post(
        "/logs",
        json={
            "project": "my-api",
            "entries": [
                {"message": "First", "level": "DEBUG"},
                {"message": "Second", "level": "WARNING"},
            ],
        },
    )
    assert resp.status_code == 201
    assert resp.get_json()["inserted"] == 2


def test_ingest_log_missing_project(client):
    resp = client.post("/logs", json={"message": "oops"})
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


def test_read_metrics_returns_all(client):
    _seed_metrics(client)
    resp = client.get("/metrics?project=my-api")
    assert resp.status_code == 200
    rows = resp.get_json()
    assert len(rows) == 3


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


def test_read_metrics_missing_project(client):
    resp = client.get("/metrics")
    assert resp.status_code == 400


def test_read_metrics_respects_limit(client):
    _seed_metrics(client)
    resp = client.get("/metrics?project=my-api&limit=1")
    assert len(resp.get_json()) == 1


def test_read_metrics_no_limit_returns_all(client):
    _seed_metrics(client)
    resp = client.get("/metrics?project=my-api&limit=0")
    assert len(resp.get_json()) == 3


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


def test_read_logs_returns_all(client):
    _seed_logs(client)
    resp = client.get("/logs?project=my-api")
    assert resp.status_code == 200
    assert len(resp.get_json()) == 3


def test_read_logs_filter_by_level(client):
    _seed_logs(client)
    resp = client.get("/logs?project=my-api&level=error")
    rows = resp.get_json()
    assert len(rows) == 1
    assert rows[0]["level"] == "ERROR"


def test_read_logs_missing_project(client):
    resp = client.get("/logs")
    assert resp.status_code == 400


def test_read_logs_no_limit_returns_all(client):
    _seed_logs(client)
    resp = client.get("/logs?project=my-api&limit=0")
    assert len(resp.get_json()) == 3


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
