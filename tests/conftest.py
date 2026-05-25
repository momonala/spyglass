"""Shared pytest fixtures for Spyglass tests."""

import pytest

from spyglass.db.store import ProjectStore
from spyglass.server.app import create_app


@pytest.fixture
def store(tmp_path):
    """A fresh ProjectStore backed by a temporary directory."""
    return ProjectStore(tmp_path / "data")


@pytest.fixture
def flask_app(store):
    """A Flask test app backed by the in-memory-equivalent temp store."""
    app = create_app(store)
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(flask_app):
    """Flask test client."""
    return flask_app.test_client()
