import logging
from dataclasses import replace
from pathlib import Path

from noveltranslator.application.events import ProgressCallback, ProgressEvent, emit_progress
from noveltranslator.core.exceptions import ExportError
from noveltranslator.exporters import ChapterAssembler, EpubExporter, ExportBook, ExportRequest, ExportResult, ExporterRegistry, HtmlExporter, JsonExporter, TxtExporter
from noveltranslator.storage.identifiers import slugify
from noveltranslator.storage.repository import NovelRepository
from noveltranslator.storage.serialization import utc_now_iso

logger = logging.getLogger("noveltranslator.application.export")


class ExportService:
    def __init__(self, repository: NovelRepository, registry: ExporterRegistry | None = None, *, progress_callback: ProgressCallback | None = None) -> None:
        self.repository = repository
        self.registry = registry or self.default_registry()
        self.assembler = ChapterAssembler(repository)
        self.progress_callback = progress_callback

    @staticmethod
    def default_registry() -> ExporterRegistry:
        registry = ExporterRegistry()
        for exporter in (TxtExporter(), JsonExporter(), HtmlExporter(), EpubExporter()):
            registry.register(exporter)
        return registry

    def export_novel(self, novel_id: str, *, format_id: str, translation_id: str = "default", destination: str | Path | None = None, include_warnings: bool = False, only_validated: bool = True, allow_partial: bool = False, overwrite: bool = False, from_chapter: int | None = None, to_chapter: int | None = None) -> ExportResult:
        metadata = self.repository.load_novel_metadata(novel_id)
        target_language = "es"
        chapter_numbers = self.repository.list_chapters(novel_id)
        selected = [number for number in chapter_numbers if (from_chapter is None or number >= from_chapter) and (to_chapter is None or number <= to_chapter)]
        emit_progress(self.progress_callback, ProgressEvent("export", "stage_started", novel_id, total=len(selected), message=f"Preparando exportación {format_id.upper()}"))
        chapters = []
        warnings: list[str] = []
        skipped = 0
        for number in selected:
            validation = self.repository.load_validation_result(novel_id, number, translation_id) if self.repository.validation_exists(novel_id, number, translation_id) else None
            validation_status = validation.get("status") if validation else None
            if validation_status == "FAILED":
                warnings.append(f"Chapter {number} skipped: validation failed.")
                skipped += 1
                emit_progress(self.progress_callback, ProgressEvent("export", "item_skipped", novel_id, number, skipped, len(selected), f"Capítulo {number:03d} omitido: validación fallida"))
                continue
            if only_validated and validation_status is None:
                warnings.append(f"Chapter {number} skipped: validation result is missing.")
                skipped += 1
                emit_progress(self.progress_callback, ProgressEvent("export", "item_skipped", novel_id, number, skipped, len(selected), f"Capítulo {number:03d} omitido: falta validación"))
                continue
            if validation_status == "WARNING" and not include_warnings:
                warnings.append(f"Chapter {number} skipped: validation has warnings.")
                skipped += 1
                emit_progress(self.progress_callback, ProgressEvent("export", "item_skipped", novel_id, number, skipped, len(selected), f"Capítulo {number:03d} omitido: tiene avisos"))
                continue
            try:
                chapters.append(self.assembler.assemble_chapter(novel_id, number, translation_id, allow_partial=allow_partial, validation_status=validation_status or "UNVALIDATED"))
                emit_progress(self.progress_callback, ProgressEvent("export", "item_completed", novel_id, number, len(chapters) + skipped, len(selected), f"Capítulo {number:03d} preparado para exportar"))
            except ExportError as error:
                warnings.append(str(error))
                skipped += 1
                emit_progress(self.progress_callback, ProgressEvent("export", "item_skipped", novel_id, number, len(chapters) + skipped, len(selected), f"Capítulo {number:03d} omitido: {error}"))
        if not chapters:
            raise ExportError("No chapters are eligible for export.")
        cover_path = self._local_cover(metadata, novel_id)
        display_title = metadata.get("translated_title") if target_language.casefold() == "es" else None
        book = ExportBook(novel_id, str(display_title or metadata.get("title", novel_id)), metadata.get("author"), str(metadata.get("language", "en")), target_language, translation_id, metadata.get("source"), tuple(chapters), cover_path)
        output = Path(destination) if destination else self._default_destination(novel_id, book.title, target_language, translation_id, format_id)
        request = ExportRequest(novel_id, translation_id, output, include_warnings, only_validated, allow_partial, overwrite, from_chapter, to_chapter)
        logger.info("Export started: %s (%s)", novel_id, format_id)
        result = self.registry.resolve(format_id).export(request, book)
        result = replace(result, chapters_skipped=skipped, warnings=warnings, created_at=utc_now_iso())
        logger.info("Export completed: %s", result.output_path)
        emit_progress(self.progress_callback, ProgressEvent("export", "stage_completed", novel_id, current=len(chapters) + skipped, total=len(selected), message=f"Exportado a {result.output_path}"))
        return result

    def _default_destination(self, novel_id: str, title: str, target_language: str, translation_id: str, format_id: str) -> Path:
        return self.repository.root / novel_id / "exports" / f"{slugify(title)}.{slugify(target_language, 10)}.{slugify(translation_id, 30)}.{format_id.casefold()}"

    def _local_cover(self, metadata: dict, novel_id: str) -> Path | None:
        for key in ("cover_path", "cover_file", "cover_local_path"):
            value = metadata.get(key)
            if not value:
                continue
            candidate = Path(value)
            if not candidate.is_absolute():
                candidate = self.repository.root / novel_id / candidate
            if candidate.is_file():
                return candidate
        return None
