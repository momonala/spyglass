"""Tests for the server-side write buffer."""

import datetime

from sqlalchemy import func
from sqlalchemy import select

from spyglass.db.models import MetricPoint
from spyglass.server.write_buffer import PendingMetric
from spyglass.server.write_buffer import WriteBuffer


def _point(name: str = "m") -> PendingMetric:
    return PendingMetric(
        name=name,
        timestamp=datetime.datetime.now(datetime.UTC),
        metric_type="gauge",
        value=1.0,
        tags=None,
    )


def _count(store, slug: str) -> int:
    with store.metrics_session(slug) as session:
        return session.scalar(select(func.count()).select_from(MetricPoint))


def test_buffered_rows_are_written_only_on_flush(store):
    slug = store.init_project("demo", 30)
    buffer = WriteBuffer(store, flush_interval_s=120)

    buffer.add_metrics(slug, [_point(), _point("other")])
    assert _count(store, slug) == 0

    buffer.flush()
    assert _count(store, slug) == 2


def test_stop_flushes_pending_rows(store):
    slug = store.init_project("demo", 30)
    buffer = WriteBuffer(store, flush_interval_s=120)

    buffer.add_metrics(slug, [_point()])
    buffer.stop()
    assert _count(store, slug) == 1


def test_zero_interval_writes_immediately(store):
    slug = store.init_project("demo", 30)
    WriteBuffer(store).add_metrics(slug, [_point()])
    assert _count(store, slug) == 1
