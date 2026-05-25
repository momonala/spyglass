"""Integration tests for the dashboard site blueprint."""

import json


def _seed_project(client, project="my-api"):
    client.post("/projects/register", json={"project": project, "retention_days": 30})
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


def test_dashboard_page(client):
    resp = client.get("/dashboard")
    assert resp.status_code == 200
    assert b"Spyglass Dashboard" in resp.data


def test_root_redirects_to_dashboard(client):
    resp = client.get("/")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/dashboard")


def test_dashboard_projects(client):
    _seed_project(client, "alpha")
    resp = client.get("/dashboard/api/projects")
    assert resp.status_code == 200
    projects = resp.get_json()
    assert any(project["slug"] == "alpha" for project in projects)


def test_dashboard_metric_names(client):
    _seed_project(client)
    resp = client.get("/dashboard/api/metrics/names?project=my-api")
    assert resp.status_code == 200
    names = {row["name"] for row in resp.get_json()}
    assert "my-api.fn.counter" in names
    assert "my-api.fn.latency" in names


def test_dashboard_metric_names_missing_project(client):
    resp = client.get("/dashboard/api/metrics/names")
    assert resp.status_code == 400


def test_dashboard_metric_series(client):
    _seed_project(client)
    resp = client.get("/dashboard/api/metrics/series?project=my-api&name=my-api.fn.counter")
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["metric_type"] == "counter"
    assert len(payload["points"]) >= 1


def test_dashboard_metric_summary(client):
    _seed_project(client)
    resp = client.get("/dashboard/api/metrics/summary?project=my-api&name=my-api.fn.queue")
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["latest_value"] == 7.0


def test_dashboard_metric_histogram(client):
    _seed_project(client)
    resp = client.get("/dashboard/api/metrics/histogram?project=my-api&name=my-api.fn.latency")
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["count"] == 1
    assert len(payload["bins"]) == 1


def test_dashboard_layout_round_trip(client, store):
    _seed_project(client)
    layout = {
        "version": 1,
        "widgets": [
            {
                "id": "widget-1",
                "type": "timeseries",
                "metric_name": "my-api.fn.counter",
                "title": "Requests",
            }
        ],
    }

    put_resp = client.put(
        "/dashboard/api/layout?project=my-api",
        json=layout,
    )
    assert put_resp.status_code == 200
    assert put_resp.get_json() == layout

    get_resp = client.get("/dashboard/api/layout?project=my-api")
    assert get_resp.status_code == 200
    assert get_resp.get_json() == layout

    saved_path = store.project_dir("my-api") / "dashboard.json"
    assert saved_path.exists()
    assert json.loads(saved_path.read_text()) == layout


def test_dashboard_layout_validation(client):
    _seed_project(client)
    resp = client.put(
        "/dashboard/api/layout?project=my-api",
        json={"version": 1, "widgets": [{"id": "x", "type": "unknown", "metric_name": "a.b"}]},
    )
    assert resp.status_code == 400


def test_dashboard_layout_missing_project(client):
    resp = client.get("/dashboard/api/layout")
    assert resp.status_code == 400
