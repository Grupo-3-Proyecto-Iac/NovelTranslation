import re
import unicodedata


def slugify(value: str, max_length: int = 80) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii").lower()
    normalized = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-.")
    normalized = normalized[:max_length].strip("-.")
    return normalized or "novel"


def chapter_directory_name(number: int, width: int = 3) -> str:
    if number < 1:
        raise ValueError("chapter number must be positive")
    return str(number).zfill(max(width, len(str(number))))
