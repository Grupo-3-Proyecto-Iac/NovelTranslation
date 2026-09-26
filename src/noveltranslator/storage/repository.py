"""Filesystem repositories for novels, chapters, artifacts, and progress."""

from pathlib import Path
from typing import Any

from noveltranslator.core.models import Chapter, ChapterState, Novel, NovelProgress
from noveltranslator.core.exceptions import ChapterNotFoundError, NovelNotFoundError

from .identifiers import chapter_directory_name, slugify
from .serialization import read_json, utc_now_iso, write_json_atomic


class NovelRepository:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()

    def _novel_id(self, novel_id: str) -> str:
        candidate = Path(novel_id)
        if candidate.name != novel_id or novel_id in {"", ".", ".."}:
            raise ValueError("novel_id must be a single safe filesystem component")
        resolved = (self.root / novel_id).resolve()
        if self.root not in resolved.parents:
            raise ValueError("novel_id escapes the novels directory")
        return novel_id

    def _dir(self, novel_id: str) -> Path:
        return self.root / self._novel_id(novel_id)

    def create_novel(self, novel: Novel, novel_id: str | None = None) -> str:
        identifier = self._novel_id(novel_id or slugify(novel.id or novel.title))
        directory = self._dir(identifier)
        directory.mkdir(parents=True, exist_ok=True)
        now = utc_now_iso()
        metadata = {"id": identifier, "title": novel.title, "author": novel.author, "language": novel.language, "description": novel.description, "cover_url": novel.cover_url, "source": novel.source, "source_url": novel.source_url, "created_at": now, "updated_at": now}
        if not (directory / "metadata.json").exists():
            write_json_atomic(directory / "metadata.json", metadata)
        for filename, initial in (("glossary.json", {"terms": []}), ("translation_memory.json", {"entries": []})):
            if not (directory / filename).exists():
                write_json_atomic(directory / filename, initial)
        return identifier

    def novel_exists(self, novel_id: str) -> bool:
        return (self._dir(novel_id) / "metadata.json").is_file()

    def _require(self, novel_id: str) -> Path:
        directory = self._dir(novel_id)
        if not (directory / "metadata.json").is_file():
            raise NovelNotFoundError(f"Novel not found: {novel_id}")
        return directory

    def save_novel_metadata(self, novel_id: str, metadata: dict[str, Any]) -> None:
        directory = self._require(novel_id)
        current = self.load_novel_metadata(novel_id)
        current.update(metadata)
        current["updated_at"] = utc_now_iso()
        write_json_atomic(directory / "metadata.json", current)

    def load_novel_metadata(self, novel_id: str) -> dict[str, Any]:
        return read_json(self._require(novel_id) / "metadata.json")

    def create_chapter(self, novel_id: str, chapter: Chapter) -> Path:
        directory = self._require(novel_id) / "chapters" / chapter_directory_name(chapter.number)
        directory.mkdir(parents=True, exist_ok=True)
        metadata_path = directory / "metadata.json"
        if not metadata_path.exists():
            write_json_atomic(metadata_path, {"number": chapter.number, "title": chapter.title, "url": chapter.url, "status": chapter.status.value, "updated_at": utc_now_iso()})
        return directory

    def chapter_exists(self, novel_id: str, number: int) -> bool:
        return (self._require(novel_id) / "chapters" / chapter_directory_name(number) / "metadata.json").is_file()

    def _chapter_dir(self, novel_id: str, number: int) -> Path:
        directory = self._require(novel_id) / "chapters" / chapter_directory_name(number)
        if not directory.is_dir():
            raise ChapterNotFoundError(f"Chapter not found: {novel_id}/{number}")
        return directory

    def save_chapter_metadata(self, novel_id: str, number: int, metadata: dict[str, Any]) -> None:
        directory = self._chapter_dir(novel_id, number)
        current = read_json(directory / "metadata.json") if (directory / "metadata.json").exists() else {"number": number}
        current.update(metadata)
        current["updated_at"] = utc_now_iso()
        write_json_atomic(directory / "metadata.json", current)

    def load_chapter_metadata(self, novel_id: str, number: int) -> dict[str, Any]:
        return read_json(self._chapter_dir(novel_id, number) / "metadata.json")

    def save_source(self, novel_id: str, number: int, language: str, paragraphs: list[str]) -> None:
        write_json_atomic(self._chapter_dir(novel_id, number) / "source.json", {"language": language, "paragraphs": paragraphs, "stored_at": utc_now_iso()})

    def load_source(self, novel_id: str, number: int) -> dict[str, Any]:
        return read_json(self._chapter_dir(novel_id, number) / "source.json")

    def source_exists(self, novel_id: str, number: int) -> bool:
        return (self._chapter_dir(novel_id, number) / "source.json").is_file()

    def save_analysis(self, novel_id: str, number: int, analysis: Any) -> None:
        write_json_atomic(self._chapter_dir(novel_id, number) / "analysis.json", analysis)

    def load_analysis(self, novel_id: str, number: int) -> Any:
        return read_json(self._chapter_dir(novel_id, number) / "analysis.json")

    def analysis_exists(self, novel_id: str, number: int) -> bool:
        return (self._chapter_dir(novel_id, number) / "analysis.json").is_file()

    def _translation_path(self, novel_id: str, number: int, translation_id: str, chunk_index: int) -> Path:
        return self._chapter_dir(novel_id, number) / "translations" / slugify(translation_id, 40) / f"chunk_{chunk_index:03d}.json"

    def save_translation_chunk(self, novel_id: str, number: int, translation_id: str, chunk: dict[str, Any]) -> None:
        write_json_atomic(self._translation_path(novel_id, number, translation_id, int(chunk["chunk_index"])), chunk)

    def load_translation_chunk(self, novel_id: str, number: int, translation_id: str, chunk_index: int) -> dict[str, Any]:
        return read_json(self._translation_path(novel_id, number, translation_id, chunk_index))

    def translation_chunk_exists(self, novel_id: str, number: int, translation_id: str, chunk_index: int) -> bool:
        return self._translation_path(novel_id, number, translation_id, chunk_index).is_file()

    def save_progress(self, progress: NovelProgress | dict[str, Any], novel_id: str | None = None) -> None:
        identifier = novel_id or progress.novel_id
        self._require(identifier)
        write_json_atomic(self._dir(identifier) / "progress.json", progress)

    def load_progress(self, novel_id: str) -> dict[str, Any]:
        return read_json(self._require(novel_id) / "progress.json")

    def progress_exists(self, novel_id: str) -> bool:
        return (self._require(novel_id) / "progress.json").is_file()

    def list_novels(self) -> list[str]:
        return sorted(path.name for path in self.root.iterdir() if path.is_dir() and (path / "metadata.json").is_file()) if self.root.exists() else []

    def list_chapters(self, novel_id: str) -> list[int]:
        chapters = self._require(novel_id) / "chapters"
        return sorted(int(path.name) for path in chapters.iterdir() if path.is_dir() and path.name.isdigit()) if chapters.is_dir() else []

    def inspect_novel_state(self, novel_id: str) -> list[ChapterState]:
        states = []
        for number in self.list_chapters(novel_id):
            directory = self._chapter_dir(novel_id, number)
            chunks = []
            translations = directory / "translations"
            for path in translations.glob("*/chunk_*.json") if translations.is_dir() else []:
                try:
                    chunks.append(int(path.stem.split("_")[-1]))
                except ValueError:
                    continue
            states.append(ChapterState(number, (directory / "source.json").is_file(), (directory / "analysis.json").is_file(), tuple(sorted(set(chunks)))))
        return states
