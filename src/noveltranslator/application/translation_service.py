import logging
from dataclasses import dataclass

from noveltranslator.analysis.context_builder import ContextBuilder
from noveltranslator.core.enums import EntityStatus, EntityType, GlossaryStatus, ProcessingState
from noveltranslator.core.models import Chunk, Entity, GlossaryTerm
from noveltranslator.processing.glossary import GlossaryManager
from noveltranslator.processing.normalizer import TextNormalizer
from noveltranslator.processing.validator import TranslationValidator
from noveltranslator.storage.progress_manager import ProgressManager
from noveltranslator.storage.repository import NovelRepository
from noveltranslator.storage.serialization import utc_now_iso
from noveltranslator.translators.models import TranslationRequest
from noveltranslator.translators.protection import ProtectedTermProtector
from noveltranslator.translators.registry import TranslatorRegistry

logger = logging.getLogger("noveltranslator.application.translation")


@dataclass(frozen=True)
class TranslationSummary:
    novel_id: str
    translation_id: str
    chapters_processed: int = 0
    chunks_translated: int = 0
    chunks_skipped: int = 0
    chunks_failed: int = 0
    pending: int = 0
    completed: bool = False
    paused: bool = False


class TranslationService:
    def __init__(self, repository: NovelRepository, registry: TranslatorRegistry, *, context_builder: ContextBuilder | None = None, validator: TranslationValidator | None = None, protector: ProtectedTermProtector | None = None, max_attempts: int = 1) -> None:
        self.repository = repository
        self.registry = registry
        self.context_builder = context_builder or ContextBuilder()
        self.validator = validator or TranslationValidator()
        self.protector = protector or ProtectedTermProtector()
        self.normalizer = TextNormalizer()
        self.max_attempts = max(1, int(max_attempts))

    def translate_novel(self, novel_id: str, *, translation_id: str = "default", translator_id: str = "mock", source_language: str | None = None, target_language: str = "es", limit: int | None = None, from_chapter: int | None = None, to_chapter: int | None = None, force: bool = False) -> TranslationSummary:
        if limit is not None and limit < 1:
            raise ValueError("limit must be positive")
        translator = self.registry.resolve(translator_id)
        metadata = self.repository.load_novel_metadata(novel_id)
        chapters = self.repository.list_chapters(novel_id)
        progress = ProgressManager(self.repository, novel_id)
        progress.start_novel()
        progress.set_translation_id(translation_id)
        glossary = GlossaryManager(self.repository, novel_id).list_terms()
        processed = translated = skipped = failed = 0
        paused = False
        for number in chapters:
            if from_chapter is not None and number < from_chapter or to_chapter is not None and number > to_chapter:
                continue
            if limit is not None and processed >= limit:
                break
            if not self.repository.chunks_exist(novel_id, number):
                continue
            chapter_metadata = self.repository.load_chapter_metadata(novel_id, number)
            try:
                result = self._translate_chapter(novel_id, number, metadata, chapter_metadata, glossary, translator, translation_id, progress, force, source_language, target_language)
                translated += result[0]
                skipped += result[1]
                processed += 1
            except KeyboardInterrupt:
                paused = True
                self.repository.save_chapter_metadata(novel_id, number, {"status": ProcessingState.PAUSED.value})
                progress.pause()
                break
            except Exception as error:
                failed += 1
                self.repository.save_chapter_metadata(novel_id, number, {"status": ProcessingState.FAILED.value, "error_type": type(error).__name__, "error_message": str(error)[:500]})
                progress.mark_chapter_failed(number, error)
                logger.error("Translation failed: %s/%03d", novel_id, number)
                break
        pending = sum(1 for number in chapters if self.repository.chunks_exist(novel_id, number) and not self._chapter_complete(novel_id, number, translation_id))
        completed = pending == 0 and failed == 0 and not paused and any(self.repository.chunks_exist(novel_id, number) for number in chapters)
        if completed:
            progress.complete()
        return TranslationSummary(novel_id, translation_id, processed, translated, skipped, failed, pending, completed, paused)

    def _translate_chapter(self, novel_id, number, novel_metadata, chapter_metadata, glossary, translator, translation_id, progress, force, source_language, target_language) -> tuple[int, int]:
        chunks_payload = self.repository.load_chunks(novel_id, number)
        source_data = self.repository.load_source(novel_id, number)
        current_hash = self.normalizer.source_hash(self.normalizer.normalize(source_data.get("paragraphs", [])))
        if chunks_payload.get("source_hash") != current_hash:
            raise ValueError("persisted chunks are stale for the current source")
        chunks = [Chunk(**item) for item in chunks_payload.get("chunks", [])]
        analysis = self.repository.load_analysis(novel_id, number) if self.repository.analysis_exists(novel_id, number) else {}
        entities = [self._entity(item) for item in analysis.get("entities", [])]
        translated = skipped = 0
        previous: list[Chunk] = []
        self.repository.save_chapter_metadata(novel_id, number, {"status": ProcessingState.TRANSLATING.value})
        for chunk in chunks:
            if self._translation_valid(novel_id, number, translation_id, chunk.index, current_hash) and not force:
                skipped += 1
                previous.append(chunk)
                continue
            progress.set_current_chapter(number)
            progress.set_stage(ProcessingState.TRANSLATING)
            progress.set_chunk_progress(chunk.index, len(chunks))
            context = self.context_builder.build(novel_metadata["title"], chapter_metadata.get("title", ""), number, chunk, previous, glossary, entities)
            protected_text, replacements, protected_terms = self.protector.protect(chunk.source_text, context.glossary_terms)
            request = TranslationRequest(protected_text, source_language or novel_metadata.get("language", "en"), target_language, novel_metadata["title"], chapter_metadata.get("title", ""), number, chunk.index, context.previous_chunk_text, context.glossary_terms, protected_terms, context.entities)
            result = None
            for attempt in range(1, self.max_attempts + 1):
                try:
                    result = translator.translate(request)
                    break
                except Exception:
                    if attempt == self.max_attempts:
                        raise
                    logger.warning("Translation attempt %d/%d failed for %s/%03d/%03d", attempt, self.max_attempts, novel_id, number, chunk.index)
            assert result is not None
            restored = self.protector.restore(result.translated_text, replacements)
            clean = self.validator.validate(restored, replacements)
            self.repository.save_translation_chunk(novel_id, number, translation_id, {"chapter_number": number, "chunk_index": chunk.index, "source_hash": current_hash, "source_text": chunk.source_text, "translated_text": clean, "translator_id": result.translator_id, "model_id": result.model_id, "source_language": result.source_language, "target_language": result.target_language, "created_at": utc_now_iso(), "elapsed_seconds": result.elapsed_seconds, "metadata": result.metadata})
            translated += 1
            previous.append(chunk)
        self.repository.save_chapter_metadata(novel_id, number, {"status": ProcessingState.TRANSLATED.value})
        progress.mark_translation_completed(number)
        return translated, skipped

    def _translation_valid(self, novel_id, number, translation_id, chunk_index, source_hash) -> bool:
        if not self.repository.translation_chunk_exists(novel_id, number, translation_id, chunk_index):
            return False
        data = self.repository.load_translation_chunk(novel_id, number, translation_id, chunk_index)
        return data.get("source_hash") == source_hash and bool(str(data.get("translated_text", "")).strip()) and bool(data.get("translator_id")) and bool(data.get("model_id"))

    def _chapter_complete(self, novel_id, number, translation_id) -> bool:
        chunks = self.repository.load_chunks(novel_id, number).get("chunks", [])
        source_hash = self.repository.load_chunks(novel_id, number).get("source_hash")
        return bool(chunks) and all(self._translation_valid(novel_id, number, translation_id, int(item["index"]), source_hash) for item in chunks)

    @staticmethod
    def _entity(data: dict) -> Entity:
        return Entity(data["text"], EntityType(data.get("type", EntityType.OTHER)), data.get("confidence"), data.get("preserve", False), data.get("translation"), EntityStatus(data.get("status", EntityStatus.CANDIDATE)), data.get("first_seen_chapter"), data.get("first_seen_chunk"))
