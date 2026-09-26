from abc import ABC, abstractmethod
from typing import Any, Protocol

from .models import Chapter, Novel


class NovelSource(Protocol):
    name: str

    def can_handle(self, url: str) -> bool: ...
    def get_novel(self, url: str) -> Novel: ...
    def get_chapters(self, novel: Novel) -> list[Chapter]: ...
    def get_chapter(self, chapter: Chapter) -> Chapter: ...


class Translator(Protocol):
    name: str

    def translate(self, text: str, context: dict[str, Any] | None = None) -> str: ...


class Exporter(Protocol):
    format_name: str

    def export(self, novel: Novel, destination: str) -> None: ...


class StorageRepository(Protocol):
    def save_json(self, relative_path: str, data: Any) -> None: ...
    def load_json(self, relative_path: str) -> Any: ...
    def exists(self, relative_path: str) -> bool: ...


class Analyzer(Protocol):
    def analyze(self, text: str) -> dict[str, Any]: ...


class NotImplementedComponent(ABC):
    """Base marker for future components intentionally outside Sprint 0."""

    @abstractmethod
    def execute(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

