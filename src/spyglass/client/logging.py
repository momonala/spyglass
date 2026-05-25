"""Spyglass logging integration.

configure_logging() wires up the root logger to emit records to both stdout
(via logging.basicConfig) and the Spyglass server (via SpyglassHandler).
"""

import logging
from datetime import datetime
from datetime import timezone

from spyglass.client.http_client import create_session
from spyglass.client.http_client import silence_client_transport_loggers


def _normalize_host(host: str) -> str:
    if host.startswith(("http://", "https://")):
        return host
    return f"http://{host}"


def _extract_extra(record: logging.LogRecord) -> dict | None:
    """Pull non-standard fields off a LogRecord into a dict for remote storage."""
    standard_fields = {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "message",
    }
    extra = {k: v for k, v in record.__dict__.items() if k not in standard_fields}
    return extra or None


class SpyglassHandler(logging.Handler):
    """Logging handler that POSTs log records to the Spyglass server.

    Failures are silent so the host application's logging output stays clean.

    Args:
        host: Server address (normalized to http:// if no scheme given).
        project: Project name to tag log entries with.
        timeout: HTTP request timeout in seconds.
    """

    def __init__(self, host: str, project: str, timeout: float = 2.0) -> None:
        super().__init__()
        self._host = _normalize_host(host)
        self._project = project
        self._timeout = timeout
        self._session = create_session()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            ts = datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat()
            payload = {
                "project": self._project,
                "entries": [
                    {
                        "timestamp": ts,
                        "level": record.levelname,
                        "logger_name": record.name,
                        "message": self.format(record),
                        "extra": _extract_extra(record),
                    }
                ],
            }
            self._session.post(f"{self._host}/logs", json=payload, timeout=self._timeout)
        except Exception as exc:
            logging.getLogger(__name__).debug("spyglass log emit failed: %s", exc)

    def handleError(self, record: logging.LogRecord) -> None:
        """Do not print tracebacks when remote ingest fails."""


def configure_logging(
    host: str,
    project: str,
    level: int = logging.INFO,
    timeout: float = 2.0,
) -> None:
    """Configure logging to write to stdout and the Spyglass server.

    Calls ``logging.basicConfig`` (no-op if the root logger already has handlers)
    then attaches a ``SpyglassHandler`` so every log record is also sent remotely.

    Args:
        host: Spyglass server address, e.g. ``"localhost:5013"``.
        project: Project name for remote log storage.
        level: Minimum log level for both stdout and remote handlers.
        timeout: HTTP timeout for the remote handler in seconds.

    Example::

        from spyglass import configure_logging
        configure_logging(host="localhost:5013", project="my-api")
        logger = logging.getLogger(__name__)
        logger.info("Server started")
    """
    def_log_format = "%(asctime)s %(levelname)s [%(funcName)s] %(name)s %(message)s"

    silence_client_transport_loggers()
    logging.basicConfig(level=level, format=def_log_format)

    handler = SpyglassHandler(host=host, project=project, timeout=timeout)
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(def_log_format))
    logging.getLogger().addHandler(handler)
