from typer.testing import CliRunner

from noveltranslator.cli.commands import app


def test_cli_help() -> None:
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "NovelTranslator" in result.stdout
    assert "source" in result.stdout


def test_access_check_rejects_invalid_url_without_network() -> None:
    result = CliRunner().invoke(app, ["access", "check", "file:///local.txt"])
    assert result.exit_code != 0
    assert "http" in result.output.lower()

