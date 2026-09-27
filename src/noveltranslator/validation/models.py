from dataclasses import dataclass, field
from typing import Any

from noveltranslator.core.enums import ValidationStatus
from noveltranslator.storage.serialization import utc_now_iso


@dataclass
class ValidationIssue:
    code: str
    severity: ValidationStatus
    message: str
    chapter_number: int | None = None
    chunk_index: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidationResult:
    status: ValidationStatus
    errors: list[ValidationIssue] = field(default_factory=list)
    warnings: list[ValidationIssue] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    validated_at: str = field(default_factory=utc_now_iso)
    translation_id: str = "default"
    chapter_number: int | None = None
    needs_review: bool = False


@dataclass
class ValidationSummary:
    novel_id: str
    chapters_total: int = 0
    ok: int = 0
    warnings: int = 0
    failed: int = 0
    needs_review: int = 0
    issues_by_code: dict[str, int] = field(default_factory=dict)
