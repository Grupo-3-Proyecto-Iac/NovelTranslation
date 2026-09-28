from noveltranslator.application.translation_repair_service import TranslationRepairService
from noveltranslator.core.enums import EntityType, GlossaryStatus
from noveltranslator.core.models import Chapter, GlossaryTerm, Novel
from noveltranslator.processing.glossary import GlossaryManager
from noveltranslator.storage.repository import NovelRepository


def make_repository(tmp_path):
    repository = NovelRepository(tmp_path / "novels")
    novel_id = repository.create_novel(Novel("", "Novel", None, "en", None, None, "test", "url"))
    repository.create_chapter(novel_id, Chapter(1, "One", "url"))
    repository.save_source(novel_id, 1, "en", ["source"])
    return repository, novel_id


def test_repair_existing_chunks_uses_locked_glossary_and_is_idempotent(tmp_path):
    repository, novel_id = make_repository(tmp_path)
    GlossaryManager(repository, novel_id).add(
        GlossaryTerm(
            "Vermilion Princess",
            EntityType.TITLE,
            "Princesa Vermileon",
            True,
            GlossaryStatus.LOCKED,
            "manual",
        )
    )
    repository.save_translation_chunk(
        novel_id,
        1,
        "hf-opus-v3",
        {
            "chapter_number": 1,
            "chunk_index": 1,
            "translated_text": "The Vermilion Princess arrived. La Princesa Vermilion esperó.",
        },
    )

    service = TranslationRepairService(repository)
    preview = service.repair_novel(novel_id, "hf-opus-v3", dry_run=True)
    assert preview.chunks_changed == 1
    assert repository.load_translation_chunk(novel_id, 1, "hf-opus-v3", 1)["translated_text"].startswith("The Vermilion")

    result = service.repair_novel(novel_id, "hf-opus-v3")
    assert result.replacements == 2
    chunk = repository.load_translation_chunk(novel_id, 1, "hf-opus-v3", 1)
    assert chunk["translated_text"] == "La Princesa Vermileon arrived. La Princesa Vermileon esperó."
    assert service.repair_novel(novel_id, "hf-opus-v3").chunks_changed == 0


def test_repair_known_title_variants(tmp_path):
    repository, novel_id = make_repository(tmp_path)
    GlossaryManager(repository, novel_id).add(
        GlossaryTerm("Vermilion Princess", EntityType.TITLE, "Princesa Vermileon", True, GlossaryStatus.LOCKED, "manual")
    )
    repository.save_translation_chunk(
        novel_id,
        1,
        "hf-opus-v3",
        {"chapter_number": 1, "chunk_index": 1, "translated_text": "Vermillón Princesa. Las Princesas Azure como las Vermilion."},
    )
    TranslationRepairService(repository).repair_novel(novel_id, "hf-opus-v3")
    text = repository.load_translation_chunk(novel_id, 1, "hf-opus-v3", 1)["translated_text"]
    assert text == "Princesa Vermileon. la Princesa Azure y la Princesa Vermileon."
