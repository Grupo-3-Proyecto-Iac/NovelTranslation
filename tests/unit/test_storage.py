from noveltranslator.storage.filesystem import JsonFilesystemRepository
from noveltranslator.storage.chapter_storage import chapter_directory


def test_json_repository_saves_and_loads(tmp_path) -> None:
    repository = JsonFilesystemRepository(tmp_path)
    repository.save_json("novel/metadata.json", {"title": "Test"})
    assert repository.exists("novel/metadata.json")
    assert repository.load_json("novel/metadata.json") == {"title": "Test"}


def test_chapter_directories_are_padded() -> None:
    assert chapter_directory(1) == "chapters/001"
    assert chapter_directory(10) == "chapters/010"

