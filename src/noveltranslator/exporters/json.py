import json

from .base import ExportBook, ExportRequest, ExportResult
from .utils import prepare_output, result


class JsonExporter:
    format_id = "json"

    def export(self, request: ExportRequest, book: ExportBook) -> ExportResult:
        destination = prepare_output(request)
        payload = {"novel": {"id": book.novel_id, "title": book.title, "author": book.author, "source_language": book.source_language, "target_language": book.target_language, "translation_id": book.translation_id, "source": book.source}, "chapters": [{"number": chapter.number, "title": chapter.title, "text": chapter.text, "validation_status": chapter.validation_status} for chapter in book.chapters]}
        destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return result(request, book)
