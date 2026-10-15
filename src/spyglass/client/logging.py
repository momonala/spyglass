"""Spyglass logging integration.

configure_logging() wires up the root logger to emit records to both stdout
(via logging.basicConfig) and the Spyglass server (via SpyglassHandler).
"""

import logging
from datetime import datetime
from datetime import timezone

import requests

from spyglass.client.batching import DEFAULT_FLUSH_INTERVAL
from spyglass.client.batching import Batcher
from spyglass.client.http_client import _normalize_host
from spyglass.client.http_client import create_session
from spyglass.client.http_client import silence_client_transport_loggers


class SpyglassHandler(logging.Handler):
    """Logging handler that POSTs log records to the Spyglass server.

    Records are buffered and sent in one batch every ``flush_interval`` seconds
    from a background thread. Failures are silent so the host application's logging output stays clean.

    Args:
        host: Server address (normalized to http:// if no scheme given).
        project: Project name to tag log entries with.
        timeout: HTTP request timeout in seconds.
        flush_interval: Seconds between batched sends.
    """

    def __init__(
        self,
        host: str,
        project: str,
        timeout: float = 2.0,
        flush_interval: float = DEFAULT_FLUSH_INTERVAL,
    ) -> None:
        super().__init__()
        self._host = _normalize_host(host)
        self._project = project
        self._timeout = timeout
        self._session = create_session()
        self._batcher = Batcher(self._post_entries, flush_interval=flush_interval)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            entry = {
                "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
                "level": record.levelname,
                "logger_name": record.name,
                "message": self.format(record),
            }
        except Exception:  # noqa: BLE001 - a bad record must not break the app's logging
            return
        self._batcher.add(entry)

    def flush(self) -> None:
        """Send all buffered records now. Also called by ``logging.shutdown`` at exit."""
        self._batcher.flush()

    def _post_entries(self, entries: list[dict]) -> None:
        try:
            self._session.post(
                f"{self._host}/logs",
                json={"project": self._project, "entries": entries},
                timeout=self._timeout,
            )
        except requests.RequestException as exc:
            logging.getLogger(__name__).debug("spyglass log emit failed: %s", exc)

    def handleError(self, record: logging.LogRecord) -> None:
        """Do not print tracebacks when remote ingest fails."""


def configure_logging(
    host: str,
    project: str,
    level: int = logging.INFO,
    timeout: float = 2.0,
    flush_interval: float = DEFAULT_FLUSH_INTERVAL,
) -> None:
    """Configure logging to write to stdout and the Spyglass server.

    Calls ``logging.basicConfig`` (no-op if the root logger already has handlers)
    then attaches a ``SpyglassHandler`` so every log record is also sent remotely.

    Args:
        host: Spyglass server address, e.g. ``"localhost:5013"``.
        project: Project name for remote log storage.
        level: Minimum log level for both stdout and remote handlers.
        timeout: HTTP timeout for the remote handler in seconds.
        flush_interval: Seconds between batched sends to the server.

    Example::

        from spyglass import configure_logging
        configure_logging(host="localhost:5013", project="my-api")
        logger = logging.getLogger(__name__)
        logger.info("Server started")
    """
    def_log_format = "%(asctime)s %(levelname)s [%(funcName)s] %(name)s %(message)s"

    silence_client_transport_loggers()
    logging.basicConfig(level=level, format=def_log_format)

    handler = SpyglassHandler(host=host, project=project, timeout=timeout, flush_interval=flush_interval)
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(def_log_format))
    logging.getLogger().addHandler(handler)
