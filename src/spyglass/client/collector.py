"""MetricsCollector: emits counters, gauges, timings, and sets to the Spyglass server."""

import functools
import inspect
import json
import logging
import time
from collections.abc import Callable
from datetime import UTC
from datetime import datetime

import requests

from spyglass.client.batching import DEFAULT_FLUSH_INTERVAL
from spyglass.client.batching import Batcher
from spyglass.client.http_client import _normalize_host
from spyglass.client.http_client import create_session
from spyglass.db.models import MetricType

_log = logging.getLogger(__name__)

SPYGLASS_PACKAGE = "spyglass"


def _caller_function() -> str:
    """Walk the call stack and return the first function name outside of spyglass."""
    for frame_info in inspect.stack():
        module = frame_info.frame.f_globals.get("__name__", "")
        if not module.startswith(SPYGLASS_PACKAGE):
            return frame_info.function
    return "<unknown>"


class MetricsCollector:
    """Emits metrics to a running Spyglass server.

    Points are buffered and sent in one batch every ``flush_interval`` seconds from
    a background thread, so emitting never blocks on the network. Counters with the
    same name and tags are summed within a batch; gauges, timings and sets are sent
    point by point. Call ``flush()`` to send immediately.

    Stat names are automatically prefixed with ``{project}.{caller_function}``.
    Pass ``prefix=False`` to any emit method to send the stat name as-is.

    Args:
        host: Server address, e.g. ``"localhost:5013"`` or ``"http://localhost:5013"``.
        project: Project name (required). Used for stat prefixes and server routing.
        retention_days: How long to retain data on the server. Sent on registration.
        tags: Optional dict of tags merged into every emitted point.
        timeout: HTTP request timeout in seconds.
        flush_interval: Seconds between batched sends.

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
        flush_interval: float = DEFAULT_FLUSH_INTERVAL,
    ) -> None:
        if not project.strip():
            raise ValueError("project is required and must be non-empty")
        self._host = _normalize_host(host)
        self.project = project
        self._tags = tags or {}
        self._timeout = timeout
        self._session = create_session()
        self._batcher = Batcher(self._post_points, flush_interval=flush_interval)
        self._register(retention_days)

    def flush(self) -> None:
        """Send all buffered points now."""
        self._batcher.flush()

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

    def timed(self, stat: str, *, tags: dict | None = None, prefix: bool = True) -> "_Timer":
        """Measure elapsed time and emit a timing metric, as a context manager or a decorator.

        As a decorator the stat is prefixed with the decorated function's name, not the
        framework function that calls it.

        Args:
            stat: Stat name (will be prefixed unless ``prefix=False``).
            tags: Optional tags for this emit.
            prefix: Whether to auto-prefix with project and caller name.

        Example::

            with collector.timed("db_query"):
                run_query()

            @collector.timed("handler")
            def handle(): ...
        """
        return _Timer(self, stat, tags, prefix)

    def _build_name(self, caller: str, stat: str, prefix: bool) -> str:
        return f"{self.project}.{caller}.{stat}" if prefix else stat

    def _emit(
        self,
        metric_type: MetricType,
        stat: str,
        value: float,
        tags: dict | None,
        prefix: bool,
    ) -> None:
        caller = _caller_function()
        name = self._build_name(caller, stat, prefix)
        self._send_point(metric_type, name, value, tags)

    def _send_point(self, metric_type: MetricType, name: str, value: float, tags: dict | None) -> None:
        merged_tags = {**self._tags, **(tags or {})} or None
        point = {
            "name": name,
            "metric_type": metric_type.value,
            "value": value,
            "timestamp": datetime.now(UTC).isoformat(),
            **({"tags": merged_tags} if merged_tags else {}),
        }
        sum_key = None
        if metric_type == MetricType.COUNTER:
            sum_key = (name, json.dumps(merged_tags, sort_keys=True))
        self._batcher.add(point, sum_key=sum_key)

    def _post_points(self, points: list[dict]) -> None:
        try:
            self._session.post(
                f"{self._host}/metrics",
                json={"project": self.project, "points": points},
                timeout=self._timeout,
            )
        except requests.RequestException as exc:
            _log.debug("spyglass metric emit failed: %s", exc)

    def _register(self, retention_days: int) -> None:
        try:
            self._session.post(
                f"{self._host}/projects/register",
                json={"project": self.project, "retention_days": retention_days},
                timeout=self._timeout,
            )
        except requests.RequestException as exc:
            _log.debug("spyglass project registration failed: %s", exc)


class _Timer:
    def __init__(self, collector: MetricsCollector, stat: str, tags: dict | None, prefix: bool) -> None:
        self._collector = collector
        self._stat = stat
        self._tags = tags
        self._prefix = prefix
        self._caller = "<unknown>"
        self._start = 0.0

    def __enter__(self) -> None:
        self._caller = _caller_function()
        self._start = time.perf_counter()

    def __exit__(self, *exc_info: object) -> None:
        self._emit(self._caller, self._start)

    def __call__(self, func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            start = time.perf_counter()
            try:
                return func(*args, **kwargs)
            finally:
                self._emit(func.__name__, start)

        return wrapper

    def _emit(self, caller: str, start: float) -> None:
        elapsed_ms = (time.perf_counter() - start) * 1000
        name = self._collector._build_name(caller, self._stat, self._prefix)
        self._collector._send_point(MetricType.TIMING, name, elapsed_ms, self._tags)
