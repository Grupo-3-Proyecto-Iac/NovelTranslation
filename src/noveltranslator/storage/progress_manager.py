from dataclasses import replace

from noveltranslator.core.enums import NovelStatus, ProcessingState
from noveltranslator.core.models import NovelProgress

from .repository import NovelRepository
from .serialization import utc_now_iso


class ProgressManager:
    def __init__(self, repository: NovelRepository, novel_id: str) -> None:
        self.repository = repository
        self.novel_id = novel_id
        if repository.progress_exists(novel_id):
            data = repository.load_progress(novel_id)
            self.progress = NovelProgress(
                novel_id=novel_id,
                overall_status=NovelStatus(data.get("overall_status", NovelStatus.PENDING)),
                current_chapter=data.get("current_chapter"), current_stage=ProcessingState(data["current_stage"]) if data.get("current_stage") else None,
                current_chunk=data.get("current_chunk"), total_chunks=data.get("total_chunks"),
                last_completed_chapter=data.get("last_completed_chapter"), updated_at=data.get("updated_at", ""),
                error_type=data.get("error_type"), error_message=data.get("error_message"),
            )
        else:
            self.progress = NovelProgress(novel_id=novel_id)

    def _save(self) -> NovelProgress:
        self.progress = replace(self.progress, updated_at=utc_now_iso())
        self.repository.save_progress(self.progress)
        return self.progress

    def start_novel(self) -> NovelProgress:
        self.progress = replace(self.progress, overall_status=NovelStatus.IN_PROGRESS, error_type=None, error_message=None)
        return self._save()

    def set_current_chapter(self, chapter: int, total_chunks: int | None = None) -> NovelProgress:
        self.progress = replace(self.progress, current_chapter=chapter, current_chunk=None, total_chunks=total_chunks)
        return self._save()

    def set_stage(self, stage: ProcessingState) -> NovelProgress:
        self.progress = replace(self.progress, current_stage=stage)
        return self._save()

    def set_chunk_progress(self, chunk: int, total_chunks: int | None = None) -> NovelProgress:
        self.progress = replace(self.progress, current_chunk=chunk, total_chunks=total_chunks or self.progress.total_chunks)
        return self._save()

    def mark_chapter_completed(self, chapter: int) -> NovelProgress:
        self.progress = replace(self.progress, last_completed_chapter=chapter, current_chapter=None, current_chunk=None, current_stage=ProcessingState.COMPLETED)
        return self._save()

    def mark_analysis_completed(self, chapter: int) -> NovelProgress:
        self.progress = replace(self.progress, last_completed_chapter=chapter, current_chapter=None, current_chunk=None, current_stage=ProcessingState.ANALYZED, error_type=None, error_message=None)
        return self._save()

    def pause(self) -> NovelProgress:
        self.progress = replace(self.progress, overall_status=NovelStatus.PAUSED)
        return self._save()

    def fail(self) -> NovelProgress:
        self.progress = replace(self.progress, overall_status=NovelStatus.FAILED, current_stage=ProcessingState.FAILED)
        return self._save()

    def mark_chapter_failed(self, chapter: int, error: Exception) -> NovelProgress:
        self.progress = replace(self.progress, overall_status=NovelStatus.FAILED, current_chapter=chapter, current_stage=ProcessingState.FAILED, error_type=type(error).__name__, error_message=str(error)[:500])
        return self._save()

    def complete(self) -> NovelProgress:
        self.progress = replace(self.progress, overall_status=NovelStatus.COMPLETED, current_stage=ProcessingState.COMPLETED)
        return self._save()
