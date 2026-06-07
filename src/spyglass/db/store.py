"""Per-project database routing.

Each project gets its own subdirectory under data_dir/:
    data/{slug}/metrics.db  — MetricPoint rows
    data/{slug}/logs.db     — LogEntry rows
    data/{slug}/settings.json — per-project config (retention_days)

The engine cache is a plain dict; safe for ~10 projects in a single process.
"""

import json
import re
from pathlib import Path

from sqlalchemy import Engine
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from spyglass.db.models import LogsBase
from spyglass.db.models import MetricsBase

DEFAULT_RETENTION_DAYS = 30


def slugify(name: str) -> str:
    """Convert a project name to a safe filesystem slug.

    Args:
        name: Raw project name (e.g. "My API" or "worker/jobs").

    Returns:
        Lowercase, hyphen-separated slug suitable for a directory name.
    """
    slug = re.sub(r"[^a-z0-9-]", "-", name.lower())
    return re.sub(r"-+", "-", slug).strip("-")


class ProjectStore:
    """Manages per-project SQLite databases under a shared data directory."""

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir
        self._engines: dict[str, tuple[Engine, Engine]] = {}
        self._settings_cache: dict[str, dict] = {}

    def get_slug(self, project: str) -> str:
        """Resolve slug and lazily initialize the project's DB files."""
        slug = slugify(project)
        self._ensure_engines(slug)
        return slug

    def init_project(self, project: str, retention_days: int = DEFAULT_RETENTION_DAYS) -> str:
        """Ensure project dir, DBs, and settings.json exist. Returns slug.

        Args:
            project: Project name as sent by the client.
            retention_days: How many days of data to retain for this project.

        Raises:
            ValueError: If the slug for this project collides with an existing
                project registered under a different name.
        """
        slug = slugify(project)
        project_dir = self._data_dir / slug
        project_dir.mkdir(parents=True, exist_ok=True)

        settings_path = project_dir / "settings.json"
        if settings_path.exists():
            settings = json.loads(settings_path.read_text())
            existing_name = settings.get("project")
            if existing_name and existing_name != project:
                raise ValueError(
                    f"Project name {project!r} maps to slug {slug!r}, "
                    f"which is already registered as {existing_name!r}. "
                    "Choose a distinct project name."
                )
        else:
            settings = {"project": project}
        settings["retention_days"] = retention_days
        settings_path.write_text(json.dumps(settings, indent=2))
        self._settings_cache[slug] = settings

        self._ensure_engines(slug)
        return slug

    def get_retention_days(self, slug: str) -> int:
        """Read retention_days from the project's settings.json, or return the default."""
        if slug in self._settings_cache:
            return int(self._settings_cache[slug].get("retention_days", DEFAULT_RETENTION_DAYS))
        settings_path = self._data_dir / slug / "settings.json"
        if not settings_path.exists():
            return DEFAULT_RETENTION_DAYS
        settings = json.loads(settings_path.read_text())
        self._settings_cache[slug] = settings
        return int(settings.get("retention_days", DEFAULT_RETENTION_DAYS))

    def get_project_name(self, slug: str) -> str:
        """Return the human-readable project name for a slug, falling back to the slug."""
        if slug in self._settings_cache:
            return self._settings_cache[slug].get("project", slug)
        settings_path = self._data_dir / slug / "settings.json"
        if not settings_path.exists():
            return slug
        settings = json.loads(settings_path.read_text())
        self._settings_cache[slug] = settings
        return settings.get("project", slug)

    def metrics_session(self, slug: str) -> Session:
        """Return a new SQLAlchemy Session bound to this project's metrics.db."""
        metrics_engine, _ = self._ensure_engines(slug)
        return Session(metrics_engine)

    def logs_session(self, slug: str) -> Session:
        """Return a new SQLAlchemy Session bound to this project's logs.db."""
        _, logs_engine = self._ensure_engines(slug)
        return Session(logs_engine)

    def all_slugs(self) -> list[str]:
        """Return slugs of all initialized project directories."""
        if not self._data_dir.exists():
            return []
        return [d.name for d in self._data_dir.iterdir() if d.is_dir() and not d.name.startswith(".")]

    def project_dir(self, slug: str) -> Path:
        """Return the filesystem directory for a project slug."""
        return self._data_dir / slug

    def _ensure_engines(self, slug: str) -> tuple[Engine, Engine]:
        if slug not in self._engines:
            project_dir = self._data_dir / slug
            project_dir.mkdir(parents=True, exist_ok=True)

            metrics_engine = create_engine(f"sqlite:///{project_dir / 'metrics.db'}")
            logs_engine = create_engine(f"sqlite:///{project_dir / 'logs.db'}")

            MetricsBase.metadata.create_all(metrics_engine)
            LogsBase.metadata.create_all(logs_engine)

            self._engines[slug] = (metrics_engine, logs_engine)

        return self._engines[slug]
