"""Resolve MetricPoint.name_id against the metric_names lookup table.

Only ever a few dozen distinct names per project, so no caching layer is
needed: every lookup is an indexed query against a tiny table.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from spyglass.db.models import MetricName


def get_name_id(session: Session, name: str) -> int | None:
    """Look up the id for an existing metric name, or None if it's never been seen."""
    return session.execute(select(MetricName.id).where(MetricName.name == name)).scalar_one_or_none()


def get_or_create_name_id(session: Session, name: str) -> int:
    """Look up the id for a metric name, inserting it if this is the first time it's seen."""
    name_id = get_name_id(session, name)
    if name_id is not None:
        return name_id
    row = MetricName(name=name)
    session.add(row)
    session.flush()
    return row.id


def name_to_id_map(session: Session) -> dict[str, int]:
    """All known metric names for this project, as name -> id."""
    return dict(session.execute(select(MetricName.name, MetricName.id)).all())


def id_to_name_map(session: Session) -> dict[int, str]:
    """All known metric names for this project, as id -> name."""
    return {id_: name for name, id_ in name_to_id_map(session).items()}
