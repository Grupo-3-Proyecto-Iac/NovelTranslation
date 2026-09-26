from dataclasses import dataclass, field
from typing import Any

from .enums import EntityStatus, EntityType, GlossaryStatus, NovelStatus, ProcessingState


@dataclass
class Chapter:
    number: int
    title: str
    url: str
    status: ProcessingState = ProcessingState.PENDING
    paragraphs: list[str] = field(default_factory=list)
    chapter_type: str = "chapter"
    order_index: int | None = None


@dataclass
class Novel:
    id: str
    title: str
    author: str | None
    language: str
    description: str | None
    cover_url: str | None
    source: str
    source_url: str
    chapters: list[Chapter] = field(default_factory=list)


@dataclass
class Chunk:
    chapter_number: int
    index: int
    source_text: str
    paragraph_start: int | None = None
    paragraph_end: int | None = None
    previous_context: str | None = None
    next_context: str | None = None


@dataclass
class Entity:
    text: str
    type: EntityType
    confidence: float | None = None
    preserve: bool = False
    translation: str | None = None
    status: EntityStatus = EntityStatus.CANDIDATE
    first_seen_chapter: int | None = None
    first_seen_chunk: int | None = None


@dataclass
class GlossaryTerm:
    term: str
    type: EntityType | str
    translation: str | None = None
    locked: bool = False
    status: GlossaryStatus = GlossaryStatus.PROPOSED
    source: str | None = None
    preserve: bool = False
    first_seen_chapter: int | None = None
    first_seen_chunk: int | None = None


@dataclass
class TranslationMemoryEntry:
    id: str
    source_text: str
    translated_text: str
    source_language: str
    target_language: str
    chapter_number: int | None
    chunk_index: int | None
    created_at: str
    source_hash: str | None
    translation_id: str
    status: str = "ACTIVE"
    preferred: bool = False
    usage_count: int = 0
    last_used_at: str | None = None
    confidence: float | None = None


@dataclass
class ContextMemoryItem:
    id: str
    text: str
    chapter_number: int
    entities: list[str] = field(default_factory=list)
    source_hash: str | None = None
    translation_id: str = "default"
    status: str = "ACTIVE"
    created_at: str = ""


@dataclass
class ChapterContext:
    chapter_number: int
    summary: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    source_hash: str | None = None
    translation_id: str = "default"
    updated_at: str = ""


@dataclass
class ProgressRecord:
    novel_id: str
    chapter_number: int | None
    task: str
    chunk_index: int | None
    state: ProcessingState
    updated_at: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class NovelProgress:
    novel_id: str
    overall_status: NovelStatus = NovelStatus.PENDING
    current_chapter: int | None = None
    current_stage: ProcessingState | None = None
    current_chunk: int | None = None
    total_chunks: int | None = None
    last_completed_chapter: int | None = None
    updated_at: str = ""
    error_type: str | None = None
    error_message: str | None = None
    translation_id: str | None = None


@dataclass(frozen=True)
class PendingJob:
    novel_id: str
    chapter: int | None
    stage: ProcessingState | None
    chunk: int | None
    total_chunks: int | None = None


@dataclass(frozen=True)
class ChapterState:
    number: int
    source_exists: bool
    analysis_exists: bool
    translation_chunks: tuple[int, ...] = ()

