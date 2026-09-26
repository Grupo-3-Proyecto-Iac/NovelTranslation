import logging
from urllib.parse import urlparse

from noveltranslator.access.manager import AccessManager
from noveltranslator.access.models import AccessStatus
from noveltranslator.core.enums import ProcessingState
from noveltranslator.core.exceptions import AccessBlockedError, ChapterContentNotFoundError, NovelMetadataNotFoundError
from noveltranslator.core.models import Chapter, Novel

from .metadata import parse_novel_metadata
from .parser import CHAPTER_PATTERN, parse_chapter_content, parse_chapter_title, parse_chapters

logger = logging.getLogger("noveltranslator.sources.lorenovels")


class LorenovelsSource:
    name = "Lorenovels"
    source_id = "lorenovels"
    domains = ("lorenovels.com",)

    def __init__(self, access_manager: AccessManager | None = None) -> None:
        self.access_manager = access_manager or AccessManager()

    def can_handle(self, url: str) -> bool:
        parsed = urlparse(url)
        hostname = (parsed.hostname or "").lower().rstrip(".")
        if hostname.startswith("www."):
            hostname = hostname[4:]
        return parsed.scheme in {"http", "https"} and hostname in self.domains

    def get_novel(self, url: str) -> Novel:
        self._validate_url(url)
        logger.info("Fetching novel page: %s", url)
        response = self.access_manager.fetch(url)
        self._ensure_access(response.access_status, url)
        try:
            novel = parse_novel_metadata(response.text, response.final_url)
        except ValueError as exc:
            raise NovelMetadataNotFoundError(str(exc)) from exc
        logger.info("Novel metadata parsed: %s", novel.title)
        return novel

    def get_chapters(self, novel: Novel) -> list[Chapter]:
        response = self.access_manager.fetch(novel.source_url)
        self._ensure_access(response.access_status, novel.source_url)
        chapters = parse_chapters(response.text, novel.source_url)
        novel.chapters = chapters
        logger.info("Chapter list parsed: %s (%d chapters)", novel.title, len(chapters))
        return chapters

    def get_chapter(self, chapter: Chapter) -> Chapter:
        logger.info("Fetching chapter: %s", chapter.url)
        response = self.access_manager.fetch(chapter.url)
        self._ensure_access(response.access_status, chapter.url)
        try:
            paragraphs = parse_chapter_content(response.text)
        except (ChapterContentNotFoundError, ValueError):
            raise
        if not paragraphs:
            raise ChapterContentNotFoundError(f"Chapter content not found: {chapter.url}")
        title = chapter.title or parse_chapter_title(response.text) or chapter.title
        result = Chapter(chapter.number, title, chapter.url, ProcessingState.DOWNLOADED, paragraphs, chapter.chapter_type, chapter.order_index)
        logger.info("Chapter parsed: %s (%d paragraphs)", chapter.title, len(paragraphs))
        return result

    @staticmethod
    def chapter_number_from_url(url: str) -> int:
        match = CHAPTER_PATTERN.search(url)
        return int(match.group(1)) if match else 0

    @staticmethod
    def _validate_url(url: str) -> None:
        parsed = urlparse(url)
        hostname = (parsed.hostname or "").lower().rstrip(".")
        if hostname.startswith("www."):
            hostname = hostname[4:]
        if parsed.scheme not in {"http", "https"} or hostname != "lorenovels.com":
            raise ValueError("URL is not a Lorenovels URL")

    @staticmethod
    def _ensure_access(status: AccessStatus, url: str) -> None:
        blocked = {AccessStatus.CAPTCHA_REQUIRED, AccessStatus.FORBIDDEN, AccessStatus.RATE_LIMITED, AccessStatus.LOGIN_REQUIRED, AccessStatus.JAVASCRIPT_REQUIRED}
        if status in blocked:
            raise AccessBlockedError(f"Lorenovels access blocked ({status.value}): {url}")
        if status not in {AccessStatus.OK, AccessStatus.REDIRECTED}:
            raise AccessBlockedError(f"Lorenovels access failed ({status.value}): {url}")
