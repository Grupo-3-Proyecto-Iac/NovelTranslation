import json
from pathlib import Path
from zipfile import ZipFile

import pytest
from typer.testing import CliRunner

from noveltranslator.application.export_service import ExportService
from noveltranslator.core.exceptions import ExportError
from noveltranslator.core.models import Chapter, Novel
from noveltranslator.core.enums import ProcessingState
from noveltranslator.exporters.assembler import ChapterAssembler
from noveltranslator.cli import commands
from noveltranslator.storage.repository import NovelRepository
from noveltranslator.storage.serialization import utc_now_iso, write_json_atomic


def export_fixture(tmp_path: Path) -> tuple[NovelRepository, str, str]:
    repo = NovelRepository(tmp_path / "novels")
    novel_id = repo.create_novel(Novel("export", "A Novel: Test / Foo?", "Author", "en", None, None, "test", "https://example.test"))
    repo.create_chapter(novel_id, Chapter(1, "First", "https://example.test/1", ProcessingState.TRANSLATED))
    repo.create_chapter(novel_id, Chapter(2, "Second", "https://example.test/2", ProcessingState.TRANSLATED))
    chunks = [{"chapter_number": 1, "index": index, "source_text": f"Source {index}"} for index in (3, 1, 2)]
    repo.save_chunks(novel_id, 1, "hash-1", chunks)
    repo.save_chunks(novel_id, 2, "hash-2", [{"chapter_number": 2, "index": 1, "source_text": "Second source"}])
    for chapter, source_hash, values in ((1, "hash-1", ((1, "First <text>"), (2, "Second paragraph"), (3, "Third paragraph"))), (2, "hash-2", ((1, "Chapter two"),))):
        for index, text in values:
            repo.save_translation_chunk(novel_id, chapter, "default", {"chapter_number": chapter, "chunk_index": index, "translation_id": "default", "source_hash": source_hash, "source_text": "source", "translated_text": text, "translator_id": "mock", "model_id": "mock-v1", "source_language": "en", "target_language": "es"})
        repo.save_validation_result(novel_id, chapter, "default", {"translation_id": "default", "chapter_number": chapter, "status": "OK", "errors": [], "warnings": [], "metrics": {"source_hash": source_hash}, "validated_at": utc_now_iso(), "needs_review": False})
    # A separate translation must never be mixed into the default export.
    repo.save_translation_chunk(novel_id, 1, "other", {"chapter_number": 1, "chunk_index": 1, "translation_id": "other", "source_hash": "hash-1", "translated_text": "OTHER MODEL", "translator_id": "other", "model_id": "other", "source_language": "en", "target_language": "es"})
    return repo, novel_id, "default"


def test_assembler_orders_chunks_and_rejects_missing(tmp_path: Path) -> None:
    repo, novel_id, translation_id = export_fixture(tmp_path)
    chapter = ChapterAssembler(repo).assemble_chapter(novel_id, 1, translation_id)
    assert chapter.text == "First <text>\n\nSecond paragraph\n\nThird paragraph"
    (tmp_path / "novels" / novel_id / "chapters" / "001" / "translations" / "default" / "chunk_002.json").unlink()
    with pytest.raises(ExportError, match="chunk 2 is missing"):
        ChapterAssembler(repo).assemble_chapter(novel_id, 1, translation_id)


def test_export_all_formats_and_escape_html(tmp_path: Path) -> None:
    repo, novel_id, translation_id = export_fixture(tmp_path)
    service = ExportService(repo)
    outputs = {}
    for format_id in ("txt", "json", "html", "epub"):
        result = service.export_novel(novel_id, format_id=format_id, translation_id=translation_id)
        outputs[format_id] = result.output_path
        assert result.output_path.is_file()
        assert result.chapters_exported == 2
    assert "First &lt;text&gt;" in outputs["html"].read_text(encoding="utf-8")
    payload = json.loads(outputs["json"].read_text(encoding="utf-8"))
    assert [item["number"] for item in payload["chapters"]] == [1, 2]
    with ZipFile(outputs["epub"]) as archive:
        assert archive.read("mimetype") == b"application/epub+zip"
        assert "OEBPS/nav.xhtml" in archive.namelist()
        assert "OEBPS/chapter_001.xhtml" in archive.namelist()
        assert "OEBPS/chapter_002.xhtml" in archive.namelist()
        assert "First" in archive.read("OEBPS/nav.xhtml").decode("utf-8")


def test_warning_requires_explicit_opt_in_and_overwrite_is_explicit(tmp_path: Path) -> None:
    repo, novel_id, translation_id = export_fixture(tmp_path)
    repo.save_validation_result(novel_id, 2, translation_id, {"translation_id": translation_id, "chapter_number": 2, "status": "WARNING", "errors": [], "warnings": [{"code": "SUSPICIOUS_LENGTH_RATIO"}], "metrics": {}, "validated_at": utc_now_iso(), "needs_review": True})
    result = ExportService(repo).export_novel(novel_id, format_id="txt", translation_id=translation_id)
    assert result.chapters_exported == 1
    assert result.chapters_skipped == 1
    result = ExportService(repo).export_novel(novel_id, format_id="json", translation_id=translation_id, include_warnings=True)
    with pytest.raises(ExportError, match="already exists"):
        ExportService(repo).export_novel(novel_id, format_id="json", translation_id=translation_id)
    assert result.output_path.is_file()


def test_export_cli_delegates_to_export_service(tmp_path: Path, monkeypatch) -> None:
    repo, novel_id, _ = export_fixture(tmp_path)
    monkeypatch.setattr(commands, "repository", lambda: repo)
    result = CliRunner().invoke(commands.app, ["export", novel_id, "--format", "txt"])
    assert result.exit_code == 0, result.stdout
    assert "Chapters exported: 2" in result.stdout
