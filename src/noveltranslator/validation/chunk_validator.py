import re
from typing import Any

from noveltranslator.core.models import GlossaryTerm
from .heuristics import has_invalid_unicode, untranslated_ratio, words
from .models import ValidationIssue, ValidationResult, ValidationStatus


PLACEHOLDER_RE = re.compile(r"__NT_TERM_[A-Z0-9_]+__")


class ChunkValidator:
    def __init__(self, *, min_length_ratio: float = 0.35, max_length_ratio: float = 2.50, untranslated_threshold: float = 0.30, untranslated_enabled: bool = True, locked_missing_is_failure: bool = True) -> None:
        self.min_length_ratio = min_length_ratio
        self.max_length_ratio = max_length_ratio
        self.untranslated_threshold = untranslated_threshold
        self.untranslated_enabled = untranslated_enabled
        self.locked_missing_is_failure = locked_missing_is_failure

    def validate(self, source_text: str, translated_text: str, *, chapter_number: int, chunk_index: int, expected_source_hash: str | None = None, actual_source_hash: str | None = None, metadata: dict[str, Any] | None = None, expected_metadata: dict[str, Any] | None = None, glossary_terms: list[GlossaryTerm] | None = None) -> ValidationResult:
        errors: list[ValidationIssue] = []
        warnings: list[ValidationIssue] = []
        metadata = metadata or {}
        glossary_terms = glossary_terms or []
        def issue(code: str, severity: ValidationStatus, message: str, **extra: Any) -> None:
            target = errors if severity is ValidationStatus.FAILED else warnings
            target.append(ValidationIssue(code, severity, message, chapter_number, chunk_index, extra))

        if not isinstance(translated_text, str) or not translated_text.strip():
            issue("EMPTY_TRANSLATION", ValidationStatus.FAILED, "Translation is empty.")
        else:
            if PLACEHOLDER_RE.search(translated_text):
                issue("PLACEHOLDER_LEAK", ValidationStatus.FAILED, "Internal protected-term placeholder remains.")
            if has_invalid_unicode(translated_text):
                issue("INVALID_UNICODE", ValidationStatus.FAILED, "Translation contains invalid Unicode.")
            source_length = len(source_text.strip())
            translated_length = len(translated_text.strip())
            ratio = translated_length / source_length if source_length else 0.0
            source_words = len(words(source_text))
            translated_words = len(words(translated_text))
            metrics = {"source_characters": source_length, "translated_characters": translated_length, "length_ratio": ratio, "source_words": source_words, "translated_words": translated_words}
            if ratio < self.min_length_ratio or ratio > self.max_length_ratio:
                issue("SUSPICIOUS_LENGTH_RATIO", ValidationStatus.WARNING, "Translation length ratio is outside the configured range.", ratio=ratio)
            expected_terms = sorted((term for term in glossary_terms if term.locked or term.preserve), key=lambda term: len(term.term), reverse=True)
            normalized_translation = " ".join(translated_text.split()).casefold()
            covered: list[str] = []
            for term in expected_terms:
                source_present = term.term.casefold() in " ".join(source_text.split()).casefold()
                if not source_present or any(term.term.casefold() in longer.casefold() for longer in covered):
                    continue
                expected = term.term if term.preserve or not term.translation else term.translation
                if expected.casefold() not in normalized_translation:
                    code = "LOCKED_TERM_MISSING" if term.locked else "LOCKED_TERM_CHANGED"
                    severity = ValidationStatus.FAILED if term.locked and self.locked_missing_is_failure else ValidationStatus.WARNING
                    issue(code, severity, f"Protected term missing or changed: {term.term}", expected=expected)
                covered.append(term.term)
            excluded = {term.term for term in expected_terms} | {term.translation for term in glossary_terms if term.translation}
            ratio_untranslated = untranslated_ratio(translated_text, excluded)
            metrics["possible_untranslated_ratio"] = ratio_untranslated
            if self.untranslated_enabled and ratio_untranslated >= self.untranslated_threshold and len(words(translated_text)) >= 3:
                issue("POSSIBLE_UNTRANSLATED_TEXT", ValidationStatus.WARNING, "Possible untranslated English detected.", ratio=ratio_untranslated)
        if expected_source_hash is not None and actual_source_hash != expected_source_hash:
            issue("SOURCE_HASH_MISMATCH", ValidationStatus.FAILED, "Translation does not match the current source hash.", expected=expected_source_hash, actual=actual_source_hash)
        if expected_metadata:
            for key, expected in expected_metadata.items():
                if key in metadata and metadata[key] != expected:
                    issue("TRANSLATION_METADATA_MISMATCH", ValidationStatus.FAILED, f"Translation metadata mismatch: {key}.", field=key, expected=expected, actual=metadata[key])
        status = ValidationStatus.FAILED if errors else ValidationStatus.WARNING if warnings else ValidationStatus.OK
        return ValidationResult(status, errors, warnings, locals().get("metrics", {}), translation_id=str(metadata.get("translation_id", "default")), chapter_number=chapter_number, needs_review=bool(warnings))
