"""Load non-secret server configuration from [tool.config] in pyproject.toml."""

import tomllib
from dataclasses import dataclass
from pathlib import Path

_PYPROJECT = Path(__file__).resolve().parent.parent.parent / "pyproject.toml"


@dataclass(frozen=True)
class SpyglassConfig:
    data_dir: str = "data"
    host: str = "0.0.0.0"
    port: int = 5013
    retention_days: int = 30


def load_config() -> SpyglassConfig:
    """Read [tool.config] from pyproject.toml and return a SpyglassConfig."""
    with _PYPROJECT.open("rb") as f:
        raw = tomllib.load(f)
    c = raw.get("tool", {}).get("config", {})
    return SpyglassConfig(
        data_dir=c.get("data_dir", "data"),
        host=c.get("host", "0.0.0.0"),
        port=int(c.get("port", 5013)),
        retention_days=int(c.get("retention_days", 30)),
    )


CONFIG = load_config()
