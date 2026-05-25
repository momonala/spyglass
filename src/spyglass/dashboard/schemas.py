"""Shared Pydantic schemas for the Spyglass dashboard API.

These types are importable by any app embedding Spyglass so it can build
its own typed dashboard without depending on spyglass.server internals.
"""

from pydantic import BaseModel


class PreparedLogEntry(BaseModel):
    """A cleaned, typed log record ready for the dashboard."""

    timestamp: str
    level: str
    logger_name: str
    message: str
    function: str | None = None
    extra: dict | None = None


class LogHistogram(BaseModel):
    """Per-bucket log counts grouped by level, aligned to a TimeWindow."""

    labels: list[str]
    counts: dict[str, list[int]]
    total: int


class WindowInfo(BaseModel):
    """Describes the query window resolved from user-supplied parameters."""

    amount: int
    unit: str
    hours: int
    rollup_minutes: int
