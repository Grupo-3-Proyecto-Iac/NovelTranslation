from urllib.parse import urljoin

from bs4 import BeautifulSoup

from noveltranslator.core.models import Novel

from .selectors import AUTHOR, COVER, DESCRIPTION, NOVEL_TITLE


def _first_text(soup: BeautifulSoup, selectors: tuple[str, ...]) -> str | None:
    for selector in selectors:
        node = soup.select_one(selector)
        if node is None:
            continue
        if node.name == "meta":
            value = node.get("content")
        else:
            value = node.get_text(" ", strip=True)
        if value:
            return value.strip()
    return None


def parse_novel_metadata(html: str, source_url: str) -> Novel:
    soup = BeautifulSoup(html, "lxml")
    title = _first_text(soup, NOVEL_TITLE)
    if title and title.lower().endswith(" - lorenovels"):
        title = title[:-len(" - lorenovels")].strip()
    if not title:
        raise ValueError("Novel metadata not found: title")
    headings = [node.get_text(" ", strip=True) for node in soup.select("h2.wp-block-heading")]
    author = _first_text(soup, ("[rel='author']",))
    if not author and len(headings) > 1 and headings[1].lower() not in {"eastern, romance, fantasy"}:
        author = headings[1]
    description = _first_text(soup, DESCRIPTION)
    if description and description.lower().startswith("title:"):
        description = None
    cover = _first_text(soup, COVER)
    return Novel(
        id=source_url.rstrip("/").rsplit("/", 1)[-1], title=title, author=author,
        language="en", description=description, cover_url=urljoin(source_url, cover) if cover else None,
        source="lorenovels", source_url=source_url, chapters=[],
    )
