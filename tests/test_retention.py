"""Tests for the retention job: stale rows are deleted, fresh rows are kept."""

from datetime import datetime
from datetime import timedelta
from datetime import timezone

from spyglass.db.models import LogEntry
from spyglass.db.models import MetricPoint
from spyglass.db.store import ProjectStore
from spyglass.server.retention import run_retention


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _insert_metric(store: ProjectStore, slug: str, days_old: int) -> None:
    ts = _utcnow() - timedelta(days=days_old)
    with store.metrics_session(slug) as session:
        session.add(MetricPoint(timestamp=ts, name="test.fn.c", metric_type="counter", value=1))
        session.commit()


def _insert_log(store: ProjectStore, slug: str, days_old: int) -> None:
    ts = _utcnow() - timedelta(days=days_old)
    with store.logs_session(slug) as session:
        session.add(LogEntry(timestamp=ts, level="INFO", logger_name="test", message="msg"))
        session.commit()


def _count_metrics(store: ProjectStore, slug: str) -> int:
    from sqlalchemy import func
    from sqlalchemy import select

    with store.metrics_session(slug) as session:
        return session.execute(select(func.count()).select_from(MetricPoint)).scalar()


def _count_logs(store: ProjectStore, slug: str) -> int:
    from sqlalchemy import func
    from sqlalchemy import select

    with store.logs_session(slug) as session:
        return session.execute(select(func.count()).select_from(LogEntry)).scalar()


def test_retention_deletes_old_rows(tmp_path):
    store = ProjectStore(tmp_path / "data")
    slug = store.init_project("my-api", retention_days=30)

    _insert_metric(store, slug, days_old=31)  # stale
    _insert_metric(store, slug, days_old=5)  # fresh
    _insert_log(store, slug, days_old=45)  # stale
    _insert_log(store, slug, days_old=1)  # fresh

    run_retention(store)

    assert _count_metrics(store, slug) == 1
    assert _count_logs(store, slug) == 1


def test_retention_keeps_all_fresh_rows(tmp_path):
    store = ProjectStore(tmp_path / "data")
    slug = store.init_project("my-api", retention_days=30)

    _insert_metric(store, slug, days_old=1)
    _insert_metric(store, slug, days_old=10)
    _insert_log(store, slug, days_old=2)

    run_retention(store)

    assert _count_metrics(store, slug) == 2
    assert _count_logs(store, slug) == 1


def test_retention_handles_empty_project(tmp_path):
    store = ProjectStore(tmp_path / "data")
    store.init_project("empty-project", retention_days=30)
    run_retention(store)  # should not raise


def test_retention_respects_per_project_retention_days(tmp_path):
    store = ProjectStore(tmp_path / "data")
    slug_short = store.init_project("short-lived", retention_days=7)
    slug_long = store.init_project("long-lived", retention_days=90)

    # 10 days old: stale for short-lived (7d), fresh for long-lived (90d)
    _insert_metric(store, slug_short, days_old=10)
    _insert_metric(store, slug_long, days_old=10)

    run_retention(store)

    assert _count_metrics(store, slug_short) == 0
    assert _count_metrics(store, slug_long) == 1


def test_retention_runs_across_multiple_projects(tmp_path):
    store = ProjectStore(tmp_path / "data")
    slug_a = store.init_project("alpha", retention_days=30)
    slug_b = store.init_project("beta", retention_days=30)

    _insert_metric(store, slug_a, days_old=60)
    _insert_metric(store, slug_b, days_old=60)

    run_retention(store)

    assert _count_metrics(store, slug_a) == 0
    assert _count_metrics(store, slug_b) == 0
