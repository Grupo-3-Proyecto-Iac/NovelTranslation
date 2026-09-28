import hashlib
import re
from collections.abc import Iterable


class TextNormalizer:
    """Performs conservative structural cleanup without rewriting prose."""

    _MOJIBAKE_MARKERS = ("Ã", "Â", "â", "ð", "�")

    @classmethod
    def repair_mojibake(cls, text: str) -> str:
        """Repair common UTF-8/Windows-1252 decoding errors conservatively."""
        if not isinstance(text, str):
            return text

        def score(value: str) -> int:
            return sum(value.count(marker) for marker in cls._MOJIBAKE_MARKERS)

        repaired = text
        for _ in range(2):
            before = score(repaired)
            if before == 0:
                break
            try:
                candidate = repaired.encode("cp1252").decode("utf-8")
            except (UnicodeEncodeError, UnicodeDecodeError):
                break
            if score(candidate) >= before:
                break
            repaired = candidate
        return repaired

    def normalize(self, paragraphs: Iterable[str]) -> list[str]:
        result = []
        for paragraph in paragraphs:
            if not isinstance(paragraph, str):
                continue
            cleaned = self.repair_mojibake(paragraph).replace("\r\n", "\n").replace("\r", "\n").strip()
            if cleaned:
                result.append(cleaned)
        return result

    def source_hash(self, paragraphs: Iterable[str]) -> str:
        normalized = self.normalize(paragraphs)
        payload = "\n".join(normalized).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


def source_hash(paragraphs: Iterable[str]) -> str:
    return TextNormalizer().source_hash(paragraphs)

