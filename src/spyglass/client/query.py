"""Read-only HTTP client for querying a running Spyglass server."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import requests

_log = logging.getLogger(__name__)

_DEFAULT_LIMIT = 5000
_DEFAULT_TIMEOUT = 5.0


def _normalize_host(host: str) -> str:
    if host.startswith(("http://", "https://")):
        return host
    return f"http://{host}"


def _iso(dt: datetime) -> str:
    """Convert a datetime to a UTC ISO-8601 string the server accepts."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") + "Z"


class SpyglassQueryClient:
    """Thin HTTP client for the Spyglass read API.

    Args:
        host: Spyglass server address, e.g. ``"localhost:5013"`` or
              ``"http://localhost:5013"``.
        project: Project name to scope all queries to.
        timeout: Request timeout in seconds.
        limit: Default row limit for metric/log queries.
    """

    def __init__(
        self,
        host: str,
        project: str,
        timeout: float = _DEFAULT_TIMEOUT,
        limit: int = _DEFAULT_LIMIT,
    ) -> None:
        self._host = _normalize_host(host)
        self.project = project
        self._timeout = timeout
        self._limit = limit
        self._session = requests.Session()

    def status(self) -> dict | None:
        """GET /status — returns the server status dict, or None if unreachable."""
        try:
            resp = self._session.get(f"{self._host}/status", timeout=self._timeout)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            _log.debug("spyglass status check failed: %s", exc)
            return None

    def fetch_metrics(
        self,
        since: datetime,
        *,
        limit: int | None = None,
    ) -> list[dict]:
        """GET /metrics — return all points for this project since *since*.

        Returns an empty list if the server is unreachable or returns an error.
        """
        params = {
            "project": self.project,
            "from": _iso(since),
            "limit": limit if limit is not None else self._limit,
        }
        try:
            resp = self._session.get(
                f"{self._host}/metrics", params=params, timeout=self._timeout
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            _log.debug("spyglass fetch_metrics failed: %s", exc)
            return []

    def fetch_logs(
        self,
        since: datetime,
        *,
        limit: int | None = None,
    ) -> list[dict]:
        """GET /logs — return all log entries for this project since *since*.

        Returns an empty list if the server is unreachable or returns an error.
        """
        params = {
            "project": self.project,
            "from": _iso(since),
            "limit": limit if limit is not None else self._limit,
        }
        try:
            resp = self._session.get(
                f"{self._host}/logs", params=params, timeout=self._timeout
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            _log.debug("spyglass fetch_logs failed: %s", exc)
            return []
