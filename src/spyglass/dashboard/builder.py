"""SummaryBuilder: turn raw Spyglass points + a config into a typed SummaryResponse."""

from datetime import datetime, timezone

from .aggregate import (
    DEFAULT_ROLLUP,
    DEFAULT_WINDOW_AMOUNT,
    TimeWindow,
    build_log_histogram,
    counter_series,
    counter_sum,
    latest_gauge,
    match_points,
    parse_metric_time,
    parse_rollup,
    parse_window_amount,
    parse_window_unit,
    prepare_logs,
    resolve_rollup_minutes,
    timing_p50_series,
    timing_summary,
    window_hours_from,
    compute_state_uptime,
)
from .config import ChartDefinition, MetricSelector, StateTransitionRule
from .schemas import ChartData, SummaryResponse, WindowInfo


class SummaryBuilder:
    """Aggregates raw Spyglass metric points into a generic SummaryResponse.

    Instantiate once with a fixed config; call build() per request.

    Args:
        selectors: Named metric selectors (suffix + optional type/tags).
        state_rules: Ordered rules mapping selectors to state labels.
        charts: Multi-series chart definitions referencing selector names.
        states: All possible state names (used to initialise uptime durations).
    """

    def __init__(
        self,
        selectors: dict[str, MetricSelector],
        state_rules: list[StateTransitionRule],
        charts: list[ChartDefinition],
        states: list[str],
    ) -> None:
        self._selectors = selectors
        self._state_rules = state_rules
        self._charts = charts
        self._states = states

    def build(
        self,
        metrics: list[dict],
        logs: list[dict],
        window_amount: int = DEFAULT_WINDOW_AMOUNT,
        window_unit: str = "hours",
        rollup: str = DEFAULT_ROLLUP,
        _now: datetime | None = None,
    ) -> SummaryResponse:
        now = _now or datetime.now(timezone.utc)
        amount = parse_window_amount(window_amount)
        unit = parse_window_unit(window_unit)
        rollup_val = parse_rollup(rollup)
        hours = window_hours_from(amount, unit)
        rollup_mins = resolve_rollup_minutes(rollup_val, hours)
        window = TimeWindow.from_hours(hours, now, rollup_mins)

        counters, timings, gauges = self._aggregate_selectors(metrics)
        state = self._compute_uptime(metrics, window.start, now)
        charts = self._compute_charts(metrics, window)

        prepared_logs = prepare_logs(logs)
        log_hist = build_log_histogram(prepared_logs, window)

        return SummaryResponse(
            generated_at=now.isoformat(),
            window=WindowInfo(amount=amount, unit=unit, hours=hours, rollup_minutes=rollup_mins),
            state=state,
            counters=counters,
            timings=timings,
            gauges=gauges,
            charts=charts,
            log_histogram=log_hist,
            logs=prepared_logs,
        )

    def _aggregate_selectors(
        self, metrics: list[dict]
    ) -> tuple[dict[str, float], dict, dict[str, float | None]]:
        counters: dict[str, float] = {}
        timings = {}
        gauges: dict[str, float | None] = {}
        for name, sel in self._selectors.items():
            tags = sel.tags or None
            if sel.metric_type == "counter":
                counters[name] = counter_sum(metrics, sel.suffix, tags=tags)
            elif sel.metric_type == "timing":
                timings[name] = timing_summary(metrics, sel.suffix, tags=tags)
            elif sel.metric_type == "gauge":
                gauges[name] = latest_gauge(metrics, sel.suffix)
        return counters, timings, gauges

    def _compute_uptime(
        self, metrics: list[dict], window_start: datetime, window_end: datetime
    ) -> "StateUptime | None":  # noqa: F821 — forward ref resolved at runtime
        if not self._state_rules:
            return None

        from .schemas import StateUptime as _StateUptime  # avoid circular at module level

        events: list[tuple[datetime, str]] = []
        for point in metrics:
            if point.get("metric_type") != "counter" or point["value"] <= 0:
                continue
            for rule in self._state_rules:
                sel = self._selectors[rule.selector_name]
                if not point["name"].endswith(sel.suffix):
                    continue
                if sel.tags and not all((point.get("tags") or {}).get(k) == v for k, v in sel.tags.items()):
                    continue
                ts = parse_metric_time(point["timestamp"])
                if window_start <= ts <= window_end:
                    events.append((ts, rule.state))
                break
        return compute_state_uptime(events, window_start, window_end, self._states)

    def _compute_charts(self, metrics: list[dict], window: TimeWindow) -> list[ChartData]:
        chart_data = []
        for chart_def in self._charts:
            series: dict[str, list[float | None]] = {}
            for s in chart_def.series:
                sel = self._selectors[s.selector_name]
                tags = sel.tags or None
                if s.metric_type == "counter":
                    series[s.label] = counter_series(metrics, sel.suffix, window, tags=tags)
                elif s.metric_type == "timing":
                    series[s.label] = timing_p50_series(metrics, sel.suffix, window, tags=tags)
            chart_data.append(ChartData(name=chart_def.name, labels=window.labels(), series=series))
        return chart_data
