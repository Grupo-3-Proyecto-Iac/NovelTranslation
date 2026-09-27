from .base import ExportBook, ExportRequest, ExportResult
from .utils import prepare_output, result


class TxtExporter:
    format_id = "txt"

    def export(self, request: ExportRequest, book: ExportBook) -> ExportResult:
        destination = prepare_output(request)
        lines = [book.title, "", f"Author: {book.author or '-'}", f"Translation: {book.translation_id}", "", "=" * 32, ""]
        for chapter in book.chapters:
            lines.extend([f"Chapter {chapter.number} — {chapter.title}", "", chapter.text, "", "=" * 32, ""])
        destination.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        return result(request, book)
