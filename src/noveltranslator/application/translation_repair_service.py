"""Local repairs for translation artifacts already persisted on disk."""

from dataclasses import dataclass
import re

from noveltranslator.processing.glossary import GlossaryManager
from noveltranslator.storage.repository import NovelRepository
from noveltranslator.storage.serialization import utc_now_iso


@dataclass(frozen=True)
class TranslationRepairSummary:
    novel_id: str
    translation_id: str
    chunks_scanned: int
    chunks_changed: int
    chapters_changed: int
    replacements: int


class TranslationRepairService:
    """Apply safe, idempotent glossary corrections without a model or network."""

    # Compatibility variants for chunks generated before this glossary term
    # was locked. New translations use the glossary directly.
    _KNOWN_VARIANTS: dict[str, tuple[str, ...]] = {
        "vermilion princess": (
            "Vermilion Princess",
            "Vermillion Princess",
            "Princesa Vermilion",
            "Princesa Vermilión",
            "Vermillón Princesa",
        ),
    }

    def __init__(self, repository: NovelRepository) -> None:
        self.repository = repository

    @staticmethod
    def _replacement_patterns(term: str, translation: str) -> list[tuple[re.Pattern[str], str]]:
        key = " ".join(term.casefold().split())
        variants = list(TranslationRepairService._KNOWN_VARIANTS.get(key, ()))
        if term not in variants:
            variants.insert(0, term)
        patterns: list[tuple[str, str]] = []

        # Avoid producing "The Princesa ..." for the known English title.
        if key == "vermilion princess":
            patterns.extend(
                [
                    (r"\bthe\s+vermilion\s+princess\b", f"La {translation}"),
                    (r"\ba\s+vermilion\s+princess\b", f"Una {translation}"),
                    (r"\blas\s+Princesas\s+Azure\s+como\s+las\s+Vermilion\b", f"la Princesa Azure y la {translation}"),
                ]
            )
        for variant in sorted(variants, key=len, reverse=True):
            patterns.append((rf"(?<!\w){re.escape(variant)}(?!\w)", translation))
        return [(re.compile(pattern, re.IGNORECASE), value) for pattern, value in patterns]

    def repair_novel(
        self,
        novel_id: str,
        translation_id: str,
        *,
        from_chapter: int | None = None,
        to_chapter: int | None = None,
        dry_run: bool = False,
    ) -> TranslationRepairSummary:
        terms = [
            term
            for term in GlossaryManager(self.repository, novel_id).list_terms()
            if term.locked and term.translation
        ]
        patterns = [
            pattern
            for term in terms
            for pattern in self._replacement_patterns(term.term, str(term.translation))
        ]
        chapters = [
            number
            for number in self.repository.list_chapters(novel_id)
            if (from_chapter is None or number >= from_chapter)
            and (to_chapter is None or number <= to_chapter)
        ]
        scanned = changed = changed_chapters = replacements = 0
        for number in chapters:
            chapter_changed = False
            for chunk_index in self.repository.list_translation_chunks(novel_id, number, translation_id):
                scanned += 1
                chunk = self.repository.load_translation_chunk(novel_id, number, translation_id, chunk_index)
                original = str(chunk.get("translated_text", ""))
                repaired = original
                chunk_replacements = 0
                for pattern, replacement in patterns:
                    repaired, count = pattern.subn(replacement, repaired)
                    chunk_replacements += count
                if repaired == original:
                    continue
                changed += 1
                replacements += chunk_replacements
                chapter_changed = True
                if not dry_run:
                    chunk["translated_text"] = repaired
                    chunk["postprocessed_at"] = utc_now_iso()
                    chunk["postprocessing"] = "locked-glossary-repair"
                    self.repository.save_translation_chunk(novel_id, number, translation_id, chunk)
            if chapter_changed:
                changed_chapters += 1
        return TranslationRepairSummary(novel_id, translation_id, scanned, changed, changed_chapters, replacements)
