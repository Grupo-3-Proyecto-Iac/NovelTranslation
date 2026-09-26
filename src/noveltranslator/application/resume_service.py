from noveltranslator.core.enums import NovelStatus, ProcessingState
from noveltranslator.core.models import PendingJob
from noveltranslator.storage.repository import NovelRepository


class ResumeService:
    def __init__(self, repository: NovelRepository) -> None:
        self.repository = repository

    def find_pending_jobs(self) -> list[PendingJob]:
        jobs = []
        for novel_id in self.repository.list_novels():
            if not self.repository.progress_exists(novel_id):
                continue
            progress = self.repository.load_progress(novel_id)
            if progress.get("overall_status") == NovelStatus.COMPLETED.value:
                continue
            if progress.get("current_chapter") is not None or progress.get("overall_status") == NovelStatus.PAUSED.value:
                jobs.append(PendingJob(novel_id, progress.get("current_chapter"), ProcessingState(progress["current_stage"]) if progress.get("current_stage") else None, progress.get("current_chunk"), progress.get("total_chunks")))
        return jobs

