"""Tests for client-side batching of metrics and logs."""

import json
import logging
import os
import time

import pytest

from spyglass.client.batching import Batcher
from spyglass.client.collector import MetricsCollector
from spyglass.client.logging import SpyglassHandler


class _FakeResponse:
    status_code = 201


@pytest.fixture
def posts(monkeypatch):
    sent: list[tuple[str, dict]] = []

    def _fake_post(self, url, json=None, timeout=None):
        sent.append((url, json))
        return _FakeResponse()

    monkeypatch.setattr("requests.Session.post", _fake_post)
    return sent


def _tags_key(point):
    return json.dumps(point["tags"], sort_keys=True) if "tags" in point else None


def _metric_posts(posts):
    return [body for url, body in posts if url.endswith("/metrics")]


def test_emitting_does_not_post_until_flush(posts):
    collector = MetricsCollector(host="localhost:19999", project="test")
    collector.increment("hits", prefix=False)
    collector.timing("latency", 5.0, prefix=False)

    assert _metric_posts(posts) == []

    collector.flush()

    assert len(_metric_posts(posts)) == 1


def test_counters_with_same_name_and_tags_are_summed(posts):
    collector = MetricsCollector(host="localhost:19999", project="test")
    for _ in range(3):
        collector.increment("hits", prefix=False)
    collector.increment("hits", 2, prefix=False, tags={"route": "/a"})
    collector.decrement("hits", prefix=False)

    collector.flush()

    points = _metric_posts(posts)[0]["points"]
    totals = {_tags_key(p): p["value"] for p in points}
    assert totals == {None: 2, '{"route": "/a"}': 2}


def test_timings_gauges_and_sets_are_sent_point_by_point(posts):
    collector = MetricsCollector(host="localhost:19999", project="test")
    collector.timing("latency", 5.0, prefix=False)
    collector.timing("latency", 7.0, prefix=False)
    collector.gauge("depth", 1, prefix=False)
    collector.gauge("depth", 2, prefix=False)
    collector.set("users", 1, prefix=False)

    collector.flush()

    points = _metric_posts(posts)[0]["points"]
    assert [(p["name"], p["value"]) for p in points] == [
        ("latency", 5.0),
        ("latency", 7.0),
        ("depth", 1),
        ("depth", 2),
        ("users", 1),
    ]


def test_flush_with_nothing_buffered_sends_nothing(posts):
    collector = MetricsCollector(host="localhost:19999", project="test")

    collector.flush()

    assert _metric_posts(posts) == []


def test_batcher_drops_oldest_items_past_the_cap():
    sent: list[list[dict]] = []
    batcher = Batcher(sent.append, max_pending=3)
    for i in range(5):
        batcher.add({"value": i})

    batcher.flush()

    assert [item["value"] for item in sent[0]] == [2, 3, 4]


def test_batcher_flushes_in_the_background():
    sent: list[list[dict]] = []
    batcher = Batcher(sent.append, flush_interval=0.05)
    batcher.add({"value": 1})

    for _ in range(100):
        if sent:
            break
        time.sleep(0.01)

    assert sent == [[{"value": 1}]]


@pytest.mark.skipif(not hasattr(os, "fork"), reason="needs os.fork")
def test_forked_child_starts_with_an_empty_buffer():
    batcher = Batcher(lambda batch: None)
    batcher.add({"value": 1})

    pid = os.fork()
    if pid == 0:
        os._exit(0 if batcher.pending_count() == 0 else 1)
    _, status = os.waitpid(pid, 0)

    assert os.waitstatus_to_exitcode(status) == 0
    assert batcher.pending_count() == 1


def test_log_handler_sends_records_in_one_batch(posts):
    handler = SpyglassHandler(host="localhost:19999", project="test")
    logger = logging.getLogger("test_batching.handler")
    logger.propagate = False
    logger.addHandler(handler)
    try:
        for i in range(3):
            logger.warning("message %d", i)
        assert [u for u, _ in posts if u.endswith("/logs")] == []

        handler.flush()
    finally:
        logger.removeHandler(handler)

    log_posts = [body for url, body in posts if url.endswith("/logs")]
    assert len(log_posts) == 1
    assert [e["message"] for e in log_posts[0]["entries"]] == ["message 0", "message 1", "message 2"]
