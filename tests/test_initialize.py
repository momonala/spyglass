"""Tests for spyglass.initialize."""

import logging

from spyglass import initialize
from spyglass.client.logging import SpyglassHandler


def test_initialize_names_logger_after_calling_module(posts):
    root = logging.getLogger()
    handlers_before = list(root.handlers)
    try:
        logger, collector = initialize(host="localhost:19999", project="test-proj")
    finally:
        for handler in list(root.handlers):
            if handler not in handlers_before and isinstance(handler, SpyglassHandler):
                root.removeHandler(handler)

    assert logger.name == __name__
    assert collector.project == "test-proj"
