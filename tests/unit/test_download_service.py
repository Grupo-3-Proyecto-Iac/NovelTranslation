from pathlib import Path

import pytest

from noveltranslator.application.download_service import DownloadService
from noveltranslator.core.enums import ProcessingState
from noveltranslator.core.models import Chapter, Novel, NovelProgress
from noveltranslator.core.enums import NovelStatus
from noveltranslator.sources.registry import SourceRegistry
from noveltranslator.storage.progress_manager import ProgressManager
from noveltranslator.storage.repository import NovelRepository


class FakeSource:
    name = "Fake"
    source_id = "fake"

    def __init__(self, count=3):
        self.chapters = [Chapter(index, f"Chapter {index}", f"https://example.test/{index}") for index in range(1, count + 1)]
        self.chapter_calls = []
        self.mode = {}

    def can_handle(self, url):
        return url.startswith("https://example.test/novel")

    def get_novel(self, url):
        return Novel("fake-novel", "Fake Novel", "Author", "en", "Description", None, "fake", url, [])

    def get_chapters(self, novel):
        return list(self.chapters)

    def get_chapter(self, chapter):
        self.chapter_calls.append(chapter.number)
        behavior = self.mode.get(chapter.number)
        if behavior == "pause":
            raise KeyboardInterrupt
        if isinstance(behavior, Exception):
            raise behavior
        return Chapter(chapter.number, chapter.title, chapter.url, ProcessingState.DOWNLOADED, [f"Original {chapter.number}", "áéñ 한글 日本語"])


def setup(tmp_path, count=3):
    source = FakeSource(count)
    registry = SourceRegistry()
    registry.register(source)
    repository = NovelRepository(tmp_path / "novels")
    service = DownloadService(registry, repository)
    return source, repository, service


def test_new_novel_registers_and_downloads_sequentially(tmp_path):
    source, repository, service = setup(tmp_path, 3)
    summary = service.download_novel("https://example.test/novel")
    assert summary.completed and summary.downloaded_now == 3
    assert source.chapter_calls == [1, 2, 3]
    assert repository.list_novels() == ["fake-novel"]
    assert repository.list_chapters("fake-novel") == [1, 2, 3]
    assert all(repository.load_chapter_metadata("fake-novel", n)["status"] == "DOWNLOADED" for n in [1, 2, 3])


def test_limit_downloads_only_pending_chapters(tmp_path):
    source, repository, service = setup(tmp_path, 10)
    summary = service.download_novel("https://example.test/novel", limit=3)
    assert (summary.downloaded_now, summary.pending) == (3, 7)
    assert source.chapter_calls == [1, 2, 3]


def test_existing_source_files_are_skipped_and_second_run_is_idempotent(tmp_path):
    source, repository, service = setup(tmp_path, 5)
    first = service.download_novel("https://example.test/novel", limit=2)
    assert first.downloaded_now == 2
    source.chapter_calls.clear()
    second = service.download_novel("https://example.test/novel")
    assert second.downloaded_now == 3
    assert second.skipped == 2
    assert source.chapter_calls == [3, 4, 5]
    source.chapter_calls.clear()
    third = service.download_novel("https://example.test/novel")
    assert third.downloaded_now == 0 and third.skipped == 5
    assert source.chapter_calls == []


def test_pause_and_resume_continue_at_interrupted_chapter(tmp_path):
    source, repository, service = setup(tmp_path, 4)
    source.mode[3] = "pause"
    paused = service.download_novel("https://example.test/novel")
    assert paused.paused and source.chapter_calls == [1, 2, 3]
    assert repository.load_chapter_metadata("fake-novel", 3)["status"] == "PAUSED"
    source.mode.clear()
    resumed = service.resume_novel("fake-novel")
    assert resumed.completed
    assert source.chapter_calls == [1, 2, 3, 3, 4]


def test_failure_stops_and_is_persisted(tmp_path):
    source, repository, service = setup(tmp_path, 4)
    source.mode[3] = RuntimeError("temporary failure")
    summary = service.download_novel("https://example.test/novel")
    assert summary.failed == 1 and not summary.completed
    assert source.chapter_calls == [1, 2, 3]
    metadata = repository.load_chapter_metadata("fake-novel", 3)
    assert metadata["status"] == "FAILED"
    assert metadata["error_type"] == "RuntimeError"
    progress = repository.load_progress("fake-novel")
    assert progress["current_chapter"] == 3 and progress["current_stage"] == "FAILED"


def test_crash_reconciliation_skips_valid_source_artifact(tmp_path):
    source, repository, service = setup(tmp_path, 3)
    novel = source.get_novel("https://example.test/novel")
    novel_id = repository.create_novel(novel)
    for chapter in source.chapters:
        repository.create_chapter(novel_id, chapter)
    repository.save_source(novel_id, 3, "en", ["already saved"])
    ProgressManager(repository, novel_id).set_current_chapter(3)
    source.chapter_calls.clear()
    summary = service.resume_novel(novel_id)
    assert source.chapter_calls == [1, 2]
    assert summary.skipped == 1
    assert repository.load_chapter_metadata(novel_id, 3)["status"] == "DOWNLOADED"


def test_new_chapters_are_added_without_deleting_old_ones(tmp_path):
    source, repository, service = setup(tmp_path, 3)
    service.download_novel("https://example.test/novel")
    source.chapters.extend([Chapter(4, "Chapter 4", "https://example.test/4"), Chapter(5, "Chapter 5", "https://example.test/5")])
    source.chapter_calls.clear()
    summary = service.download_novel("https://example.test/novel")
    assert source.chapter_calls == [4, 5]
    assert summary.downloaded_now == 2
    assert repository.list_chapters("fake-novel") == [1, 2, 3, 4, 5]


def test_metadata_refresh_preserves_created_at(tmp_path):
    source, repository, service = setup(tmp_path, 1)
    service.download_novel("https://example.test/novel")
    created = repository.load_novel_metadata("fake-novel")["created_at"]
    source.get_novel = lambda url: Novel("fake-novel", "Updated title", "New author", "en", "New description", None, "fake", url, [])
    service.download_novel("https://example.test/novel")
    metadata = repository.load_novel_metadata("fake-novel")
    assert metadata["created_at"] == created
    assert metadata["title"] == "Updated title"


def test_corrupt_source_is_not_overwritten_without_force(tmp_path):
    source, repository, service = setup(tmp_path, 1)
    novel = source.get_novel("https://example.test/novel")
    novel_id = repository.create_novel(novel)
    repository.create_chapter(novel_id, source.chapters[0])
    source_path = Path(tmp_path) / "novels" / novel_id / "chapters" / "001" / "source.json"
    source_path.write_text("{broken", encoding="utf-8")
    summary = service.download_novel("https://example.test/novel")
    assert summary.failed == 1
    assert source.chapter_calls == []
    assert source_path.read_text(encoding="utf-8") == "{broken"
