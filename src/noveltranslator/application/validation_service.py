import logging
from dataclasses import asdict

from noveltranslator.core.enums import ProcessingState
from noveltranslator.storage.progress_manager import ProgressManager
from noveltranslator.storage.repository import NovelRepository
from noveltranslator.validation.chapter_validator import ChapterValidator
from noveltranslator.validation.chunk_validator import ChunkValidator
from noveltranslator.validation.models import ValidationResult, ValidationStatus, ValidationSummary

logger = logging.getLogger("noveltranslator.application.validation")


class ValidationService:
    def __init__(self, repository: NovelRepository, *, chunk_validator: ChunkValidator | None = None) -> None:
        self.repository = repository
        self.chapter_validator = ChapterValidator(repository, chunk_validator=chunk_validator)

    def validate_chapter(self, novel_id: str, chapter_number: int, translation_id: str = "default", *, progress: ProgressManager | None = None, reuse_existing: bool = False) -> ValidationResult:
        if reuse_existing and self.repository.validation_exists(novel_id, chapter_number, translation_id):
            stored = self.repository.load_validation_result(novel_id, chapter_number, translation_id)
            current_hash = self.repository.load_chunks(novel_id, chapter_number).get("source_hash")
            if stored.get("metrics", {}).get("source_hash") == current_hash and stored.get("translation_id", translation_id) == translation_id:
                return self._result_from_dict(stored)
        if progress:
            progress.set_current_chapter(chapter_number)
            progress.set_stage(ProcessingState.VALIDATING)
        logger.info("Validation started: %s/%03d", novel_id, chapter_number)
        result = self.chapter_validator.validate_chapter(novel_id, chapter_number, translation_id)
        self.repository.save_validation_result(novel_id, chapter_number, translation_id, asdict(result))
        self.repository.save_chapter_metadata(novel_id, chapter_number, {"status": ProcessingState.COMPLETED.value if result.status is not ValidationStatus.FAILED else ProcessingState.FAILED.value, "needs_review": result.needs_review})
        logger.info("Validation result persisted: %s/%03d (%s)", novel_id, chapter_number, result.status)
        if progress:
            if result.status is ValidationStatus.FAILED:
                progress.mark_chapter_failed(chapter_number, ValueError("chapter validation failed"))
            else:
                progress.mark_chapter_completed(chapter_number)
        return result

    def validate_novel(self, novel_id: str, *, translation_id: str = "default", limit: int | None = None, from_chapter: int | None = None, to_chapter: int | None = None, reuse_existing: bool = False) -> ValidationSummary:
        if limit is not None and limit < 1:
            raise ValueError("limit must be positive")
        progress = ProgressManager(self.repository, novel_id)
        progress.start_novel()
        summary = ValidationSummary(novel_id)
        for number in self.repository.list_chapters(novel_id):
            if from_chapter is not None and number < from_chapter or to_chapter is not None and number > to_chapter:
                continue
            if not self.repository.list_translation_chunks(novel_id, number, translation_id):
                continue
            if limit is not None and summary.chapters_total >= limit:
                break
            try:
                result = self.validate_chapter(novel_id, number, translation_id, progress=progress, reuse_existing=reuse_existing)
            except KeyboardInterrupt:
                progress.pause()
                logger.warning("Validation paused: %s/%03d", novel_id, number)
                break
            summary.chapters_total += 1
            if result.status is ValidationStatus.OK:
                summary.ok += 1
            elif result.status is ValidationStatus.WARNING:
                summary.warnings += 1
            else:
                summary.failed += 1
            if result.needs_review:
                summary.needs_review += 1
            for issue in result.errors + result.warnings:
                summary.issues_by_code[issue.code] = summary.issues_by_code.get(issue.code, 0) + 1
        if summary.failed:
            progress.fail()
        elif summary.chapters_total:
            progress.complete()
        return summary

    @staticmethod
    def _result_from_dict(data: dict) -> ValidationResult:
        from noveltranslator.validation.models import ValidationIssue
        errors = [ValidationIssue(**item) for item in data.get("errors", [])]
        warnings = [ValidationIssue(**item) for item in data.get("warnings", [])]
        return ValidationResult(ValidationStatus(data["status"]), errors, warnings, data.get("metrics", {}), data.get("validated_at", ""), data.get("translation_id", "default"), data.get("chapter_number"), data.get("needs_review", False))
