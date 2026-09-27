import logging
from dataclasses import dataclass

from noveltranslator.analysis.context_builder import ContextBuilder
from noveltranslator.core.enums import EntityStatus, EntityType, GlossaryStatus, ProcessingState
from noveltranslator.core.models import Chunk, Entity, GlossaryTerm, TranslationMemoryEntry
from noveltranslator.processing.glossary import GlossaryManager
from noveltranslator.processing.memory import MemoryManager, normalized_key
from noveltranslator.processing.normalizer import TextNormalizer
from noveltranslator.processing.validator import TranslationValidator
from noveltranslator.storage.progress_manager import ProgressManager
from noveltranslator.storage.repository import NovelRepository
from noveltranslator.storage.serialization import utc_now_iso
from noveltranslator.translators.models import TranslationRequest
from noveltranslator.translators.protection import ProtectedTermProtector
from noveltranslator.translators.registry import TranslatorRegistry
from noveltranslator.validation.chunk_validator import ChunkValidator
from noveltranslator.application.validation_service import ValidationService

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
    def __init__(self, repository: NovelRepository, registry: TranslatorRegistry, *, context_builder: ContextBuilder | None = None, validator: TranslationValidator | None = None, protector: ProtectedTermProtector | None = None, max_attempts: int = 1, memory_enabled: bool = True, max_translation_entries: int = 20, max_context_items: int = 20, previous_chapters: int = 2, auto_validate: bool = False, validation_service: ValidationService | None = None) -> None:
        self.repository = repository
        self.registry = registry
        self.context_builder = context_builder or ContextBuilder()
        self.validator = validator or TranslationValidator()
        self.protector = protector or ProtectedTermProtector()
        self.normalizer = TextNormalizer()
        self.max_attempts = max(1, int(max_attempts))
        self.memory_enabled = memory_enabled
        self.max_translation_entries = max(0, int(max_translation_entries))
        self.max_context_items = max(0, int(max_context_items))
        self.previous_chapters = max(0, int(previous_chapters))
        self.auto_validate = auto_validate
        self.validation_service = validation_service or ValidationService(repository)

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
        memory = MemoryManager(self.repository, novel_id)
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
                result = self._translate_chapter(novel_id, number, metadata, chapter_metadata, glossary, translator, translation_id, progress, force, source_language, target_language, memory)
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

    def _translate_chapter(self, novel_id, number, novel_metadata, chapter_metadata, glossary, translator, translation_id, progress, force, source_language, target_language, memory: MemoryManager) -> tuple[int, int]:
        chunks_payload = self.repository.load_chunks(novel_id, number)
        source_data = self.repository.load_source(novel_id, number)
        current_hash = self.normalizer.source_hash(self.normalizer.normalize(source_data.get("paragraphs", [])))
        if chunks_payload.get("source_hash") != current_hash:
            if self.memory_enabled:
                memory.mark_stale_for_chapter(number, current_hash)
            raise ValueError("persisted chunks are stale for the current source")
        chunks = [Chunk(**item) for item in chunks_payload.get("chunks", [])]
        analysis = self.repository.load_analysis(novel_id, number) if self.repository.analysis_exists(novel_id, number) else {}
        entities = [self._entity(item) for item in analysis.get("entities", [])]
        translated = skipped = 0
        previous: list[Chunk] = []
        self.repository.save_chapter_metadata(novel_id, number, {"status": ProcessingState.TRANSLATING.value})
        for chunk in chunks:
            if self._translation_valid(novel_id, number, translation_id, chunk.index, current_hash) and not force:
                if self.memory_enabled:
                    self._reconcile_chunk_memory(memory, novel_id, number, chunk, translation_id, current_hash)
                skipped += 1
                previous.append(chunk)
                continue
            progress.set_current_chapter(number)
            progress.set_stage(ProcessingState.TRANSLATING)
            progress.set_chunk_progress(chunk.index, len(chunks))
            source_language_value = source_language or novel_metadata.get("language", "en")
            relevant_memory = memory.find_relevant(chunk.source_text, source_language=source_language_value, target_language=target_language, translation_id=translation_id, max_items=self.max_translation_entries) if self.memory_enabled else []
            locked_keys = {normalized_key(term.term) for term in glossary if term.locked or term.status is GlossaryStatus.CONFIRMED}
            relevant_memory = [item for item in relevant_memory if normalized_key(item.source_text) not in locked_keys]
            relevant_context = memory.find_context(chunk.source_text, chapter_number=number, translation_id=translation_id, previous_chapters=self.previous_chapters, max_items=self.max_context_items) if self.memory_enabled else []
            context = self.context_builder.build(novel_metadata["title"], chapter_metadata.get("title", ""), number, chunk, previous, glossary, entities, relevant_memory, relevant_context)
            protected_text, replacements, protected_terms = self.protector.protect(chunk.source_text, context.glossary_terms)
            request = TranslationRequest(protected_text, source_language_value, target_language, novel_metadata["title"], chapter_metadata.get("title", ""), number, chunk.index, context.previous_chunk_text, context.glossary_terms, protected_terms, context.entities, translation_memory=context.translation_memory, narrative_context=context.narrative_context)
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
            self.repository.save_translation_chunk(novel_id, number, translation_id, {"chapter_number": number, "chunk_index": chunk.index, "translation_id": translation_id, "source_hash": current_hash, "source_text": chunk.source_text, "translated_text": clean, "translator_id": result.translator_id, "model_id": result.model_id, "source_language": result.source_language, "target_language": result.target_language, "created_at": utc_now_iso(), "elapsed_seconds": result.elapsed_seconds, "metadata": result.metadata})
            if self.memory_enabled:
                self._record_chunk_memory(memory, chunk, clean, result.source_language, result.target_language, number, translation_id, current_hash, protected_terms)
            translated += 1
            previous.append(chunk)
        self.repository.save_chapter_metadata(novel_id, number, {"status": ProcessingState.TRANSLATED.value})
        if self.memory_enabled:
            self._save_chapter_context(memory, novel_id, number, translation_id, current_hash, entities, glossary)
        if self.auto_validate:
            self.repository.save_chapter_metadata(novel_id, number, {"status": ProcessingState.VALIDATING.value})
            result = self.validation_service.validate_chapter(novel_id, number, translation_id, progress=progress)
            if result.status.value == "FAILED":
                raise ValueError("chapter validation failed")
        else:
            progress.mark_translation_completed(number)
        return translated, skipped

    def _record_chunk_memory(self, memory, chunk, translated_text, source_language, target_language, chapter_number, translation_id, source_hash, protected_terms):
        if len(chunk.source_text) <= 160 and "\n" not in chunk.source_text.strip():
            memory.add_translation_entry(TranslationMemoryEntry(f"{translation_id}-{chapter_number}-{chunk.index}", chunk.source_text, translated_text, source_language, target_language, chapter_number, chunk.index, utc_now_iso(), source_hash, translation_id, "ACTIVE", False, 0, None, None))
        for term in protected_terms:
            if term.translation and term.term in chunk.source_text:
                memory.add_translation_entry(TranslationMemoryEntry(f"{translation_id}-{chapter_number}-{chunk.index}-{term.term}", term.term, term.translation, source_language, target_language, chapter_number, chunk.index, utc_now_iso(), source_hash, translation_id, "ACTIVE", True, 0, None, 1.0))

    def _reconcile_chunk_memory(self, memory, novel_id, chapter_number, chunk, translation_id, source_hash):
        data = self.repository.load_translation_chunk(novel_id, chapter_number, translation_id, chunk.index)
        if not data.get("translated_text"):
            return
        source_language = data.get("source_language", "en")
        target_language = data.get("target_language", "es")
        memory.add_translation_entry(TranslationMemoryEntry(f"{translation_id}-{chapter_number}-{chunk.index}", chunk.source_text, data["translated_text"], source_language, target_language, chapter_number, chunk.index, data.get("created_at", utc_now_iso()), source_hash, translation_id, "ACTIVE", False, 0, None, None))
        logger.info("Memory reconciled: %s/%03d/%03d", novel_id, chapter_number, chunk.index)

    def _save_chapter_context(self, memory, novel_id, chapter_number, translation_id, source_hash, entities, glossary):
        names = sorted({entity.text for entity in entities} | {term.term for term in glossary if term.locked or term.status is GlossaryStatus.CONFIRMED})
        summary = [f"{name} is relevant in chapter {chapter_number}." for name in names]
        self.repository.save_chapter_context(novel_id, chapter_number, {"chapter_number": chapter_number, "summary": summary, "entities": names, "source_hash": source_hash, "translation_id": translation_id, "updated_at": utc_now_iso()})
        for item in summary:
            memory.add_context_item(item, chapter_number, names, source_hash=source_hash, translation_id=translation_id)

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
