"""Dashboard site blueprint: static UI and dashboard-specific JSON API."""

import os
import re

from flask import Blueprint
from flask import abort
from flask import current_app
from flask import jsonify
from flask import redirect
from flask import render_template
from flask import request
from jinja2 import TemplateNotFound

from spyglass.db.store import ProjectStore
from spyglass.server import dashboard_queries
from spyglass.server.dashboard_queries import DEFAULT_HISTOGRAM_BINS
from spyglass.server.util import parse_time_range

site = Blueprint(
    "site",
    __name__,
    static_folder="../static/dashboard",
    static_url_path="/dashboard/static",
    template_folder="../templates",
)

_VALID_PROJECT = re.compile(r"^[a-z0-9][a-z0-9_-]*$")

_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "../templates/dashboard")


def _store() -> ProjectStore:
    return current_app.config["STORE"]


def _require_project() -> str:
    project = request.args.get("project")
    if not project:
        abort(400, "project is required")
    return project


def _parse_window() -> tuple[object, object]:
    from_ts, to_ts = parse_time_range(request.args.get("from"), request.args.get("to"))
    if from_ts >= to_ts:
        abort(400, "from must be before to")
    return from_ts, to_ts


def _list_project_templates() -> list[str]:
    return sorted(
        os.path.splitext(f)[0]
        for f in os.listdir(_TEMPLATE_DIR)
        if f.endswith(".html") and not f.startswith("_") and f != "index.html"
    )


@site.get("/dashboard/")
def dashboard_index():
    return render_template("dashboard/index.html", projects=_list_project_templates())


@site.get("/")
def root_redirect():
    return redirect("/dashboard/")


@site.get("/dashboard/<project>")
def project_dashboard(project: str):
    if not _VALID_PROJECT.match(project):
        abort(400, f"invalid project name: {project!r}")
    try:
        return render_template(
            f"dashboard/{project}.html",
            project=project,
            projects=_list_project_templates(),
        )
    except TemplateNotFound:
        abort(404, f"no dashboard configured for project {project!r}")


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
    name = request.args.get("name")
    if not name:
        abort(400, "name is required")
    from_ts, to_ts = _parse_window()
    raw_interval = request.args.get("interval")
    if raw_interval:
        try:
            interval_seconds = int(raw_interval)
        except ValueError:
            abort(400, "interval must be an integer")
    else:
        interval_seconds = None
    return jsonify(
        dashboard_queries.query_metric_series(_store(), project, name, from_ts, to_ts, interval_seconds)
    )


@site.get("/dashboard/api/metrics/summary")
def dashboard_metric_summary():
    project = _require_project()
    name = request.args.get("name")
    if not name:
        abort(400, "name is required")
    from_ts, to_ts = _parse_window()
    return jsonify(dashboard_queries.query_metric_summary(_store(), project, name, from_ts, to_ts))


@site.get("/dashboard/api/metrics/histogram")
def dashboard_metric_histogram():
    project = _require_project()
    name = request.args.get("name")
    if not name:
        abort(400, "name is required")
    from_ts, to_ts = _parse_window()
    bins = DEFAULT_HISTOGRAM_BINS
    raw_bins = request.args.get("bins")
    if raw_bins:
        try:
            bins = int(raw_bins)
        except ValueError:
            abort(400, "bins must be an integer")
    return jsonify(dashboard_queries.query_metric_histogram(_store(), project, name, from_ts, to_ts, bins))


@site.get("/dashboard/api/layout")
def dashboard_get_layout():
    project = _require_project()
    return jsonify(dashboard_queries.load_layout(_store(), project))


@site.put("/dashboard/api/layout")
def dashboard_put_layout():
    project = _require_project()
    data = request.get_json()
    if data is None:
        abort(400, "invalid JSON")
    try:
        dashboard_queries.save_layout(_store(), project, data)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"ok": True})
