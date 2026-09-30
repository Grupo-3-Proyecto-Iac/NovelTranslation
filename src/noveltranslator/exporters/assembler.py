from noveltranslator.core.exceptions import ExportError
from noveltranslator.storage.repository import NovelRepository

from .base import ExportChapter


class ChapterAssembler:
    """Reconstructs chapters from persisted translation chunks in index order."""

    def __init__(self, repository: NovelRepository) -> None:
        self.repository = repository

    def assemble_chapter(self, novel_id: str, chapter_number: int, translation_id: str = "default", *, allow_partial: bool = False, validation_status: str = "OK") -> ExportChapter:
        metadata = self.repository.load_chapter_metadata(novel_id, chapter_number)
        chunks = self.repository.load_chunks(novel_id, chapter_number)
        expected = sorted(int(item["index"]) for item in chunks.get("chunks", []))
        actual = self.repository.list_translation_chunks(novel_id, chapter_number, translation_id)
        if expected != list(range(1, len(expected) + 1)):
            raise ExportError(f"Cannot export chapter {chapter_number}: chunk indexes are not contiguous.")
        missing = [index for index in expected if index not in actual]
        if missing and not allow_partial:
            raise ExportError(f"Cannot export chapter {chapter_number}: translation chunk {missing[0]} is missing.")
        indexes = [index for index in expected if index in actual]
        if not indexes:
            raise ExportError(f"Cannot export chapter {chapter_number}: no translated chunks are available.")
        text_parts: list[str] = []
        for index in indexes:
            data = self.repository.load_translation_chunk(novel_id, chapter_number, translation_id, index)
            if data.get("chapter_number") != chapter_number or data.get("chunk_index") != index:
                raise ExportError(f"Cannot export chapter {chapter_number}: metadata mismatch in chunk {index}.")
            text = str(data.get("translated_text", "")).strip()
            if not text:
                raise ExportError(f"Cannot export chapter {chapter_number}: chunk {index} is empty.")
            text_parts.append(text)
        text = "\n\n".join(text_parts)
        paragraphs = tuple(item.strip() for item in text.split("\n\n") if item.strip())
        title = metadata.get("translated_title") or metadata.get("title", f"Chapter {chapter_number}")
        return ExportChapter(chapter_number, str(title), text, paragraphs, validation_status)
