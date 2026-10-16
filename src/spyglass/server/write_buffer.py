"""Batch ingested metrics and logs in memory and write them to SQLite on an interval."""

import datetime
import logging
import threading
from collections import defaultdict
from dataclasses import dataclass
from dataclasses import field

from spyglass.db.metric_names import get_or_create_name_id
from spyglass.db.models import LogEntry
from spyglass.db.models import MetricPoint
from spyglass.db.store import ProjectStore

logger = logging.getLogger(__name__)


@dataclass
class PendingMetric:
    name: str
    timestamp: datetime.datetime
    metric_type: str
    value: float
    tags: str | None


@dataclass
class _Pending:
    metrics: dict[str, list[PendingMetric]] = field(default_factory=lambda: defaultdict(list))
    logs: dict[str, list[LogEntry]] = field(default_factory=lambda: defaultdict(list))


class WriteBuffer:
    """Collect rows per project and commit them once per flush, one transaction per database.

    With `flush_interval_s` of 0 every add is written immediately.
    """

    def __init__(self, store: ProjectStore, flush_interval_s: float = 0) -> None:
        self.store = store
        self.flush_interval_s = flush_interval_s
        self._pending = _Pending()
        self._lock = threading.Lock()
        self._flush_lock = threading.Lock()
        self._stop = threading.Event()

    def add_metrics(self, slug: str, points: list[PendingMetric]) -> None:
        with self._lock:
            self._pending.metrics[slug].extend(points)
        if not self.flush_interval_s:
            self.flush()

    def add_logs(self, slug: str, entries: list[LogEntry]) -> None:
        with self._lock:
            self._pending.logs[slug].extend(entries)
        if not self.flush_interval_s:
            self.flush()

    def flush(self) -> None:
        with self._flush_lock:
            with self._lock:
                pending, self._pending = self._pending, _Pending()
            for slug, points in pending.metrics.items():
                try:
                    self._write_metrics(slug, points)
                except Exception:
                    logger.exception("Write buffer [%s]: dropped %d metric points", slug, len(points))
            for slug, entries in pending.logs.items():
                try:
                    self._write_logs(slug, entries)
                except Exception:
                    logger.exception("Write buffer [%s]: dropped %d log entries", slug, len(entries))

    def _write_metrics(self, slug: str, points: list[PendingMetric]) -> None:
        with self.store.metrics_session(slug) as session:
            session.add_all(
                MetricPoint(
                    timestamp=p.timestamp,
                    name_id=get_or_create_name_id(session, p.name),
                    metric_type=p.metric_type,
                    value=p.value,
                    tags=p.tags,
                )
                for p in points
            )
            session.commit()

    def _write_logs(self, slug: str, entries: list[LogEntry]) -> None:
        with self.store.logs_session(slug) as session:
            session.add_all(entries)
            session.commit()

    def start(self) -> threading.Thread:
        def loop() -> None:
            while not self._stop.wait(self.flush_interval_s):
                self.flush()

        thread = threading.Thread(target=loop, daemon=True, name="spyglass-write-buffer")
        thread.start()
        return thread

    def stop(self) -> None:
        self._stop.set()
        self.flush()
