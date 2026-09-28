import logging
from dataclasses import dataclass
from typing import Iterable

from noveltranslator.core.enums import ProcessingState
from noveltranslator.core.exceptions import CorruptedDataError, NovelNotFoundError
from noveltranslator.core.models import Chapter, Novel
from noveltranslator.application.events import ProgressCallback, ProgressEvent, emit_progress
from noveltranslator.sources.registry import SourceRegistry
from noveltranslator.storage.progress_manager import ProgressManager
from noveltranslator.storage.repository import NovelRepository
from noveltranslator.processing.normalizer import TextNormalizer

logger = logging.getLogger("noveltranslator.application.download")


@dataclass(frozen=True)
class DownloadSummary:
    novel_id: str
    total_chapters: int
    downloaded_now: int = 0
    skipped: int = 0
    failed: int = 0
    pending: int = 0
    completed: bool = False
    paused: bool = False


class DownloadService:
    """Coordinates sequential, persistent chapter acquisition."""

    def __init__(self, registry: SourceRegistry, repository: NovelRepository, *, on_chapter_error: str = "stop", refresh_metadata: bool = True, skip_existing: bool = True, progress_callback: ProgressCallback | None = None) -> None:
        if on_chapter_error not in {"stop", "skip"}:
            raise ValueError("on_chapter_error must be 'stop' or 'skip'")
        self.registry = registry
        self.repository = repository
        self.on_chapter_error = on_chapter_error
        self.refresh_metadata = refresh_metadata
        self.skip_existing = skip_existing
        self.progress_callback = progress_callback

    def download_novel(self, url: str, *, limit: int | None = None, from_chapter: int | None = None, to_chapter: int | None = None, force: bool = False) -> DownloadSummary:
        if limit is not None and limit < 1:
            raise ValueError("limit must be positive")
        source = self.registry.resolve(url)
        logger.info("Download started: %s", url)
        novel = source.get_novel(url)
        chapters = source.get_chapters(novel)
        novel_id = self._register_novel(novel)
        self._register_chapters(novel_id, chapters)
        return self._process(novel_id, novel, source, chapters, limit=limit, from_chapter=from_chapter, to_chapter=to_chapter, force=force)

    def resume_novel(self, novel_id: str, *, limit: int | None = None) -> DownloadSummary:
        metadata = self.repository.load_novel_metadata(novel_id)
        source = self.registry.resolve(metadata["source_url"])
        novel = source.get_novel(metadata["source_url"])
        chapters = source.get_chapters(novel)
        self._register_chapters(novel_id, chapters)
        return self._process(novel_id, novel, source, chapters, limit=limit, force=False)

    def _register_novel(self, novel: Novel) -> str:
        novel_id = self.repository.create_novel(novel)
        if self.refresh_metadata and self.repository.novel_exists(novel_id):
            self.repository.save_novel_metadata(novel_id, {
                "title": novel.title, "author": novel.author, "description": novel.description,
                "cover_url": novel.cover_url, "language": novel.language, "source": novel.source,
                "source_url": novel.source_url,
            })
        return novel_id

    def _register_chapters(self, novel_id: str, chapters: Iterable[Chapter]) -> None:
        for chapter in chapters:
            self.repository.create_chapter(novel_id, chapter)
            if self.repository.source_exists(novel_id, chapter.number):
                status = ProcessingState.DOWNLOADED.value
            else:
                current = self.repository.load_chapter_metadata(novel_id, chapter.number)
                status = current.get("status", ProcessingState.PENDING.value)
                if status == ProcessingState.DOWNLOADED.value:
                    status = ProcessingState.PENDING.value
            self.repository.save_chapter_metadata(novel_id, chapter.number, {"title": chapter.title, "url": chapter.url, "chapter_type": chapter.chapter_type, "order_index": chapter.order_index, "status": status})

    def _process(self, novel_id: str, novel: Novel, source, chapters: list[Chapter], *, limit: int | None, from_chapter: int | None = None, to_chapter: int | None = None, force: bool) -> DownloadSummary:
        progress = ProgressManager(self.repository, novel_id)
        progress.start_novel()
        selected = [chapter for chapter in chapters if (from_chapter is None or chapter.number >= from_chapter) and (to_chapter is None or chapter.number <= to_chapter)]
        emit_progress(self.progress_callback, ProgressEvent("download", "stage_started", novel_id, total=len(selected), message=f"{len(selected)} capítulos seleccionados"))
        downloaded = skipped = failed = 0
        paused = False
        for chapter in selected:
            valid = self._valid_source(novel_id, chapter.number)
            if valid and self.skip_existing and not force:
                skipped += 1
                self.repository.save_chapter_metadata(novel_id, chapter.number, {"status": ProcessingState.DOWNLOADED.value})
                emit_progress(self.progress_callback, ProgressEvent("download", "item_skipped", novel_id, chapter.number, skipped + downloaded, len(selected), f"Capítulo {chapter.number:03d} ya descargado; se omite"))
                continue
            if self.repository.source_exists(novel_id, chapter.number) and not valid and not force:
                error = CorruptedDataError(f"Invalid source.json for chapter {chapter.number}; use --force to replace it")
                self.repository.save_chapter_metadata(novel_id, chapter.number, {"status": ProcessingState.FAILED.value, "error_type": type(error).__name__, "error_message": str(error)})
                progress.mark_chapter_failed(chapter.number, error)
                failed += 1
                emit_progress(self.progress_callback, ProgressEvent("download", "item_failed", novel_id, chapter.number, skipped + downloaded + failed, len(selected), str(error)))
                if self.on_chapter_error == "stop":
                    break
                continue
            if limit is not None and downloaded >= limit:
                break
            try:
                emit_progress(self.progress_callback, ProgressEvent("download", "item_started", novel_id, chapter.number, skipped + downloaded + failed + 1, len(selected), f"Descargando capítulo {chapter.number:03d}"))
                progress.set_current_chapter(chapter.number)
                progress.set_stage(ProcessingState.DOWNLOADING)
                self.repository.save_chapter_metadata(novel_id, chapter.number, {"status": ProcessingState.DOWNLOADING.value})
                logger.info("Chapter download started: %s/%03d", novel_id, chapter.number)
                result = source.get_chapter(chapter)
                paragraphs = self._validate_paragraphs(result.paragraphs)
                self.repository.save_source(novel_id, chapter.number, novel.language, paragraphs)
                self.repository.save_chapter_metadata(novel_id, chapter.number, {"status": ProcessingState.DOWNLOADED.value, "error_type": None, "error_message": None})
                progress.mark_chapter_completed(chapter.number)
                downloaded += 1
                emit_progress(self.progress_callback, ProgressEvent("download", "item_completed", novel_id, chapter.number, skipped + downloaded, len(selected), f"Capítulo {chapter.number:03d} descargado"))
                logger.info("Chapter downloaded: %s/%03d", novel_id, chapter.number)
            except KeyboardInterrupt:
                paused = True
                self.repository.save_chapter_metadata(novel_id, chapter.number, {"status": ProcessingState.PAUSED.value})
                progress.pause()
                logger.warning("Download paused: %s/%03d", novel_id, chapter.number)
                break
            except Exception as error:
                failed += 1
                emit_progress(self.progress_callback, ProgressEvent("download", "item_failed", novel_id, chapter.number, skipped + downloaded + failed, len(selected), f"Error en capítulo {chapter.number:03d}: {error}"))
                self.repository.save_chapter_metadata(novel_id, chapter.number, {"status": ProcessingState.FAILED.value, "error_type": type(error).__name__, "error_message": str(error)[:500]})
                progress.mark_chapter_failed(chapter.number, error)
                logger.error("Chapter failed: %s/%03d (%s)", novel_id, chapter.number, type(error).__name__)
                if self.on_chapter_error == "stop":
                    break
        pending = sum(1 for chapter in chapters if not self._valid_source(novel_id, chapter.number))
        completed = pending == 0 and failed == 0 and not paused
        if completed:
            progress.complete()
            logger.info("Download completed: %s", novel_id)
        emit_progress(self.progress_callback, ProgressEvent("download", "stage_completed", novel_id, current=downloaded + skipped + failed, total=len(selected), message=f"{downloaded} descargados, {skipped} omitidos, {failed} fallidos"))
        return DownloadSummary(novel_id, len(chapters), downloaded, skipped, failed, pending, completed, paused)

    def _valid_source(self, novel_id: str, number: int) -> bool:
        if not self.repository.source_exists(novel_id, number):
            return False
        try:
            data = self.repository.load_source(novel_id, number)
        except Exception:
            return False
        paragraphs = data.get("paragraphs") if isinstance(data, dict) else None
        return isinstance(paragraphs, list) and bool(paragraphs) and all(isinstance(item, str) and item.strip() for item in paragraphs)

    @staticmethod
    def _validate_paragraphs(paragraphs: list[str]) -> list[str]:
        if not isinstance(paragraphs, list):
            raise ValueError("chapter paragraphs must be a list")
        cleaned = TextNormalizer().normalize(paragraphs)
        if not cleaned:
            raise ValueError("chapter has no valid paragraphs")
        return cleaned
