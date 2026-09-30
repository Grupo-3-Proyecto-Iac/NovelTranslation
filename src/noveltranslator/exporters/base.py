from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class ExportRequest:
    novel_id: str
    translation_id: str
    destination: Path
    include_warnings: bool = False
    only_validated: bool = True
    allow_partial: bool = False
    overwrite: bool = False
    from_chapter: int | None = None
    to_chapter: int | None = None


@dataclass(frozen=True)
class ExportChapter:
    number: int
    title: str
    text: str
    paragraphs: tuple[str, ...] = ()
    validation_status: str = "OK"


def chapter_heading(chapter: ExportChapter) -> str:
    """Return a Spanish display heading without changing the source chapter title."""
    if chapter.number == 0:
        return chapter.title or "Prólogo"
    return f"Capítulo {chapter.number} — {chapter.title}"


@dataclass(frozen=True)
class ExportBook:
    novel_id: str
    title: str
    author: str | None
    source_language: str
    target_language: str
    translation_id: str
    source: str | None
    chapters: tuple[ExportChapter, ...] = ()
    cover_path: Path | None = None


@dataclass(frozen=True)
class ExportResult:
    output_path: Path
    format: str
    chapters_exported: int
    chapters_skipped: int
    warnings: list[str] = field(default_factory=list)
    created_at: str = ""


class Exporter(Protocol):
    @property
    def format_id(self) -> str: ...

    def export(self, request: ExportRequest, book: ExportBook) -> ExportResult: ...
