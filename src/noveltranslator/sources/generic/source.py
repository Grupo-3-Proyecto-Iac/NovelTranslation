from noveltranslator.core.models import Chapter, Novel

from .config import GenericSourceConfig


class GenericSource:
    """Placeholder for selector-driven sources; no web access in Sprint 0."""

    def __init__(self, config: GenericSourceConfig) -> None:
        self.config = config
        self.name = config.name

    def can_handle(self, url: str) -> bool:
        return any(domain in url for domain in self.config.domains)

    def get_novel(self, url: str) -> Novel:
        raise NotImplementedError("Generic source acquisition is planned for a later sprint")

    def get_chapters(self, novel: Novel) -> list[Chapter]:
        raise NotImplementedError

    def get_chapter(self, chapter: Chapter) -> Chapter:
        raise NotImplementedError

