from pathlib import Path

from noveltranslator.application.translation_service import TranslationService
from noveltranslator.core.enums import GlossaryStatus, ProcessingState
from noveltranslator.core.models import Chapter, GlossaryTerm, Novel, TranslationMemoryEntry
from noveltranslator.processing.memory import MemoryManager
from noveltranslator.processing.normalizer import TextNormalizer
from noveltranslator.processing.splitter import TextSplitter
from noveltranslator.storage.repository import NovelRepository
from noveltranslator.storage.serialization import utc_now_iso
from noveltranslator.translators import MockTranslator, TranslatorRegistry


def make_novel(tmp_path: Path) -> tuple[NovelRepository, str]:
    repo = NovelRepository(tmp_path / "novels")
    novel_id = repo.create_novel(Novel("memory", "Memory Novel", "Author", "en", None, None, "test", "https://example.test"))
    return repo, novel_id


def entry(source: str, translation: str, *, chapter: int | None = 1, source_hash: str | None = "hash") -> TranslationMemoryEntry:
    return TranslationMemoryEntry("id", source, translation, "en", "es", chapter, 1, utc_now_iso(), source_hash, "default")


def test_memory_add_deduplicates_and_marks_conflicts(tmp_path: Path) -> None:
    repo, novel_id = make_novel(tmp_path)
    manager = MemoryManager(repo, novel_id)
    manager.add_translation_entry(entry("Your Highness", "Su Alteza"))
    manager.add_translation_entry(entry("Your Highness", "Su Alteza"))
    manager.add_translation_entry(entry("Your Highness", "Vuestra Alteza"))

    entries = manager.load_translation_memory()
    assert len(entries) == 2
    assert {item.status for item in entries} == {"CONFLICT"}
    assert manager.find_exact("  your   highness ", "en", "es").translated_text in {"Su Alteza", "Vuestra Alteza"}


def test_memory_marks_stale_by_provenance_and_context_is_relevant_and_limited(tmp_path: Path) -> None:
    repo, novel_id = make_novel(tmp_path)
    manager = MemoryManager(repo, novel_id)
    manager.add_translation_entry(entry("Kingdom of Eldoria", "Reino de Eldoria", source_hash="old"))
    assert manager.find_exact("Kingdom of Eldoria", "en", "es", source_hash="new") is None
    assert manager.load_translation_memory()[0].status == "STALE"
    for index in range(100):
        manager.add_context_item(f"Alicia fact {index}", index + 1, ["Alicia"], translation_id="default")
    relevant = manager.find_context("Alicia", chapter_number=100, previous_chapters=100, max_items=5)
    assert len(relevant) == 5


def test_context_items_are_merged_and_persisted_in_one_write(tmp_path: Path, monkeypatch) -> None:
    repo, novel_id = make_novel(tmp_path)
    manager = MemoryManager(repo, novel_id)
    original = manager.add_context_item("Alice is relevant.", 1, ["Alice"], source_hash="old")

    writes = 0
    save_context_memory = repo.save_context_memory

    def count_saves(saved_novel_id, payload):
        nonlocal writes
        writes += 1
        save_context_memory(saved_novel_id, payload)

    monkeypatch.setattr(repo, "save_context_memory", count_saves)
    returned = manager.add_context_items(
        [
            ("Alice is relevant.", 1, ["Alice", "Queen"]),
            ("The palace is relevant.", 1, ["Alice", "Queen"]),
        ],
        source_hash="new",
    )

    stored = manager.load_context_memory()
    assert writes == 1
    assert len(stored) == 2
    assert returned[0].id == original.id
    assert returned[0].source_hash == "new"
    assert returned[0].entities == ["Alice", "Queen"]
    assert stored[1].text == "The palace is relevant."
    assert stored[1].source_hash == "new"


def test_translation_builds_chapter_context_and_reconciles_memory(tmp_path: Path, monkeypatch) -> None:
    repo, novel_id = make_novel(tmp_path)
    repo.create_chapter(novel_id, Chapter(1, "First", "https://example.test/1", ProcessingState.DOWNLOADED))
    repo.save_source(novel_id, 1, "en", ["Alice meets the Moon Sword."])
    paragraphs = ["Alice meets the Moon Sword."]
    normalizer = TextNormalizer()
    chunks = TextSplitter(overlap_paragraphs=0).split(paragraphs, 1)
    repo.save_chunks(novel_id, 1, normalizer.source_hash(normalizer.normalize(paragraphs)), chunks)
    repo.save_analysis(novel_id, 1, {"entities": [{"text": "Alice", "type": "CHARACTER"}]})
    repo.save_glossary(novel_id, {"terms": [GlossaryTerm("Moon Sword", "ITEM", "Espada Lunar", True, GlossaryStatus.LOCKED)]})
    registry = TranslatorRegistry()
    translator = MockTranslator()
    registry.register(translator)

    context_writes = 0
    save_context_memory = repo.save_context_memory

    def count_context_writes(saved_novel_id, payload):
        nonlocal context_writes
        context_writes += 1
        save_context_memory(saved_novel_id, payload)

    monkeypatch.setattr(repo, "save_context_memory", count_context_writes)

    summary = TranslationService(repo, registry, max_translation_entries=20, max_context_items=20).translate_novel(novel_id)
    assert summary.completed
    assert repo.chapter_context_exists(novel_id, 1)
    assert context_writes == 1
    assert any(item.source_text == "Moon Sword" for item in MemoryManager(repo, novel_id).load_translation_memory())

    # A second run sees a valid translation and reconciles without another model call.
    second = TranslationService(repo, registry).translate_novel(novel_id)
    assert second.chunks_skipped == 1
    assert translator.calls == 2


def test_next_chapter_receives_relevant_narrative_context(tmp_path: Path) -> None:
    repo, novel_id = make_novel(tmp_path)
    for number, text in ((1, "Alice arrived."), (2, "Alice remembered the arrival.")):
        repo.create_chapter(novel_id, Chapter(number, f"Chapter {number}", f"https://example.test/{number}", ProcessingState.DOWNLOADED))
        repo.save_source(novel_id, number, "en", [text])
        normalizer = TextNormalizer()
        chunks = TextSplitter(overlap_paragraphs=0).split([text], number)
        repo.save_chunks(novel_id, number, normalizer.source_hash(normalizer.normalize([text])), chunks)
        repo.save_analysis(novel_id, number, {"entities": [{"text": "Alice", "type": "CHARACTER"}]})

    class RecordingTranslator(MockTranslator):
        def __init__(self):
            super().__init__()
            self.requests = []

        def translate(self, request):
            self.requests.append(request)
            return super().translate(request)

    translator = RecordingTranslator()
    registry = TranslatorRegistry()
    registry.register(translator)
    TranslationService(repo, registry).translate_novel(novel_id)
    chapter_two_request = translator.requests[-1]
    assert any("Alice" in item.text for item in chapter_two_request.narrative_context)
