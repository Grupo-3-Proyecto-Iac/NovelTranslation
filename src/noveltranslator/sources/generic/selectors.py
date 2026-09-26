from dataclasses import dataclass


@dataclass(frozen=True)
class SelectorConfig:
    title: str | None = None
    author: str | None = None
    description: str | None = None
    chapter_links: str | None = None
    chapter_content: str | None = None

