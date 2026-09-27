import re
from collections import Counter
from collections.abc import Iterable

from noveltranslator.core.enums import EntityStatus, EntityType
from noveltranslator.core.models import Entity


class EntityExtractor:
    """Small deterministic candidate extractor; it deliberately avoids NLP/LLMs."""

    _phrase_pattern = re.compile(r"\b(?:[A-Z][A-Za-z'’-]+(?:\s+[A-Z][A-Za-z'’-]+)+)\b")
    _word_pattern = re.compile(r"\b[A-Z][A-Za-z'’-]{2,}\b")
    _expression_pattern = re.compile(r"\b[\w]+(?:[-–—][\w]+)+\b|\b[A-Z]{2,6}\b(?=\s*(?:[!.?]+|$))", re.UNICODE)
    _common = {"The", "This", "That", "When", "After", "Before", "Chapter", "There", "Their", "However", "Then", "But", "And", "She", "He", "They", "Where"}

    def extract(self, paragraphs: Iterable[str], *, chapter_number: int | None = None) -> list[Entity]:
        text = "\n".join(paragraphs)
        phrases = self._phrase_pattern.findall(text)
        words = self._word_pattern.findall(text)
        expressions = self._expression_pattern.findall(text)
        counts = Counter(phrases + words)
        candidates = []
        for term, count in counts.items():
            if term in self._common or (term in words and count < 2 and term not in phrases):
                continue
            candidates.append(Entity(term, EntityType.OTHER, min(0.95, 0.55 + count * 0.1), False, None, EntityStatus.CANDIDATE, chapter_number, None))
        candidate_texts = {item.text for item in candidates}
        for expression in expressions:
            if expression in candidate_texts:
                continue
            candidates.append(Entity(expression, EntityType.EXPRESSION, 0.65, False, None, EntityStatus.CANDIDATE, chapter_number, None))
        return sorted(candidates, key=lambda entity: (-len(entity.text), entity.text.casefold()))

