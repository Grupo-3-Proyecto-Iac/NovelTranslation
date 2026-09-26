from pathlib import Path

import pytest

from noveltranslator.access.models import AccessResponse, AccessStatus
from noveltranslator.core.exceptions import AccessBlockedError, ChapterContentNotFoundError
from noveltranslator.core.models import Chapter
from noveltranslator.sources.lorenovels import LorenovelsSource
from noveltranslator.sources.lorenovels.metadata import parse_novel_metadata
from noveltranslator.sources.lorenovels.parser import parse_chapter_content, parse_chapters
from noveltranslator.sources.loader import default_registry


FIXTURES = Path(__file__).parents[1] / "fixtures" / "lorenovels"
NOVEL_URL = "https://lorenovels.com/surviving-in-a-romance-fantasy-novel/"


def response(url: str, text: str, status=AccessStatus.OK) -> AccessResponse:
    return AccessResponse(url, url, 200 if status in {AccessStatus.OK, AccessStatus.REDIRECTED} else 403, {"content-type": "text/html"}, text, 0.1, status, 1, len(text))


class FakeAccess:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def fetch(self, url):
        self.calls.append(url)
        return self.pages[url]


def test_can_handle_validates_hostname():
    source = LorenovelsSource(FakeAccess({}))
    assert source.can_handle("https://lorenovels.com/foo")
    assert source.can_handle("http://www.lorenovels.com/foo")
    assert not source.can_handle("https://example.com/foo")
    assert not source.can_handle("https://lorenovels.com.attacker.example/foo")


def test_metadata_and_chapters_are_parsed_from_fixture():
    html = (FIXTURES / "novel_page.html").read_text(encoding="utf-8")
    novel = parse_novel_metadata(html, NOVEL_URL)
    assert (novel.title, novel.author, novel.language) == ("Surviving in a Romance Fantasy Novel", "Korita", "en")
    assert novel.cover_url == "https://lorenovels.com/covers/example.webp"
    chapters = parse_chapters(html, NOVEL_URL)
    assert [chapter.number for chapter in chapters] == [0, 1, 2, 10]
    assert chapters[0].chapter_type == "prologue"
    assert chapters[1].url == "https://lorenovels.com/chapter-1-start/"


def test_chapter_content_preserves_inline_text_and_removes_irrelevant_nodes():
    html = (FIXTURES / "chapter_page.html").read_text(encoding="utf-8")
    assert parse_chapter_content(html) == ["The room was silent.", '"Where am I?"', "He slowly opened his eyes."]


def test_empty_chapter_raises_specific_error():
    with pytest.raises(ChapterContentNotFoundError):
        parse_chapter_content("<html><body><main></main></body></html>")


def test_source_uses_access_manager_and_returns_chapter():
    novel_html = (FIXTURES / "novel_page.html").read_text(encoding="utf-8")
    chapter_html = (FIXTURES / "chapter_page.html").read_text(encoding="utf-8")
    chapter_url = "https://lorenovels.com/chapter-1-start/"
    access = FakeAccess({NOVEL_URL: response(NOVEL_URL, novel_html), chapter_url: response(chapter_url, chapter_html)})
    source = LorenovelsSource(access)
    novel = source.get_novel(NOVEL_URL)
    chapter = source.get_chapter(Chapter(1, "", chapter_url))
    assert novel.source == "lorenovels"
    assert chapter.title == "Chapter 1: Start"
    assert chapter.status.value == "DOWNLOADED"
    assert access.calls == [NOVEL_URL, chapter_url]


def test_source_does_not_parse_blocked_page():
    url = "https://lorenovels.com/chapter-1-start/"
    access = FakeAccess({url: response(url, "verify you are human", AccessStatus.CAPTCHA_REQUIRED)})
    with pytest.raises(AccessBlockedError):
        LorenovelsSource(access).get_chapter(Chapter(1, "", url))


def test_registry_contains_lorenovels():
    source = default_registry().resolve(NOVEL_URL)
    assert isinstance(source, LorenovelsSource)
