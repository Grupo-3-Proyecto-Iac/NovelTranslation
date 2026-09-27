from collections import Counter

from noveltranslator.core.models import Chunk, GlossaryTerm
from noveltranslator.storage.repository import NovelRepository
from noveltranslator.storage.serialization import utc_now_iso
from .chunk_validator import ChunkValidator
from .models import ValidationIssue, ValidationResult, ValidationStatus


class ChapterValidator:
    def __init__(self, repository: NovelRepository, *, chunk_validator: ChunkValidator | None = None) -> None:
        self.repository = repository
        self.chunk_validator = chunk_validator or ChunkValidator()

    def validate_chapter(self, novel_id: str, chapter_number: int, translation_id: str = "default") -> ValidationResult:
        chunks_payload = self.repository.load_chunks(novel_id, chapter_number)
        expected = [Chunk(**item) for item in chunks_payload.get("chunks", [])]
        expected_indices = [chunk.index for chunk in expected]
        actual_indices = self.repository.list_translation_chunks(novel_id, chapter_number, translation_id)
        issues: list[ValidationIssue] = []
        results: list[ValidationResult] = []
        metadata = self.repository.load_chapter_metadata(novel_id, chapter_number)
        glossary_payload = self.repository.load_glossary(novel_id)
        glossary = [GlossaryTerm(**item) for item in glossary_payload.get("terms", [])]
        if len(actual_indices) != len(set(actual_indices)):
            issues.append(ValidationIssue("DUPLICATE_CHUNK", ValidationStatus.FAILED, "Duplicate translation chunk indexes detected.", chapter_number=chapter_number))
        missing = sorted(set(expected_indices) - set(actual_indices))
        for index in missing:
            issues.append(ValidationIssue("MISSING_CHUNK", ValidationStatus.FAILED, f"Missing translation chunk: {index}.", chapter_number, index))
        unexpected = sorted(set(actual_indices) - set(expected_indices))
        for index in unexpected:
            issues.append(ValidationIssue("DUPLICATE_CHUNK", ValidationStatus.FAILED, f"Unexpected translation chunk: {index}.", chapter_number, index))
        for chunk in expected:
            if chunk.index not in actual_indices:
                continue
            translation = self.repository.load_translation_chunk(novel_id, chapter_number, translation_id, chunk.index)
            expected_metadata = {"chapter_number": chapter_number, "chunk_index": chunk.index, "translation_id": translation_id}
            result = self.chunk_validator.validate(chunk.source_text, translation.get("translated_text", ""), chapter_number=chapter_number, chunk_index=chunk.index, expected_source_hash=chunks_payload.get("source_hash"), actual_source_hash=translation.get("source_hash"), metadata=translation, expected_metadata=expected_metadata, glossary_terms=glossary)
            results.append(result)
        errors = issues + [issue for result in results for issue in result.errors]
        warnings = [issue for result in results for issue in result.warnings]
        status = ValidationStatus.FAILED if errors else ValidationStatus.WARNING if warnings else ValidationStatus.OK
        metrics = {"expected_chunks": len(expected_indices), "validated_chunks": len(results), "missing_chunks": len(missing), "source_hash": chunks_payload.get("source_hash")}
        return ValidationResult(status, errors, warnings, metrics, utc_now_iso(), translation_id, chapter_number, bool(warnings))
