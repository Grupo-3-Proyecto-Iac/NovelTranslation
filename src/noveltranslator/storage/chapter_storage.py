from noveltranslator.core.models import Chapter

from .filesystem import JsonFilesystemRepository
from .serialization import utc_now_iso


def chapter_directory(chapter_number: int) -> str:
    return f"chapters/{chapter_number:03d}"


class ChapterStorage:
    def __init__(self, repository: JsonFilesystemRepository) -> None:
        self.repository = repository

    def save_metadata(self, chapter: Chapter) -> None:
        self.repository.save_json(
            f"{chapter_directory(chapter.number)}/metadata.json",
            {"number": chapter.number, "title": chapter.title, "url": chapter.url, "status": chapter.status.value, "updated_at": utc_now_iso()},
        )

