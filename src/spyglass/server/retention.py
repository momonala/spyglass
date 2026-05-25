"""Background retention job: delete data older than each project's retention window."""

import logging
import threading
import time
from datetime import datetime
from datetime import timedelta
from datetime import timezone

import schedule
from sqlalchemy import delete

from spyglass.db.models import LogEntry
from spyglass.db.models import MetricPoint
from spyglass.db.store import ProjectStore

logger = logging.getLogger(__name__)


def run_retention(store: ProjectStore) -> None:
    """Delete stale rows from every known project's metrics and logs DBs."""
    for slug in store.all_slugs():
        retention_days = store.get_retention_days(slug)
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=retention_days)

        with store.metrics_session(slug) as session:
            result = session.execute(delete(MetricPoint).where(MetricPoint.timestamp < cutoff))
            session.commit()
            deleted_metrics = result.rowcount

        with store.logs_session(slug) as session:
            result = session.execute(delete(LogEntry).where(LogEntry.timestamp < cutoff))
            session.commit()
            deleted_logs = result.rowcount

        if deleted_metrics or deleted_logs:
            logger.info(
                "Retention [%s]: removed %d metrics, %d logs (cutoff=%s)",
                slug,
                deleted_metrics,
                deleted_logs,
                cutoff.date(),
            )


def start_retention_thread(store: ProjectStore) -> threading.Thread:
    """Start a daemon thread that runs retention at startup and then every hour.

    Uses a per-instance ``schedule.Scheduler`` to avoid polluting the global
    scheduler (important when multiple stores are created in tests).

    Args:
        store: The shared ProjectStore instance.

    Returns:
        The started daemon thread.
    """
    scheduler = schedule.Scheduler()
    scheduler.every(1).hours.do(run_retention, store)

    def loop() -> None:
        run_retention(store)  # run once immediately at startup
        while True:
            scheduler.run_pending()
            time.sleep(60)  # check for due jobs every minute

    thread = threading.Thread(target=loop, daemon=True, name="spyglass-retention")
    thread.start()
    return thread
