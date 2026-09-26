from noveltranslator.analysis.context_builder import ContextBuilder
from noveltranslator.analysis.entity_extractor import EntityExtractor
from noveltranslator.application.analysis_service import AnalysisService
from noveltranslator.core.enums import EntityStatus, EntityType, GlossaryStatus, ProcessingState
from noveltranslator.core.models import Chapter, Chunk, Entity, GlossaryTerm, Novel
from noveltranslator.processing.glossary import GlossaryManager
from noveltranslator.processing.normalizer import TextNormalizer
from noveltranslator.processing.splitter import TextSplitter
from noveltranslator.storage.repository import NovelRepository


def test_normalizer_preserves_paragraphs_unicode_and_dialogue():
    paragraphs = TextNormalizer().normalize(["  Hello   world.  ", "", '  "¿Dónde estás?"  ', "한글 日本語"])
    assert paragraphs == ["Hello world.", '"¿Dónde estás?"', "한글 日本語"]


def test_source_hash_is_stable_and_changes_with_content():
    normalizer = TextNormalizer()
    assert normalizer.source_hash(["A", " B "]) == normalizer.source_hash(["A", "B"])
    assert normalizer.source_hash(["A"]) != normalizer.source_hash(["B"])


def test_splitter_is_stable_and_respects_paragraph_boundaries():
    paragraphs = ["one", "two", "three"]
    splitter = TextSplitter(max_characters=20, target_characters=10, overlap_paragraphs=0)
    first = splitter.split(paragraphs, 1)
    second = splitter.split(paragraphs, 1)
    assert [(chunk.index, chunk.paragraph_start, chunk.paragraph_end) for chunk in first] == [(chunk.index, chunk.paragraph_start, chunk.paragraph_end) for chunk in second]
    assert [chunk.source_text for chunk in first] == ["one\n\ntwo", "three"]


def test_splitter_splits_oversized_paragraph_without_losing_text():
    paragraph = "One. Two. Three. Four."
    chunks = TextSplitter(max_characters=10, target_characters=8, overlap_paragraphs=0).split([paragraph], 1)
    assert "".join(chunk.source_text.replace(" ", "") for chunk in chunks).replace(" ", "") == paragraph.replace(" ", "")
    assert all(len(chunk.source_text) <= 10 for chunk in chunks)


def test_entity_extractor_is_deterministic_and_conservative():
    entities = EntityExtractor().extract(["Shadow Sovereign entered Eldoria.", "Shadow Sovereign watched."])
    assert any(entity.text == "Shadow Sovereign" for entity in entities)
    assert all(entity.status is EntityStatus.CANDIDATE for entity in entities)
    assert all(entity.translation is None for entity in entities)


def make_analysis_repository(tmp_path):
    repository = NovelRepository(tmp_path / "novels")
    novel = Novel("analysis-novel", "Analysis Novel", "Author", "en", None, None, "mock", "https://example.test/novel")
    novel_id = repository.create_novel(novel)
    repository.create_chapter(novel_id, Chapter(1, "Chapter 1", "https://example.test/1", ProcessingState.DOWNLOADED))
    repository.save_source(novel_id, 1, "en", ["Shadow Sovereign entered Eldoria.", "Shadow Sovereign waited."])
    return repository, novel_id


def test_analysis_persists_chunks_analysis_and_glossary(tmp_path):
    repository, novel_id = make_analysis_repository(tmp_path)
    service = AnalysisService(repository, splitter=TextSplitter(max_characters=100, target_characters=80, overlap_paragraphs=0))
    summary = service.analyze_novel(novel_id)
    assert summary.analyzed_now == 1 and summary.completed
    analysis = repository.load_analysis(novel_id, 1)
    chunks = repository.load_chunks(novel_id, 1)
    assert analysis["source_hash"] == chunks["source_hash"]
    assert repository.load_chapter_metadata(novel_id, 1)["status"] == "ANALYZED"
    assert any(item.term == "Shadow Sovereign" for item in GlossaryManager(repository, novel_id).list_terms())


def test_analysis_is_idempotent_and_invalidates_on_source_change(tmp_path):
    repository, novel_id = make_analysis_repository(tmp_path)
    service = AnalysisService(repository)
    first = service.analyze_novel(novel_id)
    second = service.analyze_novel(novel_id)
    assert first.analyzed_now == 1 and second.skipped == 1 and second.analyzed_now == 0
    repository.save_source(novel_id, 1, "en", ["Changed original."])
    third = service.analyze_novel(novel_id)
    assert third.analyzed_now == 1


def test_glossary_deduplicates_updates_and_preserves_locked_manual_choice(tmp_path):
    repository, novel_id = make_analysis_repository(tmp_path)
    manager = GlossaryManager(repository, novel_id)
    manager.add(GlossaryTerm("Shadow Sovereign", EntityType.ABILITY))
    manager.add(GlossaryTerm("shadow sovereign", EntityType.ABILITY))
    assert len(manager.list_terms()) == 1
    manager.update("Shadow Sovereign", translation="Shadow Sovereign", status=GlossaryStatus.CONFIRMED)
    manager.lock("shadow sovereign")
    manager.add_entity(Entity("Shadow Sovereign", EntityType.OTHER, translation="Other"))
    item = manager.get("SHADOW SOVEREIGN")
    assert item.translation == "Shadow Sovereign" and item.locked


def test_context_builder_selects_relevant_terms_and_previous_chunk():
    chunk = Chunk(1, 2, "Shadow Sovereign crossed Eldoria.")
    previous = [Chunk(1, 1, "Alicia waited.")]
    terms = [GlossaryTerm("Shadow Sovereign", EntityType.ABILITY), GlossaryTerm("Other", EntityType.ITEM)]
    entities = [Entity("Eldoria", EntityType.LOCATION), Entity("Unknown", EntityType.OTHER)]
    context = ContextBuilder().build("Novel", "Chapter", 1, chunk, previous, terms, entities)
    assert [term.term for term in context.glossary_terms] == ["Shadow Sovereign"]
    assert [entity.text for entity in context.entities] == ["Eldoria"]
    assert context.previous_chunk_text == "Alicia waited."
