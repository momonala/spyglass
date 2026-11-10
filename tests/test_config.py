"""Tests for the config CLI that install/install.sh reads the service name and settings from."""

import typer
from typer.testing import CliRunner

from spyglass.config import config_cli

app = typer.Typer()
app.command()(config_cli)

runner = CliRunner()


def test_config_returns_single_value():
    result = runner.invoke(app, ["--project-name"])

    assert result.exit_code == 0
    assert result.stdout.strip() == "spyglass"


def test_config_all_returns_all_values():
    result = runner.invoke(app, ["--all"])

    assert result.exit_code == 0
    assert "project_name=spyglass" in result.stdout
    assert "project_version=0.1.0" in result.stdout
