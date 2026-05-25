"""Config types for SummaryBuilder: declare what metrics mean, get typed summaries back."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class MetricSelector:
    """Matches metric points by name suffix, optional type, and optional tags."""

    suffix: str
    metric_type: str | None = None
    tags: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class StateTransitionRule:
    """Maps a named selector to a state label for uptime calculation."""

    selector_name: str  # key in SummaryBuilder.selectors
    state: str  # e.g. "healthy", "stale", "degraded"


@dataclass(frozen=True)
class ChartSeries:
    """One data series within a multi-series chart."""

    label: str
    selector_name: str  # key in SummaryBuilder.selectors
    metric_type: str = "counter"


@dataclass(frozen=True)
class ChartDefinition:
    """A named multi-series chart binding."""

    name: str
    series: list[ChartSeries]
    chart_type: str = "line"
