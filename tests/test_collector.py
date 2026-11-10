"""Tests for MetricsCollector stat naming and fire-and-forget delivery."""

import pytest
import requests

from spyglass.client.collector import MetricsCollector
from spyglass.client.http_client import _normalize_host


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("localhost:5013", "http://localhost:5013"),
        ("https://example.com", "https://example.com"),
    ],
)
def test_normalize_host(raw, expected):
    assert _normalize_host(raw) == expected


def _sent_names(collector, posts):
    collector.flush()
    return [p["name"] for url, body in posts if url.endswith("/metrics") for p in body["points"]]


def test_collector_requires_non_empty_project():
    with pytest.raises(ValueError, match="project is required"):
        MetricsCollector(host="localhost:19999", project="  ")


def test_delivery_failures_never_reach_the_caller(monkeypatch):
    def _refuse(self, url, json=None, timeout=None):
        raise requests.ConnectionError("server down")

    monkeypatch.setattr("requests.Session.post", _refuse)

    collector = MetricsCollector(host="localhost:19999", project="test")
    collector.increment("counter")
    collector.flush()


def test_prefix_prepends_project_and_calling_function(posts):
    collector = MetricsCollector(host="localhost:19999", project="myproject")

    collector.increment("requests")

    assert _sent_names(collector, posts) == [
        "myproject.test_prefix_prepends_project_and_calling_function.requests"
    ]


def test_timed_context_manager_names_after_enclosing_function(posts):
    collector = MetricsCollector(host="localhost:19999", project="p")

    with collector.timed("op"):
        pass

    assert _sent_names(collector, posts) == ["p.test_timed_context_manager_names_after_enclosing_function.op"]


def test_timed_decorator_names_after_decorated_function(posts):
    collector = MetricsCollector(host="localhost:19999", project="p")

    @collector.timed("op")
    def handler():
        return 42

    def framework_dispatch():
        return handler()

    assert framework_dispatch() == 42
    assert _sent_names(collector, posts) == ["p.handler.op"]
