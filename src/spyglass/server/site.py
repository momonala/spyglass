"""Dashboard site blueprint: static UI and dashboard-specific JSON API."""

from flask import Blueprint
from flask import abort
from flask import current_app
from flask import jsonify
from flask import redirect
from flask import request
from flask import send_from_directory

from spyglass.db.store import ProjectStore
from spyglass.server import dashboard_queries
from spyglass.server.util import parse_time_range

site = Blueprint(
    "site",
    __name__,
    static_folder="../static/dashboard",
    static_url_path="/dashboard/static",
)


def _store() -> ProjectStore:
    return current_app.config["STORE"]


def _require_project() -> str:
    project = request.args.get("project")
    if not project:
        abort(400, description="project is required")
    return project


def _parse_window() -> tuple:
    from_ts, to_ts = parse_time_range(
        request.args.get("from"),
        request.args.get("to"),
    )
    if from_ts > to_ts:
        abort(400, description="from must be before to")
    return from_ts, to_ts


@site.get("/dashboard")
def dashboard_index():
    return send_from_directory(site.static_folder, "index.html")


@site.get("/")
def root_redirect():
    return redirect("/dashboard")


@site.get("/dashboard/api/projects")
def dashboard_projects():
    return jsonify(dashboard_queries.list_projects(_store()))


@site.get("/dashboard/api/metrics/names")
def dashboard_metric_names():
    project = _require_project()
    return jsonify(dashboard_queries.list_metric_names(_store(), project))


@site.get("/dashboard/api/metrics/series")
def dashboard_metric_series():
    project = _require_project()
    name = request.args.get("name") or abort(400, description="name is required")
    from_ts, to_ts = _parse_window()
    interval = request.args.get("interval")
    interval_seconds = int(interval) if interval else None
    return jsonify(
        dashboard_queries.query_metric_series(
            _store(), project, name, from_ts, to_ts, interval_seconds,
        )
    )


@site.get("/dashboard/api/metrics/summary")
def dashboard_metric_summary():
    project = _require_project()
    name = request.args.get("name") or abort(400, description="name is required")
    from_ts, to_ts = _parse_window()
    return jsonify(
        dashboard_queries.query_metric_summary(_store(), project, name, from_ts, to_ts)
    )


@site.get("/dashboard/api/metrics/histogram")
def dashboard_metric_histogram():
    project = _require_project()
    name = request.args.get("name") or abort(400, description="name is required")
    from_ts, to_ts = _parse_window()
    try:
        bins = int(request.args.get("bins", dashboard_queries.DEFAULT_HISTOGRAM_BINS))
    except ValueError:
        abort(400, description="bins must be an integer")
    return jsonify(
        dashboard_queries.query_metric_histogram(_store(), project, name, from_ts, to_ts, bins)
    )


@site.get("/dashboard/api/layout")
def dashboard_get_layout():
    project = _require_project()
    return jsonify(dashboard_queries.load_layout(_store(), project))


@site.put("/dashboard/api/layout")
def dashboard_put_layout():
    project = _require_project()
    data = request.get_json(silent=True)
    if data is None:
        abort(400, description="invalid JSON")
    try:
        layout = dashboard_queries.save_layout(_store(), project, data)
    except ValueError as exc:
        abort(400, description=str(exc))
    return jsonify(layout)
