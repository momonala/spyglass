"""Quiet HTTP client for the Spyglass SDK.

Instrumented apps should not emit Spyglass or HTTP-library log noise; only the
host application's logs should appear in normal logging output.
"""

import logging

import requests


def _normalize_host(host: str) -> str:
    if host.startswith(("http://", "https://")):
        return host
    return f"http://{host}"

_HTTP_LOGGER_NAMES = (
    "urllib3",
    "urllib3.connectionpool",
    "requests",
    "httpcore",
    "httpx",
)

_SPYGLASS_CLIENT_LOGGER_NAMES = (
    "spyglass.client",
    "spyglass.client.collector",
    "spyglass.client.logging",
    "spyglass.client.http_client",
)


def silence_client_transport_loggers() -> None:
    """Disable HTTP stack and spyglass.client log output in instrumented apps."""
    for name in _HTTP_LOGGER_NAMES + _SPYGLASS_CLIENT_LOGGER_NAMES:
        logging.getLogger(name).disabled = True


def create_session() -> requests.Session:
    """Return a requests session after silencing transport-related loggers."""
    silence_client_transport_loggers()
    return requests.Session()
