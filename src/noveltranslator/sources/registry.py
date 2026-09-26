from noveltranslator.core.exceptions import SourceNotFoundError
from noveltranslator.core.interfaces import NovelSource


class SourceRegistry:
    def __init__(self) -> None:
        self._sources: list[NovelSource] = []

    def register(self, source: NovelSource) -> None:
        if source not in self._sources:
            self._sources.append(source)

    def list(self) -> tuple[NovelSource, ...]:
        return tuple(self._sources)

    def resolve(self, url: str) -> NovelSource:
        for source in self._sources:
            if source.can_handle(url):
                return source
        raise SourceNotFoundError(f"No registered source can handle URL: {url}")

