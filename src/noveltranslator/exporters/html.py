from html import escape

from .base import ExportBook, ExportRequest, ExportResult, chapter_heading
from .utils import prepare_output, result


class HtmlExporter:
    format_id = "html"

    def export(self, request: ExportRequest, book: ExportBook) -> ExportResult:
        destination = prepare_output(request)
        chapters = []
        for chapter in book.chapters:
            paragraphs = "".join(f"<p>{escape(paragraph)}</p>" for paragraph in chapter.paragraphs)
            chapters.append(f"<article><h2>{escape(chapter_heading(chapter))}</h2>{paragraphs}</article>")
        author = escape(book.author or "")
        html = "<!doctype html>\n<html lang=\"es\">\n<head><meta charset=\"UTF-8\"><title>" + escape(book.title) + "</title><style>body{max-width:48rem;margin:2rem auto;padding:0 1rem;font-family:serif;line-height:1.6}h1{text-align:center}article{margin-top:3rem}</style></head>\n<body><h1>" + escape(book.title) + "</h1><p>Author: " + author + "</p>" + "".join(chapters) + "</body>\n</html>\n"
        destination.write_text(html, encoding="utf-8")
        return result(request, book)
