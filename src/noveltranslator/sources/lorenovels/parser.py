import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from noveltranslator.core.exceptions import ChapterContentNotFoundError, InvalidChapterContentError
from noveltranslator.core.models import Chapter
from noveltranslator.core.enums import ProcessingState

from .selectors import CHAPTER_CONTENT, CHAPTER_LINKS, REMOVE_SELECTORS

CHAPTER_PATTERN = re.compile(r"\bchapter\s*(\d+)\b", re.IGNORECASE)
SPECIALS = {"prologue": ("prologue", 0), "epilogue": ("epilogue", 0), "side story": ("side-story", 0), "extra": ("extra", 0), "interlude": ("interlude", 0)}


def _chapter_identity(text: str) -> tuple[int, str, int]:
    match = CHAPTER_PATTERN.search(text)
    if match:
        return int(match.group(1)), "chapter", int(match.group(1))
    lowered = text.lower()
    for marker, (chapter_type, order) in SPECIALS.items():
        if marker in lowered:
            return 0, chapter_type, order
    return 0, "special", 0


def parse_chapters(html: str, source_url: str) -> list[Chapter]:
    soup = BeautifulSoup(html, "lxml")
    found: list[Chapter] = []
    seen: set[str] = set()
    for link in soup.select(CHAPTER_LINKS):
        title = link.get_text(" ", strip=True)
        href = link.get("href")
        if not href or not title or not (CHAPTER_PATTERN.search(title) or any(marker in title.lower() for marker in SPECIALS)):
            continue
        url = urljoin(source_url, href)
        if url in seen:
            continue
        seen.add(url)
        number, chapter_type, order = _chapter_identity(title)
        found.append(Chapter(number, title, url, ProcessingState.PENDING, [], chapter_type, order))
    numeric = sorted((chapter for chapter in found if chapter.chapter_type == "chapter"), key=lambda item: item.number)
    special = [chapter for chapter in found if chapter.chapter_type != "chapter"]
    special.sort(key=lambda item: (item.order_index or 0, item.title.lower()))
    for index, chapter in enumerate(special + numeric):
        chapter.order_index = index
    return special + numeric


def parse_chapter_content(html: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    container = next((soup.select_one(selector) for selector in CHAPTER_CONTENT if soup.select_one(selector)), None)
    if container is None:
        raise ChapterContentNotFoundError("Chapter content not found: content container")
    for selector in REMOVE_SELECTORS:
        for node in container.select(selector):
            node.decompose()
    paragraphs = []
    for node in container.select("p"):
        text = " ".join(node.get_text(" ", strip=True).split())
        text = re.sub(r"\s+([,.;:!?])", r"\1", text)
        if text and text.lower() not in {"published on", "share this:"}:
            paragraphs.append(text)
    if not paragraphs:
        raise InvalidChapterContentError("Chapter content is empty")
    return paragraphs


def parse_chapter_title(html: str) -> str | None:
    soup = BeautifulSoup(html, "lxml")
    node = soup.select_one("h1.wp-block-post-title") or soup.select_one("h1")
    return node.get_text(" ", strip=True) if node else None
