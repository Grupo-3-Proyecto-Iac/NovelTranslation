"""Small, local and auditable translation/context memory services."""

from __future__ import annotations

import hashlib
import logging
import re

from noveltranslator.core.models import ContextMemoryItem, TranslationMemoryEntry
from noveltranslator.storage.repository import NovelRepository
from noveltranslator.storage.serialization import utc_now_iso

logger = logging.getLogger("noveltranslator.processing.memory")


def normalized_key(value: str) -> str:
    return " ".join(value.strip().split()).casefold()


class MemoryManager:
    def __init__(self, repository: NovelRepository, novel_id: str) -> None:
        self.repository = repository
        self.novel_id = novel_id

    def load_translation_memory(self) -> list[TranslationMemoryEntry]:
        return [TranslationMemoryEntry(**item) for item in self.repository.load_translation_memory(self.novel_id).get("entries", [])]

    def save_translation_memory(self, entries: list[TranslationMemoryEntry]) -> None:
        self.repository.save_translation_memory(self.novel_id, {"entries": entries, "updated_at": utc_now_iso()})

    def add_translation_entry(self, entry: TranslationMemoryEntry) -> TranslationMemoryEntry:
        entries = self.load_translation_memory()
        same_source = [item for item in entries if normalized_key(item.source_text) == normalized_key(entry.source_text) and item.source_language == entry.source_language and item.target_language == entry.target_language and item.translation_id == entry.translation_id]
        exact = next((item for item in same_source if normalized_key(item.translated_text) == normalized_key(entry.translated_text)), None)
        if exact:
            exact.usage_count += 1
            exact.last_used_at = utc_now_iso()
            if exact.status == "STALE" and entry.source_hash == exact.source_hash:
                exact.status = "ACTIVE"
            self.save_translation_memory(entries)
            return exact
        if same_source:
            for item in same_source:
                if item.status == "ACTIVE":
                    item.status = "CONFLICT"
            entry.status = "CONFLICT"
            logger.warning("Memory conflict detected: %s", entry.source_text)
        self.save_translation_memory(entries + [entry])
        logger.info("Translation memory entry added: %s", entry.source_text)
        return entry

    def find_exact(self, source_text: str, source_language: str, target_language: str, translation_id: str = "default", source_hash: str | None = None) -> TranslationMemoryEntry | None:
        entries = self.load_translation_memory()
        changed = False
        matches = []
        for entry in entries:
            if normalized_key(entry.source_text) != normalized_key(source_text) or entry.source_language != source_language or entry.target_language != target_language or entry.translation_id != translation_id:
                continue
            if source_hash and entry.source_hash and entry.source_hash != source_hash and entry.status != "STALE":
                entry.status = "STALE"
                changed = True
                logger.warning("Stale memory detected: %s", entry.source_text)
                continue
            if entry.status in {"ACTIVE", "CONFLICT"}:
                matches.append(entry)
        if changed:
            self.save_translation_memory(entries)
        if not matches:
            return None
        preferred = next((item for item in matches if item.preferred), None)
        result = preferred or next((item for item in matches if item.status == "ACTIVE"), matches[0])
        result.usage_count += 1
        result.last_used_at = utc_now_iso()
        self.save_translation_memory(entries)
        logger.info("Memory entry reused: %s", source_text)
        return result

    def find_relevant(self, text: str, *, source_language: str | None = None, target_language: str | None = None, translation_id: str = "default", max_items: int = 20, source_hash: str | None = None) -> list[TranslationMemoryEntry]:
        words = set(re.findall(r"[\w'-]+", text.casefold()))
        candidates = []
        for entry in self.load_translation_memory():
            if entry.status != "ACTIVE" or entry.translation_id != translation_id:
                continue
            if source_language and entry.source_language != source_language or target_language and entry.target_language != target_language:
                continue
            if source_hash and entry.source_hash and entry.source_hash != source_hash:
                continue
            overlap = len(words.intersection(set(re.findall(r"[\w'-]+", entry.source_text.casefold()))))
            if overlap:
                candidates.append((overlap, entry.usage_count, entry))
        candidates.sort(key=lambda value: (-value[0], -value[1], value[2].created_at))
        return [item for _, _, item in candidates[:max(0, max_items)]]

    def mark_stale_for_chapter(self, chapter_number: int, source_hash: str) -> int:
        entries = self.load_translation_memory()
        changed = 0
        for entry in entries:
            if entry.chapter_number == chapter_number and entry.source_hash and entry.source_hash != source_hash and entry.status != "STALE":
                entry.status = "STALE"
                changed += 1
        if changed:
            self.save_translation_memory(entries)
            logger.warning("Marked %d stale memory entries for chapter %s", changed, chapter_number)
        return changed

    def load_context_memory(self) -> list[ContextMemoryItem]:
        return [ContextMemoryItem(**item) for item in self.repository.load_context_memory(self.novel_id).get("items", [])]

    def save_context_memory(self, items: list[ContextMemoryItem]) -> None:
        self.repository.save_context_memory(self.novel_id, {"items": items, "updated_at": utc_now_iso()})

    def add_context_item(self, text: str, chapter_number: int, entities: list[str] | None = None, *, source_hash: str | None = None, translation_id: str = "default") -> ContextMemoryItem:
        entities = entities or []
        item_id = hashlib.sha1(f"{chapter_number}|{normalized_key(text)}|{translation_id}".encode("utf-8")).hexdigest()[:16]
        items = self.load_context_memory()
        existing = next((item for item in items if item.id == item_id), None)
        if existing:
            existing.source_hash = source_hash or existing.source_hash
            existing.entities = sorted(set(existing.entities + entities))
            self.save_context_memory(items)
            return existing
        item = ContextMemoryItem(item_id, text, chapter_number, sorted(set(entities)), source_hash, translation_id, "ACTIVE", utc_now_iso())
        self.save_context_memory(items + [item])
        logger.info("Context item added: chapter %s", chapter_number)
        return item

    def find_context(self, text: str, *, chapter_number: int | None = None, translation_id: str = "default", previous_chapters: int = 2, max_items: int = 20) -> list[ContextMemoryItem]:
        words = set(re.findall(r"[\w'-]+", text.casefold()))
        scored = []
        for item in self.load_context_memory():
            if item.status != "ACTIVE" or item.translation_id != translation_id:
                continue
            if chapter_number is not None and item.chapter_number > chapter_number:
                continue
            if chapter_number is not None and item.chapter_number < chapter_number - max(0, previous_chapters):
                continue
            overlap = len(words.intersection({word.casefold() for entity in item.entities for word in re.findall(r"[\w'-]+", entity)}))
            if overlap or normalized_key(item.text) in normalized_key(text):
                proximity = abs((chapter_number or item.chapter_number) - item.chapter_number)
                scored.append((overlap, -proximity, item))
        scored.sort(key=lambda value: (-value[0], -value[1], value[2].chapter_number))
        return [item for _, _, item in scored[:max(0, max_items)]]


class TranslationMemory(MemoryManager):
    """Backward-compatible name for the original placeholder class."""

