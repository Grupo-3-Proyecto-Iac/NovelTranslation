from pathlib import Path

from noveltranslator.application.validation_service import ValidationService
from noveltranslator.core.enums import GlossaryStatus, ProcessingState
from noveltranslator.core.models import Chapter, GlossaryTerm, Novel
from noveltranslator.processing.normalizer import TextNormalizer
from noveltranslator.processing.splitter import TextSplitter
from noveltranslator.storage.repository import NovelRepository
from noveltranslator.validation.chapter_validator import ChapterValidator
from noveltranslator.validation.chunk_validator import ChunkValidator
from noveltranslator.validation.models import ValidationStatus


def fixture_repo(tmp_path: Path, translated: str = "Reino de Eldoria llegó.") -> tuple[NovelRepository, str, str]:
    repo = NovelRepository(tmp_path / "novels")
    novel_id = repo.create_novel(Novel("quality", "Quality", "Author", "en", None, None, "test", "https://example.test"))
    repo.create_chapter(novel_id, Chapter(1, "One", "https://example.test/1", ProcessingState.TRANSLATED))
    source = ["Kingdom of Eldoria arrived."]
    repo.save_source(novel_id, 1, "en", source)
    normalizer = TextNormalizer()
    chunks = TextSplitter(overlap_paragraphs=0).split(source, 1)
    source_hash = normalizer.source_hash(normalizer.normalize(source))
    repo.save_chunks(novel_id, 1, source_hash, chunks)
    repo.save_glossary(novel_id, {"terms": [GlossaryTerm("Kingdom of Eldoria", "LOCATION", "Reino de Eldoria", True, GlossaryStatus.LOCKED)]})
    repo.save_translation_chunk(novel_id, 1, "default", {"chapter_number": 1, "chunk_index": 1, "translation_id": "default", "source_hash": source_hash, "source_text": chunks[0].source_text, "translated_text": translated, "translator_id": "mock", "model_id": "mock-v1", "source_language": "en", "target_language": "es"})
    return repo, novel_id, source_hash


def test_chunk_validator_empty_placeholder_and_untranslated() -> None:
    validator = ChunkValidator()
    empty = validator.validate("A source", "  ", chapter_number=1, chunk_index=1)
    assert empty.status is ValidationStatus.FAILED
    assert empty.errors[0].code == "EMPTY_TRANSLATION"
    leaked = validator.validate("A source", "__NT_TERM_0001_AAAA__", chapter_number=1, chunk_index=1)
    assert any(issue.code == "PLACEHOLDER_LEAK" for issue in leaked.errors)
    untranslated = validator.validate("He walked into the room and looked at her.", "He walked into the room and looked at her.", chapter_number=1, chunk_index=1)
    assert untranslated.status is ValidationStatus.WARNING
    assert any(issue.code == "POSSIBLE_UNTRANSLATED_TEXT" for issue in untranslated.warnings)


def test_locked_term_and_length_ratio() -> None:
    validator = ChunkValidator()
    glossary = [GlossaryTerm("Kingdom of Eldoria", "LOCATION", "Reino de Eldoria", True, GlossaryStatus.LOCKED)]
    ok = validator.validate("Kingdom of Eldoria arrived.", "Reino de Eldoria llegó.", chapter_number=1, chunk_index=1, glossary_terms=glossary)
    assert ok.status is ValidationStatus.OK
    missing = validator.validate("Kingdom of Eldoria arrived.", "El reino llegó.", chapter_number=1, chunk_index=1, glossary_terms=glossary)
    assert missing.status is ValidationStatus.FAILED
    assert any(issue.code == "LOCKED_TERM_MISSING" for issue in missing.errors)
    short = validator.validate("A very long source sentence with many words.", "Sí.", chapter_number=1, chunk_index=1)
    assert any(issue.code == "SUSPICIOUS_LENGTH_RATIO" for issue in short.warnings)


def test_locked_term_matching_uses_word_boundaries() -> None:
    validator = ChunkValidator(untranslated_enabled=False)
    zen = GlossaryTerm("Zen", "OTHER", "zen", True, GlossaryStatus.LOCKED)
    false_match = validator.validate(
        "Dozens of warriors arrived.",
        "Llegaron decenas de guerreros.",
        chapter_number=1,
        chunk_index=1,
        glossary_terms=[zen],
    )
    assert false_match.status is ValidationStatus.OK

    true_match = validator.validate(
        "Zen techniques are practiced here.",
        "Aquí se practican técnicas.",
        chapter_number=1,
        chunk_index=1,
        glossary_terms=[zen],
    )
    assert any(issue.code == "LOCKED_TERM_MISSING" for issue in true_match.errors)


def test_singular_locked_term_does_not_match_plural_source() -> None:
    validator = ChunkValidator(untranslated_enabled=False)
    term = GlossaryTerm("Princess Consort", "TITLE", "princesa consorte", True, GlossaryStatus.LOCKED)
    result = validator.validate(
        "The crown princess consorts arrived.",
        "Llegaron las princesas consortes.",
        chapter_number=1,
        chunk_index=1,
        glossary_terms=[term],
    )
    assert result.status is ValidationStatus.OK


def test_chapter_validation_persists_and_detects_hash_and_missing(tmp_path: Path) -> None:
    repo, novel_id, source_hash = fixture_repo(tmp_path)
    result = ValidationService(repo).validate_novel(novel_id)
    assert result.ok == 1
    stored = repo.load_validation_result(novel_id, 1, "default")
    assert stored["status"] == "OK"
    assert stored["metrics"]["source_hash"] == source_hash

    repo.save_translation_chunk(novel_id, 1, "default", {"chapter_number": 1, "chunk_index": 1, "translation_id": "default", "source_hash": "old", "translated_text": "Reino de Eldoria llegó.", "translator_id": "mock", "model_id": "mock-v1", "source_language": "en", "target_language": "es"})
    mismatch = ChapterValidator(repo).validate_chapter(novel_id, 1)
    assert mismatch.status is ValidationStatus.FAILED
    assert any(issue.code == "SOURCE_HASH_MISMATCH" for issue in mismatch.errors)

    repo.save_translation_chunk(novel_id, 1, "default", {"chapter_number": 1, "chunk_index": 1, "translation_id": "default", "source_hash": source_hash, "translated_text": "Reino de Eldoria llegó.", "translator_id": "mock", "model_id": "mock-v1", "source_language": "en", "target_language": "es"})
    (tmp_path / "novels" / novel_id / "chapters" / "001" / "translations" / "default" / "chunk_001.json").unlink()
    missing = ChapterValidator(repo).validate_chapter(novel_id, 1)
    assert any(issue.code == "MISSING_CHUNK" for issue in missing.errors)
