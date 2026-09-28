from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from noveltranslator.access.browser_client import BrowserClient
from noveltranslator.core.models import Chapter
from noveltranslator.sources.lorenovels.parser import parse_chapter_content


@dataclass(frozen=True)
class CaptureSummary:
    novel_id: str
    captured: int
    skipped: int
    failed: int
    output_directory: Path


class BrowserCaptureService:
    """Captures visible chapter HTML using one persistent browser page.

    The service only stores a page when the chapter parser can find real
    chapter paragraphs in the returned DOM. It does not bypass access
    controls or retry indefinitely.
    """

    def __init__(self, browser: BrowserClient, output_root: Path) -> None:
        self.browser = browser
        self.output_root = Path(output_root)

    def capture(
        self,
        novel,
        chapters: list[Chapter],
        *,
        from_chapter: int | None = None,
        to_chapter: int | None = None,
        delay_seconds: float = 30.0,
        overwrite: bool = False,
    ) -> CaptureSummary:
        selected = [
            chapter for chapter in chapters
            if (from_chapter is None or chapter.number >= from_chapter)
            and (to_chapter is None or chapter.number <= to_chapter)
        ]
        output_directory = self.output_root / novel.id
        output_directory.mkdir(parents=True, exist_ok=True)
        captured = skipped = failed = 0

        for position, chapter in enumerate(selected):
            target = output_directory / f"{chapter.number:03d}.html"
            if target.exists() and not overwrite:
                skipped += 1
                print(f"HTML omitido: capítulo {chapter.number:03d} ya existe")
                continue
            if position and delay_seconds > 0:
                print(f"Esperando {delay_seconds:.0f} segundos antes del siguiente capítulo...")
                time.sleep(delay_seconds)

            print(f"Abriendo capítulo {chapter.number:03d}: {chapter.title}")
            response = self.browser.fetch(chapter.url)
            try:
                paragraphs = parse_chapter_content(response.text)
            except Exception as error:
                paragraphs = []
                print(f"HTML no contiene un capítulo procesable: {type(error).__name__}")
            if not paragraphs:
                failed += 1
                print(f"Captura detenida en capítulo {chapter.number:03d}: acceso bloqueado o contenido no visible")
                break
            target.write_text(response.text, encoding="utf-8")
            captured += 1
            print(f"HTML guardado: {target}")

        return CaptureSummary(novel.id, captured, skipped, failed, output_directory)
