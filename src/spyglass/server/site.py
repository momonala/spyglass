"""Dashboard site blueprint: static UI and dashboard-specific JSON API."""

import re
from datetime import datetime
from datetime import timezone
from pathlib import Path

from flask import Blueprint
from flask import abort
from flask import current_app
from flask import jsonify
from flask import redirect
from flask import render_template
from flask import request
from jinja2 import TemplateNotFound
from markupsafe import Markup

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

_TEMPLATE_DIR = Path(__file__).parent.parent / "templates" / "dashboard"


def _store() -> ProjectStore:
    return current_app.config["STORE"]


@site.app_template_filter("timeago")
def _timeago(when: datetime | None) -> str:
    """Render a naive-UTC timestamp as a short relative age, e.g. "4h ago"."""
    if when is None:
        return "no data"
    seconds = (datetime.now(timezone.utc).replace(tzinfo=None) - when).total_seconds()
    for unit_seconds, suffix in ((86400, "d"), (3600, "h"), (60, "m")):
        if seconds >= unit_seconds:
            return f"{int(seconds // unit_seconds)}{suffix} ago"
    return "just now"


@site.app_template_filter("sparkline")
def _sparkline(values: list[int]) -> Markup:
    """Render bucketed counts as a bare inline SVG bar chart (no axes, no JS).

    The viewBox is stretched to the container width, so bar geometry is in
    arbitrary units and only the relative heights carry meaning.
    """
    peak = max(values, default=0)
    if not peak:
        return Markup('<div class="sparkline sparkline--empty" aria-hidden="true"></div>')

    width, height = 100.0, 24.0
    slot = width / len(values)
    bars = "".join(
        # Empty buckets draw nothing — a minimum-height bar would turn a quiet
        # stretch into a dashed line that reads as data.
        f'<rect x="{i * slot:.3f}" y="{height - v / peak * height:.2f}"'
        f' width="{slot * 0.72:.3f}" height="{v / peak * height:.2f}"/>'
        for i, v in enumerate(values)
        if v
    )
    return Markup(
        f'<svg class="sparkline" viewBox="0 0 {width:g} {height:g}" preserveAspectRatio="none"'
        f' aria-hidden="true">{bars}</svg>'
    )


@site.app_template_filter("compact")
def _compact(value: int) -> str:
    """Abbreviate a count so it fits a stat tile: 1_204 -> "1.2k"."""
    for threshold, suffix in ((1_000_000_000, "b"), (1_000_000, "m"), (1_000, "k")):
        if value >= threshold:
            scaled = value / threshold
            return f"{scaled:.1f}{suffix}" if scaled < 10 else f"{scaled:.0f}{suffix}"
    return str(value)


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


def _parse_tag_filters() -> dict[str, str]:
    """Parse tag_{key}={value} query params into a tag filter dict."""
    tags: dict[str, str] = {}
    for param, value in request.args.items():
        if param.startswith("tag_") and value:
            tags[param[4:]] = value
    return tags


def _parse_bins() -> int:
    raw_bins = request.args.get("bins")
    if not raw_bins:
        return DEFAULT_HISTOGRAM_BINS
    try:
        return int(raw_bins)
    except ValueError:
        abort(400, "bins must be an integer")


def _list_project_templates() -> list[str]:
    return sorted(
        f.stem for f in _TEMPLATE_DIR.glob("*.html") if not f.name.startswith("_") and f.name != "index.html"
    )


@site.get("/dashboard/")
def dashboard_index():
    return render_template(
        "dashboard/index.html",
        projects=_list_project_templates(),
        health=dashboard_queries.list_project_health(_store()),
        activity_hours=dashboard_queries.ACTIVITY_HOURS,
    )


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
        dashboard_queries.query_metric_series(
            _store(), project, name, from_ts, to_ts, interval_seconds, _parse_tag_filters()
        )
    )


@site.get("/dashboard/api/metrics/summary")
def dashboard_metric_summary():
    project = _require_project()
    name = request.args.get("name")
    if not name:
        abort(400, "name is required")
    from_ts, to_ts = _parse_window()
    return jsonify(
        dashboard_queries.query_metric_summary(_store(), project, name, from_ts, to_ts, _parse_tag_filters())
    )


@site.get("/dashboard/api/metrics/tag-values")
def dashboard_metric_tag_values():
    project = _require_project()
    name = request.args.get("name")
    key = request.args.get("key")
    if not name:
        abort(400, "name is required")
    if not key:
        abort(400, "key is required")
    return jsonify(dashboard_queries.query_metric_tag_values(_store(), project, name, key))


@site.get("/dashboard/api/metrics/histogram")
def dashboard_metric_histogram():
    project = _require_project()
    name = request.args.get("name")
    if not name:
        abort(400, "name is required")
    from_ts, to_ts = _parse_window()
    return jsonify(
        dashboard_queries.query_metric_histogram(
            _store(), project, name, from_ts, to_ts, _parse_bins(), _parse_tag_filters()
        )
    )


@site.get("/dashboard/api/metrics/histogram-multi")
def dashboard_metric_histogram_multi():
    project = _require_project()
    names = request.args.getlist("name")
    if not names:
        abort(400, "name is required")
    from_ts, to_ts = _parse_window()
    return jsonify(
        dashboard_queries.query_metric_histogram_multi(
            _store(), project, names, from_ts, to_ts, _parse_bins(), _parse_tag_filters()
        )
    )


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
