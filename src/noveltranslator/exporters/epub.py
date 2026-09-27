from html import escape
import mimetypes
from pathlib import Path
import uuid
from zipfile import ZIP_STORED, ZIP_DEFLATED, ZipFile

from noveltranslator.storage.serialization import utc_now_iso

from .base import ExportBook, ExportRequest, ExportResult
from .utils import prepare_output, result


class EpubExporter:
    format_id = "epub"

    def export(self, request: ExportRequest, book: ExportBook) -> ExportResult:
        destination = prepare_output(request)
        identifier = f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, book.novel_id + ':' + book.translation_id)}"
        modified = utc_now_iso().replace("+00:00", "Z")
        manifest = ["<item id=\"nav\" href=\"nav.xhtml\" media-type=\"application/xhtml+xml\" properties=\"nav\"/>", "<item id=\"css\" href=\"styles.css\" media-type=\"text/css\"/>"]
        spine = []
        nav_items = []
        chapter_files: list[tuple[str, str]] = []
        for chapter in book.chapters:
            filename = f"chapter_{chapter.number:03d}.xhtml"
            item_id = f"chapter_{chapter.number:03d}"
            chapter_files.append((filename, self._chapter_xhtml(book, chapter)))
            manifest.append(f"<item id=\"{item_id}\" href=\"{filename}\" media-type=\"application/xhtml+xml\"/>")
            spine.append(f"<itemref idref=\"{item_id}\"/>")
            nav_items.append(f"<li><a href=\"{filename}\">Chapter {chapter.number} — {escape(chapter.title)}</a></li>")
        cover_bytes = None
        cover_name = None
        if book.cover_path and book.cover_path.is_file():
            cover_name = f"images/cover{book.cover_path.suffix.lower() or '.jpg'}"
            mime = mimetypes.guess_type(book.cover_path.name)[0] or "image/jpeg"
            manifest.append(f"<item id=\"cover-image\" href=\"{cover_name}\" media-type=\"{mime}\" properties=\"cover-image\"/>")
            cover_bytes = (cover_name, book.cover_path.read_bytes())
        opf = f"""<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<package xmlns=\"http://www.idpf.org/2007/opf\" unique-identifier=\"book-id\" version=\"3.0\">
<metadata xmlns:dc=\"http://purl.org/dc/elements/1.1/\"><dc:identifier id=\"book-id\">{identifier}</dc:identifier><dc:title>{escape(book.title)}</dc:title>{f'<dc:creator>{escape(book.author)}</dc:creator>' if book.author else ''}<dc:language>{escape(book.target_language)}</dc:language><meta property=\"dcterms:modified\">{modified}</meta></metadata>
<manifest>{''.join(manifest)}</manifest><spine>{''.join(spine)}</spine></package>"""
        nav = f"""<?xml version=\"1.0\" encoding=\"UTF-8\"?><html xmlns=\"http://www.w3.org/1999/xhtml\" xmlns:epub=\"http://www.idpf.org/2007/ops\"><head><title>{escape(book.title)}</title></head><body><nav epub:type=\"toc\" id=\"toc\"><h1>Contents</h1><ol>{''.join(nav_items)}</ol></nav></body></html>"""
        with ZipFile(destination, "w") as archive:
            archive.writestr("mimetype", "application/epub+zip", compress_type=ZIP_STORED)
            archive.writestr("META-INF/container.xml", "<?xml version=\"1.0\"?><container version=\"1.0\" xmlns=\"urn:oasis:names:tc:opendocument:xmlns:container\"><rootfiles><rootfile full-path=\"OEBPS/content.opf\" media-type=\"application/oebps-package+xml\"/></rootfiles></container>", compress_type=ZIP_DEFLATED)
            archive.writestr("OEBPS/content.opf", opf, compress_type=ZIP_DEFLATED)
            archive.writestr("OEBPS/nav.xhtml", nav, compress_type=ZIP_DEFLATED)
            archive.writestr("OEBPS/styles.css", "body{font-family:serif;line-height:1.6}h1{text-align:center}", compress_type=ZIP_DEFLATED)
            for filename, content in chapter_files:
                archive.writestr(f"OEBPS/{filename}", content, compress_type=ZIP_DEFLATED)
            if cover_bytes:
                archive.writestr(f"OEBPS/{cover_bytes[0]}", cover_bytes[1], compress_type=ZIP_DEFLATED)
        return result(request, book)

    @staticmethod
    def _chapter_xhtml(book: ExportBook, chapter) -> str:
        paragraphs = "".join(f"<p>{escape(paragraph)}</p>" for paragraph in chapter.paragraphs)
        return f"<?xml version=\"1.0\" encoding=\"UTF-8\"?><html xmlns=\"http://www.w3.org/1999/xhtml\"><head><title>{escape(chapter.title)}</title><link rel=\"stylesheet\" type=\"text/css\" href=\"styles.css\"/></head><body><h1>{escape(book.title)}</h1><h2>Chapter {chapter.number} — {escape(chapter.title)}</h2>{paragraphs}</body></html>"
