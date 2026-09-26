from typer.testing import CliRunner

from noveltranslator.cli.commands import app


def test_cli_help() -> None:
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "NovelTranslator" in result.stdout
    assert "source" in result.stdout

