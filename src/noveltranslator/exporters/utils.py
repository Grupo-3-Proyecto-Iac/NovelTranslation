from pathlib import Path

from noveltranslator.core.exceptions import ExportError
from noveltranslator.storage.serialization import utc_now_iso

from .base import ExportBook, ExportRequest, ExportResult


def prepare_output(request: ExportRequest) -> Path:
    destination = Path(request.destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and not request.overwrite:
        raise ExportError(f"Export file already exists; pass --overwrite: {destination}")
    return destination


def result(request: ExportRequest, book: ExportBook, warnings: list[str] | None = None) -> ExportResult:
    return ExportResult(Path(request.destination), request.destination.suffix.lstrip("."), len(book.chapters), 0, warnings or [], utc_now_iso())
