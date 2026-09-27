import json
from pathlib import Path

from noveltranslator.application.analysis_service import AnalysisService
from noveltranslator.application.download_service import DownloadService
from noveltranslator.application.export_service import ExportService
from noveltranslator.application.translation_service import TranslationService
from noveltranslator.application.validation_service import ValidationService
from noveltranslator.core.enums import GlossaryStatus, ProcessingState
from noveltranslator.core.models import Chapter, GlossaryTerm, Novel
from noveltranslator.processing.splitter import TextSplitter
from noveltranslator.storage.repository import NovelRepository
from noveltranslator.sources.registry import SourceRegistry
from noveltranslator.translators import MockTranslator, TranslatorRegistry
from noveltranslator.validation.chunk_validator import ChunkValidator


class E2ESource:
    name = "E2E Mock Source"
    source_id = "e2e"

    def __init__(self) -> None:
        self.chapters = [Chapter(1, "First", "https://e2e.test/1"), Chapter(2, "Second", "https://e2e.test/2"), Chapter(3, "Third", "https://e2e.test/3")]
        self.contents = {1: ["Alicia entered the castle.", "She activated Shadow Sovereign."], 2: ["Ethan saw Alicia.", "Alicia waved at Ethan."], 3: ["They arrived at the Kingdom of Eldoria.", "The kingdom was quiet."]}
        self.chapter_calls: list[int] = []

    def can_handle(self, url: str) -> bool:
        return url.startswith("https://e2e.test/novel")

    def get_novel(self, url: str) -> Novel:
        return Novel("e2e-novel", "The Example Novel", "Author", "en", "Fixture", None, "e2e", url)

    def get_chapters(self, novel: Novel) -> list[Chapter]:
        return list(self.chapters)

    def get_chapter(self, chapter: Chapter) -> Chapter:
        self.chapter_calls.append(chapter.number)
        return Chapter(chapter.number, chapter.title, chapter.url, ProcessingState.DOWNLOADED, self.contents[chapter.number])


class InterruptingTranslator(MockTranslator):
    def __init__(self) -> None:
        super().__init__()
        self.interrupted = False

    def translate(self, request):
        if request.chapter_number == 2 and request.chunk_index == 2 and not self.interrupted:
            self.interrupted = True
            raise KeyboardInterrupt
        return super().translate(request)


def registry_for(translator: MockTranslator) -> TranslatorRegistry:
    registry = TranslatorRegistry()
    registry.register(translator)
    return registry


def test_full_local_pipeline_resume_idempotency_and_exports(tmp_path: Path) -> None:
    root = tmp_path / "datos-ñ"
    repository = NovelRepository(root / "novels")
    source = E2ESource()
    source_registry = SourceRegistry()
    source_registry.register(source)
    download = DownloadService(source_registry, repository)

    downloaded = download.download_novel("https://e2e.test/novel")
    assert downloaded.completed and source.chapter_calls == [1, 2, 3]
    analysis = AnalysisService(repository, splitter=TextSplitter(max_characters=100, target_characters=20, overlap_paragraphs=0))
    analyzed = analysis.analyze_novel("e2e-novel")
    assert analyzed.completed and analyzed.analyzed_now == 3
    repository.save_glossary("e2e-novel", {"terms": [GlossaryTerm("Alicia", "CHARACTER", "Alicia", True, GlossaryStatus.LOCKED), GlossaryTerm("Shadow Sovereign", "ABILITY", "Shadow Sovereign", True, GlossaryStatus.LOCKED), GlossaryTerm("Kingdom of Eldoria", "LOCATION", "Reino de Eldoria", True, GlossaryStatus.LOCKED)]})

    interrupted = InterruptingTranslator()
    first_translation = TranslationService(repository, registry_for(interrupted)).translate_novel("e2e-novel")
    assert first_translation.paused
    assert repository.translation_chunk_exists("e2e-novel", 2, "default", 1)
    assert not repository.translation_chunk_exists("e2e-novel", 2, "default", 2)

    resumed_translator = MockTranslator()
    resumed = TranslationService(repository, registry_for(resumed_translator)).translate_novel("e2e-novel")
    assert resumed.completed
    assert resumed_translator.calls < sum(len(repository.list_translation_chunks("e2e-novel", number, "default")) for number in (1, 2, 3))
    assert source.chapter_calls == [1, 2, 3]

    validation = ValidationService(repository, chunk_validator=ChunkValidator(untranslated_enabled=False)).validate_novel("e2e-novel", translation_id="default")
    assert validation.failed == 0 and validation.ok == 3
    export_service = ExportService(repository)
    outputs = [export_service.export_novel("e2e-novel", format_id=format_id, overwrite=True).output_path for format_id in ("txt", "json", "html", "epub")]
    assert all(path.is_file() and path.stat().st_size > 0 for path in outputs)
    payload = json.loads(outputs[1].read_text(encoding="utf-8"))
    assert [chapter["number"] for chapter in payload["chapters"]] == [1, 2, 3]
    assert "Reino de Eldoria" in outputs[0].read_text(encoding="utf-8") or "Kingdom of Eldoria" in outputs[0].read_text(encoding="utf-8")

    source.chapter_calls.clear()
    second_download = download.download_novel("https://e2e.test/novel")
    second_analysis = analysis.analyze_novel("e2e-novel")
    second_translation = TranslationService(repository, registry_for(MockTranslator())).translate_novel("e2e-novel")
    assert second_download.downloaded_now == 0 and source.chapter_calls == []
    assert second_analysis.analyzed_now == 0
    assert second_translation.chunks_translated == 0
