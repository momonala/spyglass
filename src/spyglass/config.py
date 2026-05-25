import tomllib
from pathlib import Path

import typer

_config_file = Path(__file__).parent.parent.parent / "pyproject.toml"
with _config_file.open("rb") as f:
    _config = tomllib.load(f)

_project_config = _config["project"]
_tool_config = _config["tool"]["config"]

PROJECT_NAME = _project_config["name"]
PROJECT_VERSION = _project_config["version"]
FLASK_PORT = _tool_config["port"]
DATA_DIR = _tool_config["data_dir"]
HOST = _tool_config["host"]
RETENTION_DAYS = _tool_config["retention_days"]


def config_cli(
    all: bool = typer.Option(False, "--all", help="Show all configuration values"),
    project_name: bool = typer.Option(False, "--project-name", help="Show project name"),
    project_version: bool = typer.Option(False, "--project-version", help="Show project version"),
    flask_port: bool = typer.Option(False, "--flask-port", help="Show Flask server port"),
    data_dir: bool = typer.Option(False, "--data-dir", help="Show data directory"),
    host: bool = typer.Option(False, "--host", help="Show host"),
    retention_days: bool = typer.Option(False, "--retention-days", help="Show retention days"),
) -> None:
    """Expose non-secret configuration defined in pyproject.toml.

    See docs/CONFIGURATION.md for details on adding new options.
    """
    if all:
        typer.echo(f"project_name={PROJECT_NAME}")
        typer.echo(f"project_version={PROJECT_VERSION}")
        typer.echo(f"flask_port={FLASK_PORT}")
        typer.echo(f"data_dir={DATA_DIR}")
        typer.echo(f"host={HOST}")
        typer.echo(f"retention_days={RETENTION_DAYS}")
        return

    param_map = {
        project_name: PROJECT_NAME,
        project_version: PROJECT_VERSION,
        flask_port: FLASK_PORT,
        data_dir: DATA_DIR,
        host: HOST,
        retention_days: RETENTION_DAYS,
    }

    for is_set, value in param_map.items():
        if is_set:
            typer.echo(value)
            return

    typer.secho(
        "Error: No config key specified. Use --help to see available options.",
        fg=typer.colors.RED,
        err=True,
    )
    raise typer.Exit(1)


def main():
    typer.run(config_cli)


if __name__ == "__main__":
    main()
