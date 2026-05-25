"""MetricsCollector: emits counters, gauges, timings, and sets to the Spyglass server."""

import inspect
import logging
import time
from contextlib import contextmanager
from datetime import datetime
from datetime import timezone

from spyglass.client.http_client import create_session
from spyglass.db.models import MetricType

_log = logging.getLogger(__name__)

SPYGLASS_PACKAGE = "spyglass"


def _normalize_host(host: str) -> str:
    if host.startswith(("http://", "https://")):
        return host
    return f"http://{host}"


def _caller_function() -> str:
    """Walk the call stack and return the first function name outside of spyglass."""
    for frame_info in inspect.stack():
        module = frame_info.frame.f_globals.get("__name__", "")
        if not module.startswith(SPYGLASS_PACKAGE):
            return frame_info.function
    return "<unknown>"


class MetricsCollector:
    """Emits metrics to a running Spyglass server.

    Stat names are automatically prefixed with ``{project}.{caller_function}``.
    Pass ``prefix=False`` to any emit method to send the stat name as-is.

    Args:
        host: Server address, e.g. ``"localhost:5013"`` or ``"http://localhost:5013"``.
        project: Project name (required). Used for stat prefixes and server routing.
        retention_days: How long to retain data on the server. Sent on registration.
        tags: Optional dict of tags merged into every emitted point.
        timeout: HTTP request timeout in seconds.

    Example::

        collector = MetricsCollector(host="localhost:5013", project="my-api")

        def handle_request():
            collector.increment("requests")          # myproject.handle_request.requests
            collector.gauge("queue_depth", 42)
            with collector.timed("db_query"):
                run_query()
    """

    def __init__(
        self,
        host: str,
        project: str,
        retention_days: int = 30,
        tags: dict | None = None,
        timeout: float = 2.0,
    ) -> None:
        if not project.strip():
            raise ValueError("project is required and must be non-empty")
        self._host = _normalize_host(host)
        self.project = project
        self._tags = tags or {}
        self._timeout = timeout
        self._session = create_session()
        self._register(retention_days)

    def increment(
        self, stat: str, value: float = 1, *, tags: dict | None = None, prefix: bool = True
    ) -> None:
        """Increment a counter stat."""
        self._emit(MetricType.COUNTER, stat, value, tags, prefix)

    def decrement(
        self, stat: str, value: float = 1, *, tags: dict | None = None, prefix: bool = True
    ) -> None:
        """Decrement a counter stat (sends a negative value)."""
        self._emit(MetricType.COUNTER, stat, -abs(value), tags, prefix)

    def gauge(self, stat: str, value: float, *, tags: dict | None = None, prefix: bool = True) -> None:
        """Record a gauge value."""
        self._emit(MetricType.GAUGE, stat, value, tags, prefix)

    def timing(self, stat: str, value_ms: float, *, tags: dict | None = None, prefix: bool = True) -> None:
        """Record a timing in milliseconds."""
        self._emit(MetricType.TIMING, stat, value_ms, tags, prefix)

    def set(self, stat: str, value: float, *, tags: dict | None = None, prefix: bool = True) -> None:
        """Record a set membership value."""
        self._emit(MetricType.SET, stat, value, tags, prefix)

    @contextmanager
    def timed(self, stat: str, *, tags: dict | None = None, prefix: bool = True):
        """Context manager that measures elapsed time and emits a timing metric.

        Args:
            stat: Stat name (will be prefixed unless ``prefix=False``).
            tags: Optional tags for this emit.
            prefix: Whether to auto-prefix with project and caller name.

        Example::

            with collector.timed("db_query"):
                run_query()
        """
        caller = _caller_function()
        start = time.perf_counter()
        try:
            yield
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000
            name = f"{self.project}.{caller}.{stat}" if prefix else stat
            self._send_point(MetricType.TIMING, name, elapsed_ms, tags)

    def _emit(
        self,
        metric_type: MetricType,
        stat: str,
        value: float,
        tags: dict | None,
        prefix: bool,
    ) -> None:
        caller = _caller_function()
        name = f"{self.project}.{caller}.{stat}" if prefix else stat
        self._send_point(metric_type, name, value, tags)

    def _send_point(self, metric_type: MetricType, name: str, value: float, tags: dict | None) -> None:
        merged_tags = {**self._tags, **(tags or {})} or None
        payload = {
            "project": self.project,
            "points": [
                {
                    "name": name,
                    "metric_type": metric_type.value,
                    "value": value,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    **({"tags": merged_tags} if merged_tags else {}),
                }
            ],
        }
        try:
            self._session.post(f"{self._host}/metrics", json=payload, timeout=self._timeout)
        except Exception as exc:
            _log.debug("spyglass metric emit failed: %s", exc)

    def _register(self, retention_days: int) -> None:
        try:
            self._session.post(
                f"{self._host}/projects/register",
                json={"project": self.project, "retention_days": retention_days},
                timeout=self._timeout,
            )
        except Exception as exc:
            _log.debug("spyglass project registration failed: %s", exc)
