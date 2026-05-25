"""Tests for spyglass.initialize."""

from spyglass import initialize
from spyglass.client.collector import MetricsCollector


def test_initialize_returns_logger_and_collector():
    logger, collector = initialize(host="localhost:19999", project="test-proj")
    assert logger.name == __name__
    assert isinstance(collector, MetricsCollector)
    assert collector.project == "test-proj"


def test_initialize_respects_logger_name_override():
    logger, _ = initialize(host="localhost:19999", project="p", logger_name="custom.logger")
    assert logger.name == "custom.logger"
