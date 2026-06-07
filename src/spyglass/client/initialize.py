"""Single entrypoint for instrumenting an application with Spyglass."""

import inspect
import logging

from spyglass.client.collector import SPYGLASS_PACKAGE
from spyglass.client.collector import MetricsCollector
from spyglass.client.logging import configure_logging


def _caller_logger_name() -> str:
    """Return the ``__name__`` of the first stack frame outside the spyglass package."""
    for frame_info in inspect.stack():
        module = frame_info.frame.f_globals.get("__name__", "")
        if not module.startswith(SPYGLASS_PACKAGE):
            return module
    return "__main__"


def initialize(
    host: str,
    project: str,
    *,
    level: int = logging.INFO,
    retention_days: int = 30,
    tags: dict | None = None,
    timeout: float = 2.0,
    logger_name: str | None = None,
) -> tuple[logging.Logger, MetricsCollector]:
    """Configure logging and metrics for the calling application.

    Sets up stdout + remote log shipping and returns a logger named like
    ``logging.getLogger(__name__)`` in the caller's module, plus a
    ``MetricsCollector`` for the same host and project.

    Args:
        host: Spyglass server address, e.g. ``"localhost:5013"``.
        project: Project name (required).
        level: Minimum log level for stdout and remote handlers.
        retention_days: Server retention window for this project.
        tags: Optional global metric tags.
        timeout: HTTP timeout in seconds.
        logger_name: Override the inferred caller module name for the logger.

    Returns:
        ``(logger, metrics_collector)`` ready to use in the calling module.

    Example::

        from spyglass import initialize

        logger, metrics = initialize(host="localhost:5013", project="my-api")
        logger.info("started")
        metrics.increment("requests")
    """
    configure_logging(host=host, project=project, level=level, timeout=timeout)
    collector = MetricsCollector(
        host=host,
        project=project,
        retention_days=retention_days,
        tags=tags,
        timeout=timeout,
    )
    logger = logging.getLogger(logger_name or _caller_logger_name())
    return logger, collector
