from noveltranslator.core.enums import EntityType, ProcessingState
from noveltranslator.core.models import Chapter, Entity, Novel


def test_domain_models_can_be_created() -> None:
    chapter = Chapter(1, "Chapter One", "https://example.test/ch1")
    novel = Novel("novel-1", "A Novel", "Author", "en", "Description", None, "test", "https://example.test", [chapter])
    entity = Entity("Alice", EntityType.CHARACTER, 0.99, True, "Alicia")
    assert novel.chapters[0].number == 1
    assert entity.type is EntityType.CHARACTER


def test_enums_expose_processing_states() -> None:
    assert ProcessingState.PENDING.value == "PENDING"
    assert ProcessingState.COMPLETED.value == "COMPLETED"

