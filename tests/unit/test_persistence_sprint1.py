import json

import pytest

from noveltranslator.application.resume_service import ResumeService
from noveltranslator.core.enums import NovelStatus, ProcessingState
from noveltranslator.core.exceptions import CorruptedDataError
from noveltranslator.core.models import Chapter, Novel, NovelProgress
from noveltranslator.storage.identifiers import chapter_directory_name, slugify
from noveltranslator.storage.progress_manager import ProgressManager
from noveltranslator.storage.repository import NovelRepository
from noveltranslator.storage.serialization import write_json_atomic


def make_repository(tmp_path):
    repository = NovelRepository(tmp_path / "novels")
    novel = Novel("", "Título / Seguro", "Autor", "en", None, None, "mock", "https://example.test/novel")
    novel_id = repository.create_novel(novel)
    return repository, novel_id


def test_novel_and_chapter_storage(tmp_path):
    repository, novel_id = make_repository(tmp_path)
    assert novel_id == "titulo-seguro"
    assert repository.novel_exists(novel_id)
    repository.save_novel_metadata(novel_id, {"author": "Nuevo autor"})
    assert repository.load_novel_metadata(novel_id)["author"] == "Nuevo autor"

    repository.create_chapter(novel_id, Chapter(1000, "Mil", "https://example.test/1000"))
    repository.save_chapter_metadata(novel_id, 1000, {"status": ProcessingState.DOWNLOADED.value})
    assert repository.chapter_exists(novel_id, 1000)
    assert repository.load_chapter_metadata(novel_id, 1000)["status"] == "DOWNLOADED"
    assert repository.list_chapters(novel_id) == [1000]


def test_source_analysis_translation_are_separate_and_unicode_safe(tmp_path):
    repository, novel_id = make_repository(tmp_path)
    repository.create_chapter(novel_id, Chapter(1, "Capítulo", "url"))
    paragraphs = ["áéíóú ñ", "한글 日本語"]
    repository.save_source(novel_id, 1, "en", paragraphs)
    repository.save_analysis(novel_id, 1, {"future": "not analyzed"})
    repository.save_translation_chunk(novel_id, 1, "default", {"chapter_number": 1, "chunk_index": 1, "source_text": paragraphs[0], "translated_text": "Texto"})
    assert repository.load_source(novel_id, 1)["paragraphs"] == paragraphs
    assert repository.analysis_exists(novel_id, 1)
    assert repository.translation_chunk_exists(novel_id, 1, "default", 1)
    assert not (tmp_path / "novels" / novel_id / "chapters" / "001" / "source.json").read_text(encoding="utf-8").__contains__("translated_text")


def test_multiple_translation_profiles_and_inspection(tmp_path):
    repository, novel_id = make_repository(tmp_path)
    repository.create_chapter(novel_id, Chapter(1, "One", "url"))
    repository.save_source(novel_id, 1, "en", ["source"])
    for profile, index in (("default", 1), ("nllb", 2)):
        repository.save_translation_chunk(novel_id, 1, profile, {"chapter_number": 1, "chunk_index": index, "translated_text": "ok"})
    state = repository.inspect_novel_state(novel_id)[0]
    assert state.source_exists and not state.analysis_exists
    assert state.translation_chunks == (1, 2)


def test_progress_manager_persists_and_reloads(tmp_path):
    repository, novel_id = make_repository(tmp_path)
    manager = ProgressManager(repository, novel_id)
    manager.start_novel()
    manager.set_current_chapter(3, total_chunks=9)
    manager.set_stage(ProcessingState.TRANSLATING)
    manager.set_chunk_progress(2)
    reloaded = ProgressManager(repository, novel_id).progress
    assert reloaded.overall_status is NovelStatus.IN_PROGRESS
    assert (reloaded.current_chapter, reloaded.current_chunk, reloaded.total_chunks) == (3, 2, 9)
    manager.pause()
    assert repository.load_progress(novel_id)["overall_status"] == "PAUSED"


def test_resume_ignores_completed_and_finds_incomplete(tmp_path):
    repository, novel_id = make_repository(tmp_path)
    repository.save_progress(NovelProgress(novel_id, NovelStatus.COMPLETED))
    other = NovelRepository(tmp_path / "novels")
    other_id = other.create_novel(Novel("other", "Other", None, "en", None, None, "mock", "url"))
    other.save_progress(NovelProgress(other_id, NovelStatus.IN_PROGRESS, 3, ProcessingState.TRANSLATING, 2, 9))
    jobs = ResumeService(repository).find_pending_jobs()
    assert [(job.novel_id, job.chapter, job.chunk) for job in jobs] == [(other_id, 3, 2)]


def test_corruption_and_path_safety(tmp_path):
    repository, novel_id = make_repository(tmp_path)
    (tmp_path / "novels" / novel_id / "metadata.json").write_text("{bad", encoding="utf-8")
    with pytest.raises(CorruptedDataError, match="metadata.json"):
        repository.load_novel_metadata(novel_id)
    with pytest.raises(ValueError):
        repository.novel_exists("../../outside")


def test_atomic_write_leaves_final_json_and_no_temp_file(tmp_path):
    target = tmp_path / "nested" / "data.json"
    write_json_atomic(target, {"text": "ñ"})
    assert json.loads(target.read_text(encoding="utf-8")) == {"text": "ñ"}
    assert list(target.parent.glob("*.tmp")) == []


def test_identifiers_are_safe_and_padded():
    assert slugify("Surviving in a Romance Fantasy Novel") == "surviving-in-a-romance-fantasy-novel"
    assert ".." not in slugify("../../bad\\name")
    assert chapter_directory_name(1) == "001"
    assert chapter_directory_name(1000) == "1000"
