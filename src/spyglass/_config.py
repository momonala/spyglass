"""Load non-secret server configuration from [tool.config] in pyproject.toml."""

import tomllib
from dataclasses import dataclass
from dataclasses import fields as dataclass_fields
from pathlib import Path

_PYPROJECT = Path(__file__).resolve().parent.parent.parent / "pyproject.toml"


@dataclass(frozen=True)
class SpyglassConfig:
    data_dir: str = "data"
    host: str = "0.0.0.0"
    port: int = 5013
    retention_days: int = 30
    project_name: str = ""
    project_version: str = ""


def load_config() -> SpyglassConfig:
    """Read [tool.config] from pyproject.toml and return a SpyglassConfig."""
    with _PYPROJECT.open("rb") as f:
        raw = tomllib.load(f)
    c = raw.get("tool", {}).get("config", {})
    p = raw.get("project", {})
    field_names = {f.name for f in dataclass_fields(SpyglassConfig)}
    return SpyglassConfig(
        **{k: v for k, v in c.items() if k in field_names},
        project_name=p.get("name", ""),
        project_version=p.get("version", ""),
    )


CONFIG = load_config()
