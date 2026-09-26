from dataclasses import dataclass, field
from typing import Any

from noveltranslator.core.models import Entity, GlossaryTerm


@dataclass(frozen=True)
class TranslationRequest:
    source_text: str
    source_language: str
    target_language: str
    novel_title: str
    chapter_title: str
    chapter_number: int
    chunk_index: int
    previous_context: str | None = None
    glossary_terms: list[GlossaryTerm] = field(default_factory=list)
    protected_terms: list[GlossaryTerm] = field(default_factory=list)
    entities: list[Entity] = field(default_factory=list)
    translation_style: str = "natural literary Spanish"


@dataclass(frozen=True)
class TranslationResult:
    translated_text: str
    translator_id: str
    model_id: str
    source_language: str
    target_language: str
    metadata: dict[str, Any] = field(default_factory=dict)
    elapsed_seconds: float | None = None
    warnings: list[str] = field(default_factory=list)
