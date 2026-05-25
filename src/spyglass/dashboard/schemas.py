"""Shared Pydantic schemas for the Spyglass dashboard library.

Importable by any app that embeds Spyglass to build its own typed dashboard
without depending on spyglass.server internals.
"""

from pydantic import BaseModel


class PreparedLogEntry(BaseModel):
    timestamp: str
    level: str
    logger_name: str
    message: str
    function: str | None = None
    extra: dict | None = None


class TimingSummary(BaseModel):
    count: int
    p50: float | None
    p95: float | None
    max: float | None


class StateUptime(BaseModel):
    current: str
    event_count: int
    seconds: dict[str, float]
    pcts: dict[str, float]


class LogHistogram(BaseModel):
    labels: list[str]
    by_level: dict[str, list[int]]
    total: int


class WindowInfo(BaseModel):
    amount: int
    unit: str
    hours: int
    rollup_minutes: int


class ChartData(BaseModel):
    name: str
    labels: list[str]
    series: dict[str, list[float | None]]


class SummaryResponse(BaseModel):
    generated_at: str
    window: WindowInfo
    state: StateUptime | None
    counters: dict[str, float]
    timings: dict[str, TimingSummary]
    gauges: dict[str, float | None]
    charts: list[ChartData]
    log_histogram: LogHistogram | None
    logs: list[PreparedLogEntry]
