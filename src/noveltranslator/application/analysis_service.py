import logging
from dataclasses import dataclass

from noveltranslator.analysis.analyzer import TextAnalyzer
from noveltranslator.application.events import ProgressCallback, ProgressEvent, emit_progress
from noveltranslator.core.enums import ProcessingState
from noveltranslator.core.exceptions import CorruptedDataError
from noveltranslator.processing.glossary import GlossaryManager
from noveltranslator.processing.normalizer import TextNormalizer
from noveltranslator.processing.splitter import TextSplitter
from noveltranslator.storage.progress_manager import ProgressManager
from noveltranslator.storage.repository import NovelRepository
from noveltranslator.storage.serialization import utc_now_iso

logger = logging.getLogger("noveltranslator.application.analysis")


@dataclass(frozen=True)
class AnalysisSummary:
    novel_id: str
    total_chapters: int
    analyzed_now: int = 0
    skipped: int = 0
    failed: int = 0
    pending: int = 0
    completed: bool = False


class AnalysisService:
    def __init__(self, repository: NovelRepository, *, normalizer: TextNormalizer | None = None, splitter: TextSplitter | None = None, analyzer: TextAnalyzer | None = None, progress_callback: ProgressCallback | None = None) -> None:
        self.repository = repository
        self.normalizer = normalizer or TextNormalizer()
        self.splitter = splitter or TextSplitter()
        self.analyzer = analyzer or TextAnalyzer()
        self.progress_callback = progress_callback

    def analyze_novel(self, novel_id: str, *, limit: int | None = None, from_chapter: int | None = None, to_chapter: int | None = None, force: bool = False) -> AnalysisSummary:
        if limit is not None and limit < 1:
            raise ValueError("limit must be positive")
        metadata = self.repository.load_novel_metadata(novel_id)
        chapters = self.repository.list_chapters(novel_id)
        progress = ProgressManager(self.repository, novel_id)
        progress.start_novel()
        glossary = GlossaryManager(self.repository, novel_id)
        analyzed = skipped = failed = 0
        selected = [number for number in chapters if (from_chapter is None or number >= from_chapter) and (to_chapter is None or number <= to_chapter)]
        emit_progress(self.progress_callback, ProgressEvent("analysis", "stage_started", novel_id, total=len(selected), message=f"{len(selected)} capítulos seleccionados"))
        for number in selected:
            if limit is not None and analyzed >= limit:
                break
            if not self.repository.source_exists(novel_id, number):
                emit_progress(self.progress_callback, ProgressEvent("analysis", "item_skipped", novel_id, number, message=f"Capítulo {number:03d} aún no tiene fuente"))
                continue
            try:
                source = self.repository.load_source(novel_id, number)
                paragraphs = self.normalizer.normalize(source.get("paragraphs", []))
                source_digest = self.normalizer.source_hash(paragraphs)
                existing = self.repository.load_analysis(novel_id, number) if self.repository.analysis_exists(novel_id, number) else None
                if not force and self._analysis_valid(existing, source_digest):
                    self.repository.save_chapter_metadata(novel_id, number, {"status": ProcessingState.ANALYZED.value})
                    skipped += 1
                    emit_progress(self.progress_callback, ProgressEvent("analysis", "item_skipped", novel_id, number, skipped + analyzed, len(selected), f"Análisis del capítulo {number:03d} ya existe"))
                    continue
                emit_progress(self.progress_callback, ProgressEvent("analysis", "item_started", novel_id, number, analyzed + skipped + failed + 1, len(selected), f"Analizando capítulo {number:03d}"))
                progress.set_current_chapter(number)
                progress.set_stage(ProcessingState.ANALYZING)
                self.repository.save_chapter_metadata(novel_id, number, {"status": ProcessingState.ANALYZING.value})
                chunks = self.splitter.split(paragraphs, number)
                self.repository.save_chunks(novel_id, number, source_digest, [chunk for chunk in chunks])
                analysis = self.analyzer.analyze(paragraphs, chapter_number=number)
                entities = analysis["entities"]
                terms = []
                for entity in entities:
                    glossary.add_entity(entity)
                    terms.append(entity.text)
                payload = {"source_hash": source_digest, "entities": entities, "terms_found": terms, "chunks": [{"index": chunk.index, "paragraph_start": chunk.paragraph_start, "paragraph_end": chunk.paragraph_end} for chunk in chunks], "analyzed_at": utc_now_iso()}
                self.repository.save_analysis(novel_id, number, payload)
                self.repository.save_chapter_metadata(novel_id, number, {"status": ProcessingState.ANALYZED.value})
                progress.mark_analysis_completed(number)
                analyzed += 1
                emit_progress(self.progress_callback, ProgressEvent("analysis", "item_completed", novel_id, number, analyzed + skipped, len(selected), f"Capítulo {number:03d} analizado"))
                logger.info("Chapter analyzed: %s/%03d", novel_id, number)
            except KeyboardInterrupt:
                progress.pause()
                self.repository.save_chapter_metadata(novel_id, number, {"status": ProcessingState.PAUSED.value})
                break
            except Exception as error:
                failed += 1
                emit_progress(self.progress_callback, ProgressEvent("analysis", "item_failed", novel_id, number, analyzed + skipped + failed, len(selected), f"Error en capítulo {number:03d}: {error}"))
                self.repository.save_chapter_metadata(novel_id, number, {"status": ProcessingState.FAILED.value, "error_type": type(error).__name__, "error_message": str(error)[:500]})
                progress.mark_chapter_failed(number, error)
                logger.error("Analysis failed: %s/%03d", novel_id, number)
                break
        pending = 0
        for number in chapters:
            if not self.repository.source_exists(novel_id, number):
                pending += 1
                continue
            source_data = self.repository.load_source(novel_id, number)
            digest = self.normalizer.source_hash(self.normalizer.normalize(source_data.get("paragraphs", [])))
            if not self.repository.analysis_exists(novel_id, number) or not self._analysis_valid(self.repository.load_analysis(novel_id, number), digest):
                pending += 1
        completed = pending == 0 and failed == 0
        if completed:
            progress.complete()
        emit_progress(self.progress_callback, ProgressEvent("analysis", "stage_completed", novel_id, current=analyzed + skipped + failed, total=len(selected), message=f"{analyzed} analizados, {skipped} omitidos, {failed} fallidos"))
        return AnalysisSummary(novel_id, len(chapters), analyzed, skipped, failed, pending, completed)

    @staticmethod
    def _analysis_valid(analysis, source_hash: str) -> bool:
        return isinstance(analysis, dict) and analysis.get("source_hash") == source_hash and isinstance(analysis.get("entities"), list)

