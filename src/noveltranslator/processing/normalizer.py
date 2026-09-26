import hashlib
import re
from collections.abc import Iterable


class TextNormalizer:
    """Performs conservative structural cleanup without rewriting prose."""

    def normalize(self, paragraphs: Iterable[str]) -> list[str]:
        result = []
        for paragraph in paragraphs:
            if not isinstance(paragraph, str):
                continue
            cleaned = re.sub(r"\s+", " ", paragraph).strip()
            if cleaned:
                result.append(cleaned)
        return result

    def source_hash(self, paragraphs: Iterable[str]) -> str:
        normalized = self.normalize(paragraphs)
        payload = "\n".join(normalized).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


def source_hash(paragraphs: Iterable[str]) -> str:
    return TextNormalizer().source_hash(paragraphs)

