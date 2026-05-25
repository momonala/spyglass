"""Tests for MetricsCollector stat naming and emit behavior."""

import pytest

from spyglass.client.collector import MetricsCollector
from spyglass.client.collector import _caller_function
from spyglass.client.collector import _normalize_host


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("localhost:5013", "http://localhost:5013"),
        ("http://localhost:5013", "http://localhost:5013"),
        ("https://example.com", "https://example.com"),
    ],
)
def test_normalize_host(raw, expected):
    assert _normalize_host(raw) == expected


def test_caller_function_returns_this_test_name():
    # The first non-spyglass frame is this test function.
    name = _caller_function()
    assert name == "test_caller_function_returns_this_test_name"


def _helper_that_calls_caller():
    return _caller_function()


def test_caller_function_skips_intermediate_helpers():
    # When an intermediate (non-spyglass) helper calls _caller_function,
    # the returned name is the helper itself since it's the first non-spyglass frame.
    name = _helper_that_calls_caller()
    assert name == "_helper_that_calls_caller"


def test_collector_requires_non_empty_project():
    with pytest.raises(ValueError, match="project is required"):
        MetricsCollector(host="localhost:19999", project="  ")


def test_collector_does_not_raise_when_server_unreachable():
    """Emit methods must never propagate exceptions to the caller."""
    from spyglass.client.collector import MetricsCollector

    collector = MetricsCollector(host="localhost:19999", project="test")
    collector.increment("counter")
    collector.decrement("counter")
    collector.gauge("memory", 512.0)
    collector.timing("latency", 10.5)
    collector.set("active_users", 1)


def test_timed_context_manager_does_not_raise_when_server_unreachable():
    from spyglass.client.collector import MetricsCollector

    collector = MetricsCollector(host="localhost:19999", project="test")
    with collector.timed("operation"):
        pass  # no exception should escape


def test_decrement_sends_negative_value(monkeypatch):
    from spyglass.client.collector import MetricsCollector

    sent = []

    collector = MetricsCollector(host="localhost:19999", project="test")
    monkeypatch.setattr(collector, "_send_point", lambda *a, **kw: sent.append(a))

    collector.decrement("requests", value=3)
    assert sent, "Expected _send_point to be called"
    from spyglass.db.models import MetricType

    metric_type, name, value, tags = sent[0]
    assert metric_type == MetricType.COUNTER
    assert value == -3


def test_prefix_false_sends_raw_stat(monkeypatch):
    from spyglass.client.collector import MetricsCollector

    sent = []

    collector = MetricsCollector(host="localhost:19999", project="myproject")
    monkeypatch.setattr(collector, "_send_point", lambda *a, **kw: sent.append(a))

    collector.increment("custom.full.name", prefix=False)
    _, name, *_ = sent[0]
    assert name == "custom.full.name"


def test_prefix_true_prepends_project_and_caller(monkeypatch):
    from spyglass.client.collector import MetricsCollector

    sent = []

    collector = MetricsCollector(host="localhost:19999", project="myproject")
    monkeypatch.setattr(collector, "_send_point", lambda *a, **kw: sent.append(a))

    collector.increment("requests")
    _, name, *_ = sent[0]
    # Format: {project}.{caller}.{stat}
    assert name.startswith("myproject.")
    assert name.endswith(".requests")
