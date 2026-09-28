from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from noveltranslator.core.enums import ProcessingState
from noveltranslator.core.exceptions import ChapterNotFoundError
from noveltranslator.sources.lorenovels.parser import parse_chapter_content, parse_chapter_title
from noveltranslator.storage.repository import NovelRepository
from noveltranslator.processing.normalizer import TextNormalizer


@dataclass(frozen=True)
class HtmlImportSummary:
    novel_id: str
    imported: int
    skipped: int
    failed: int
    total_files: int


class HtmlImportService:
    """Imports previously captured HTML into persisted chapter sources."""

    def __init__(self, repository: NovelRepository) -> None:
        self.repository = repository

    def import_directory(
        self,
        novel_id: str,
        directory: str | Path,
        *,
        force: bool = False,
    ) -> HtmlImportSummary:
        root = Path(directory).resolve()
        if not root.is_dir():
            raise FileNotFoundError(f"HTML directory not found: {root}")
        metadata = self.repository.load_novel_metadata(novel_id)
        language = str(metadata.get("language", "en"))
        files = sorted((path for path in root.glob("*.html") if path.stem.isdigit()), key=lambda path: int(path.stem))
        imported = skipped = failed = 0
        for path in files:
            number = int(path.stem)
            try:
                chapter_metadata = self.repository.load_chapter_metadata(novel_id, number)
            except ChapterNotFoundError:
                failed += 1
                print(f"HTML fallido: capítulo {number:03d} no existe en metadata local")
                continue
            if self.repository.source_exists(novel_id, number) and not force:
                skipped += 1
                print(f"HTML omitido: capítulo {number:03d} ya tiene source.json")
                continue
            try:
                html = path.read_text(encoding="utf-8")
                paragraphs = TextNormalizer().normalize(parse_chapter_content(html))
                title = parse_chapter_title(html) or chapter_metadata.get("title", f"Chapter {number}")
                self.repository.save_source(novel_id, number, language, paragraphs)
                self.repository.save_chapter_metadata(
                    novel_id,
                    number,
                    {
                        "title": title,
                        "status": ProcessingState.DOWNLOADED.value,
                        "error_type": None,
                        "error_message": None,
                        "imported_from_html": str(path),
                    },
                )
                imported += 1
                print(f"HTML importado: capítulo {number:03d} ({len(paragraphs)} párrafos)")
            except Exception as error:
                failed += 1
                print(f"HTML fallido: capítulo {number:03d} ({type(error).__name__}: {error})")
        return HtmlImportSummary(novel_id, imported, skipped, failed, len(files))
