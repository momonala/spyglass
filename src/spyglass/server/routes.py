"""Flask API blueprint: ingest and read for metrics and logs."""

import json
import logging

from flask import Blueprint
from flask import Response
from flask import current_app
from flask import jsonify
from flask import request
from sqlalchemy import select

from spyglass.db.metric_names import name_to_id_map
from spyglass.db.models import LogEntry
from spyglass.db.models import MetricPoint
from spyglass.db.models import MetricType
from spyglass.db.store import DEFAULT_RETENTION_DAYS
from spyglass.db.store import ProjectStore
from spyglass.server.util import parse_timestamp
from spyglass.server.write_buffer import PendingMetric
from spyglass.server.write_buffer import WriteBuffer

logger = logging.getLogger(__name__)

api = Blueprint("api", __name__)

DEFAULT_QUERY_LIMIT = 1000


def _store() -> ProjectStore:
    return current_app.config["STORE"]


def _write_buffer() -> WriteBuffer:
    return current_app.config["WRITE_BUFFER"]


def _unwrap_batch(data: dict, key: str) -> list:
    return data.get(key, [data])


def _validate_metric_type(raw_type: str) -> tuple[MetricType | None, Response | None]:
    try:
        return MetricType(raw_type), None
    except ValueError:
        allowed = ", ".join(t.value for t in MetricType)
        return None, jsonify({"error": f"unknown metric_type: {raw_type}. Allowed: {allowed}"})


@api.post("/projects/register")
def register_project() -> tuple[Response, int]:
    data = request.get_json(silent=True) or {}
    project = data.get("project")
    if not project:
        return jsonify({"error": "project is required"}), 400

    retention_days = int(data.get("retention_days", DEFAULT_RETENTION_DAYS))
    try:
        slug = _store().init_project(project, retention_days)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 409
    logger.info("Registered project %r (slug=%s, retention=%dd)", project, slug, retention_days)
    return jsonify({"slug": slug, "retention_days": retention_days}), 200


@api.post("/metrics")
def ingest_metrics() -> tuple[Response, int]:
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "invalid JSON"}), 400

    project = data.get("project")
    if not project:
        return jsonify({"error": "project is required"}), 400

    raw_points = _unwrap_batch(data, "points")

    parsed = []
    for p in raw_points:
        if not p.get("name") or not p.get("metric_type"):
            return jsonify({"error": "each point requires name and metric_type"}), 400
        metric_type, err = _validate_metric_type(p["metric_type"])
        if err is not None:
            return err, 400
        parsed.append((p, metric_type))

    slug = _store().get_slug(project)
    rows = [
        PendingMetric(
            name=p["name"],
            timestamp=parse_timestamp(p.get("timestamp")),
            metric_type=metric_type.value,
            value=float(p.get("value", 0)),
            tags=json.dumps(p["tags"]) if p.get("tags") is not None else None,
        )
        for p, metric_type in parsed
    ]
    _write_buffer().add_metrics(slug, rows)

    return jsonify({"inserted": len(rows)}), 201


@api.post("/logs")
def ingest_logs() -> tuple[Response, int]:
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "invalid JSON"}), 400

    project = data.get("project")
    if not project:
        return jsonify({"error": "project is required"}), 400

    raw_entries = _unwrap_batch(data, "entries")

    rows = []
    for e in raw_entries:
        if not e.get("message"):
            return jsonify({"error": "each entry requires message"}), 400
        rows.append(
            LogEntry(
                timestamp=parse_timestamp(e.get("timestamp")),
                level=e.get("level", "INFO").upper(),
                logger_name=e.get("logger_name", ""),
                message=e["message"],
            )
        )

    slug = _store().get_slug(project)
    _write_buffer().add_logs(slug, rows)

    return jsonify({"inserted": len(rows)}), 201


@api.get("/metrics")
def query_metrics() -> Response:
    project = request.args.get("project")
    if not project:
        return jsonify({"error": "project is required"}), 400

    stmt = select(MetricPoint).order_by(MetricPoint.timestamp.desc())

    if raw_type := request.args.get("metric_type"):
        metric_type, err = _validate_metric_type(raw_type)
        if err is not None:
            return err, 400
        stmt = stmt.where(MetricPoint.metric_type == metric_type.value)
    if from_ts := request.args.get("from"):
        stmt = stmt.where(MetricPoint.timestamp >= parse_timestamp(from_ts))
    if to_ts := request.args.get("to"):
        stmt = stmt.where(MetricPoint.timestamp <= parse_timestamp(to_ts))

    limit = int(request.args.get("limit", DEFAULT_QUERY_LIMIT))
    if limit > 0:
        stmt = stmt.limit(limit)

    store = _store()
    slug = store.get_slug(project)
    with store.metrics_session(slug) as session:
        names = name_to_id_map(session)
        if name_prefix := request.args.get("name"):
            matching_ids = [id_ for name, id_ in names.items() if name.startswith(name_prefix)]
            stmt = stmt.where(MetricPoint.name_id.in_(matching_ids))
        rows = session.execute(stmt).scalars().all()
        id_to_name = {id_: name for name, id_ in names.items()}

    return jsonify(
        [
            {
                "timestamp": r.timestamp.isoformat() + "Z",
                "name": id_to_name[r.name_id],
                "metric_type": r.metric_type,
                "value": r.value,
                "tags": json.loads(r.tags) if r.tags else None,
            }
            for r in rows
        ]
    )


@api.get("/logs")
def query_logs() -> Response:
    project = request.args.get("project")
    if not project:
        return jsonify({"error": "project is required"}), 400

    stmt = select(LogEntry).order_by(LogEntry.timestamp.desc())

    if level := request.args.get("level"):
        stmt = stmt.where(LogEntry.level == level.upper())
    if from_ts := request.args.get("from"):
        stmt = stmt.where(LogEntry.timestamp >= parse_timestamp(from_ts))
    if to_ts := request.args.get("to"):
        stmt = stmt.where(LogEntry.timestamp <= parse_timestamp(to_ts))

    limit = int(request.args.get("limit", DEFAULT_QUERY_LIMIT))
    if limit > 0:
        stmt = stmt.limit(limit)

    store = _store()
    slug = store.get_slug(project)
    with store.logs_session(slug) as session:
        rows = session.execute(stmt).scalars().all()

    return jsonify(
        [
            {
                "timestamp": r.timestamp.isoformat() + "Z",
                "level": r.level,
                "logger_name": r.logger_name,
                "message": r.message,
            }
            for r in rows
        ]
    )
