from pathlib import Path

import pytest

from noveltranslator.application.translation_service import TranslationService
from noveltranslator.core.enums import GlossaryStatus, ProcessingState
from noveltranslator.core.models import Chapter, GlossaryTerm, Novel
from noveltranslator.processing.normalizer import TextNormalizer
from noveltranslator.processing.splitter import TextSplitter
from noveltranslator.storage.repository import NovelRepository
from noveltranslator.translators import MockTranslator, TranslatorRegistry
from noveltranslator.translators.protection import ProtectedTermProtector, TranslationValidator


def prepared_repository(tmp_path: Path) -> tuple[NovelRepository, str]:
    repo = NovelRepository(tmp_path / "novels")
    novel_id = repo.create_novel(Novel("sample", "Sample", "Author", "en", None, None, "test", "https://example.test/sample"))
    repo.create_chapter(novel_id, Chapter(1, "First", "https://example.test/sample/1", ProcessingState.DOWNLOADED))
    paragraphs = ["Alice meets the Moon Sword.", "She keeps walking."]
    repo.save_source(novel_id, 1, "en", paragraphs)
    normalizer = TextNormalizer()
    chunks = TextSplitter(overlap_paragraphs=0).split(paragraphs, 1)
    repo.save_chunks(novel_id, 1, normalizer.source_hash(normalizer.normalize(paragraphs)), chunks)
    repo.save_analysis(novel_id, 1, {"entities": []})
    repo.save_glossary(novel_id, {"terms": [GlossaryTerm("Moon Sword", "ITEM", "Espada Lunar", True, GlossaryStatus.LOCKED)]})
    return repo, novel_id


def test_translation_persists_and_is_idempotent(tmp_path: Path) -> None:
    repo, novel_id = prepared_repository(tmp_path)
    registry = TranslatorRegistry()
    translator = MockTranslator()
    registry.register(translator)

    first = TranslationService(repo, registry).translate_novel(novel_id)
    saved = repo.load_translation_chunk(novel_id, 1, "default", 1)

    assert first.completed is True
    assert first.chunks_translated == 1
    assert "Espada Lunar" in saved["translated_text"]
    assert "\n\n" in saved["translated_text"]
    assert saved["source_hash"]
    assert saved["translator_id"] == "mock"
    assert translator.calls == 2

    second = TranslationService(repo, registry).translate_novel(novel_id)
    assert second.chunks_skipped == 1
    assert second.chunks_translated == 0
    assert translator.calls == 2


def test_translation_preserves_formatting_atoms(tmp_path: Path) -> None:
    repo, novel_id = prepared_repository(tmp_path)
    paragraphs = ["*Hm-hm...  \u2014 hello - world*"]
    repo.save_source(novel_id, 1, "en", paragraphs)
    normalizer = TextNormalizer()
    chunks = TextSplitter(overlap_paragraphs=0).split(paragraphs, 1)
    repo.save_chunks(novel_id, 1, normalizer.source_hash(normalizer.normalize(paragraphs)), chunks)
    repo.save_analysis(novel_id, 1, {"entities": []})
    registry = TranslatorRegistry()
    registry.register(MockTranslator())

    TranslationService(repo, registry).translate_novel(novel_id)
    translated = repo.load_translation_chunk(novel_id, 1, "default", 1)["translated_text"]

    assert "*" in translated
    assert "Hm-hm" in translated
    assert "..." in translated
    assert "  " in translated
    assert "\u2014" in translated
    assert " - " in translated


def test_protection_handles_nested_terms_and_collisions() -> None:
    protector = ProtectedTermProtector()
    terms = [
        GlossaryTerm("Shadow", "OTHER", "Sombra", True),
        GlossaryTerm("Shadow Sovereign", "TITLE", "Soberano de la Sombra", True),
    ]
    text = "Shadow Sovereign sees __NT_TERM_0001_" + "0" * 8 + "__."
    protected, replacements, _ = protector.protect(text, terms)
    restored = protector.restore(protected, replacements)
    assert "Shadow Sovereign" not in protected
    assert restored == text.replace("Shadow Sovereign", "Soberano de la Sombra").replace("Shadow", "Sombra")


def test_validator_rejects_missing_or_leaked_protected_terms() -> None:
    validator = TranslationValidator()
    with pytest.raises(ValueError):
        validator.validate("", {"TOKEN": "Term"})
    with pytest.raises(ValueError):
        validator.validate("Texto TOKEN", {"TOKEN": "Term"})
    with pytest.raises(ValueError):
        validator.validate("Texto", {"TOKEN": "Term"})
