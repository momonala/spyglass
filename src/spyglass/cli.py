"""CLI entry point. Run `spyglass serve` to start the ingest and read server."""

import logging
from pathlib import Path

import typer

app = typer.Typer(help="Spyglass observability server.")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logging.getLogger("werkzeug").setLevel(logging.WARNING)


@app.command()
def serve(
    host: str = typer.Option(None, help="Bind host (default from [tool.config])"),
    port: int = typer.Option(None, help="Bind port (default from [tool.config])"),
) -> None:
    """Start the Spyglass ingest and read API server."""
    from spyglass._config import CONFIG
    from spyglass.db.store import ProjectStore
    from spyglass.server.app import create_app
    from spyglass.server.retention import start_retention_thread

    _host = host or CONFIG.host
    _port = port or CONFIG.port
    _data_dir = Path(CONFIG.data_dir)

    store = ProjectStore(_data_dir)
    start_retention_thread(store)

    flask_app = create_app(store)
    typer.echo(f"Spyglass listening on http://{_host}:{_port}")
    flask_app.run(host=_host, port=_port, debug=True)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
