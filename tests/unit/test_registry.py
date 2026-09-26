import pytest

from noveltranslator.core.exceptions import SourceNotFoundError
from noveltranslator.sources.registry import SourceRegistry


class FakeSource:
    name = "fake"

    def can_handle(self, url: str) -> bool:
        return url.startswith("https://example.test/")


def test_registry_registers_and_resolves_source() -> None:
    registry = SourceRegistry()
    source = FakeSource()
    registry.register(source)
    assert registry.resolve("https://example.test/novel") is source


def test_registry_rejects_unknown_url() -> None:
    with pytest.raises(SourceNotFoundError):
        SourceRegistry().resolve("https://unknown.test/novel")

