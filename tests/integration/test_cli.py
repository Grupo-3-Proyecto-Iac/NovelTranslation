from typer.testing import CliRunner

from noveltranslator.cli.commands import app
from noveltranslator.core.models import Chapter, Novel


def test_cli_help() -> None:
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "NovelTranslator" in result.stdout
    assert "source" in result.stdout


def test_access_check_rejects_invalid_url_without_network() -> None:
    result = CliRunner().invoke(app, ["access", "check", "file:///local.txt"])
    assert result.exit_code != 0
    assert "http" in result.output.lower()


def test_inspect_uses_registered_source_without_network(monkeypatch) -> None:
    class FakeManager:
        def close(self):
            pass

    class FakeSource:
        name = "Fake source"

        def can_handle(self, url):
            return True

        def get_novel(self, url):
            return Novel("fake", "Fixture Novel", "Author", "en", None, None, "fake", url)

        def get_chapters(self, novel):
            return [Chapter(1, "Chapter 1", "https://example.test/1")]

    class FakeRegistry:
        def resolve(self, url):
            return FakeSource()

    monkeypatch.setattr("noveltranslator.cli.commands.access_manager", lambda: FakeManager())
    monkeypatch.setattr("noveltranslator.cli.commands.default_registry", lambda manager: FakeRegistry())
    result = CliRunner().invoke(app, ["inspect", "https://example.test/novel"])
    assert result.exit_code == 0
    assert "Fixture Novel" in result.stdout
    assert "Found: 1" in result.stdout

