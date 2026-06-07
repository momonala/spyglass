import typer

from spyglass._config import CONFIG

PROJECT_NAME = CONFIG.project_name
PROJECT_VERSION = CONFIG.project_version
FLASK_PORT = CONFIG.port
DATA_DIR = CONFIG.data_dir
HOST = CONFIG.host
RETENTION_DAYS = CONFIG.retention_days


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

    if project_name:
        typer.echo(PROJECT_NAME)
    elif project_version:
        typer.echo(PROJECT_VERSION)
    elif flask_port:
        typer.echo(FLASK_PORT)
    elif data_dir:
        typer.echo(DATA_DIR)
    elif host:
        typer.echo(HOST)
    elif retention_days:
        typer.echo(RETENTION_DAYS)
    else:
        typer.secho(
            "Error: No config key specified. Use --help to see available options.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(1)


def main() -> None:
    typer.run(config_cli)


if __name__ == "__main__":
    main()
