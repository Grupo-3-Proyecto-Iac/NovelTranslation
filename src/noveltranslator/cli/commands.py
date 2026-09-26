from dataclasses import replace

import typer

from noveltranslator.access.http_client import HttpClient
from noveltranslator.access.manager import AccessManager
from noveltranslator.access.models import AccessConfig, RetryConfig
from noveltranslator.application.resume_service import ResumeService
from noveltranslator.application.download_service import DownloadService
from noveltranslator.core.models import Chapter
from noveltranslator.infrastructure.config import load_yaml
from noveltranslator.infrastructure.paths import CONFIG_ROOT, configured_novels_root
from noveltranslator.sources.loader import default_registry
from noveltranslator.storage.repository import NovelRepository

app = typer.Typer(help="NovelTranslator: adquiere, analiza y traduce novelas web.")
source_app = typer.Typer(help="Gestiona las fuentes registradas.")
novel_app = typer.Typer(help="Gestiona novelas almacenadas localmente.")
access_app = typer.Typer(help="Diagnósticos controlados de acceso HTTP.")
app.add_typer(source_app, name="source")
app.add_typer(novel_app, name="novel")
app.add_typer(access_app, name="access")


def repository() -> NovelRepository:
    return NovelRepository(configured_novels_root())


def access_manager(no_delay: bool = False) -> AccessManager:
    config_path = CONFIG_ROOT / "config.yaml"
    if not config_path.is_file():
        config_path = CONFIG_ROOT / "config.example.yaml"
    values = load_yaml(config_path)
    access_config = AccessConfig.from_mapping(values.get("access", {}))
    if no_delay:
        access_config = replace(access_config, min_delay_seconds=0, max_delay_seconds=0, requests_per_minute=0)
    return AccessManager(HttpClient(access_config, RetryConfig.from_mapping(values.get("retry", {}))))


def download_service(manager: AccessManager) -> DownloadService:
    config_path = CONFIG_ROOT / "config.yaml"
    if not config_path.is_file():
        config_path = CONFIG_ROOT / "config.example.yaml"
    values = load_yaml(config_path)
    options = values.get("download", {})
    return DownloadService(default_registry(manager), repository(), on_chapter_error=options.get("on_chapter_error", "stop"), skip_existing=bool(options.get("skip_existing", True)), refresh_metadata=bool(options.get("refresh_metadata", True)))


@source_app.command("list")
def source_list() -> None:
    registry = default_registry()
    try:
        for source in registry.list():
            typer.echo(source.name)
    finally:
        for source in registry.list():
            source.access_manager.close()


@access_app.command("check")
def access_check(url: str = typer.Argument(..., help="Una URL HTTP/HTTPS"), no_delay: bool = typer.Option(False, "--no-delay", help="Desactiva pausas solo para este diagnóstico")) -> None:
    """Realiza una única solicitud HTTP y muestra sus metadatos."""
    manager = access_manager(no_delay=no_delay)
    try:
        response = manager.fetch(url)
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="url") from exc
    finally:
        manager.close()
    typer.echo(f"URL: {response.url}")
    typer.echo(f"Status code: {response.status_code if response.status_code is not None else '-'}")
    typer.echo(f"Access status: {response.access_status.value}")
    typer.echo(f"Content-Type: {response.content_type or '-'}")
    typer.echo(f"Attempts: {response.attempts}")
    typer.echo(f"Final URL: {response.final_url}")
    typer.echo(f"Response size: {response.size_bytes / 1024:.1f} KB")


@novel_app.command("list")
def novel_list() -> None:
    novels = repository().list_novels()
    typer.echo("\n".join(novels) if novels else "No novels found.")


@app.command()
def inspect(url: str = typer.Argument(..., help="URL de la novela"), all_chapters: bool = typer.Option(False, "--all", help="Muestra todos los capítulos")) -> None:
    manager = access_manager()
    try:
        source = default_registry(manager).resolve(url)
        novel = source.get_novel(url)
        chapters = source.get_chapters(novel)
    finally:
        manager.close()
    typer.echo(f"Source: {source.name}\n")
    typer.echo("Novel:")
    typer.echo(f"  Title: {novel.title}")
    typer.echo(f"  Author: {novel.author or '-'}")
    typer.echo(f"  Language: {novel.language}")
    typer.echo(f"\nChapters:\n  Found: {len(chapters)}")
    shown = chapters if all_chapters else chapters[:3] + (chapters[-1:] if len(chapters) > 3 else [])
    if shown:
        typer.echo("\n  Chapters:")
        for chapter in shown:
            typer.echo(f"  {chapter.number:03d} - {chapter.title}")


@app.command("inspect-chapter")
def inspect_chapter(url: str = typer.Argument(..., help="URL del capítulo"), preview: int = typer.Option(0, "--preview", min=0, help="Muestra los primeros N párrafos")) -> None:
    manager = access_manager()
    try:
        source = default_registry(manager).resolve(url)
        chapter = source.get_chapter(Chapter(source.chapter_number_from_url(url), "", url))
    finally:
        manager.close()
    typer.echo(f"Source: {source.name}")
    typer.echo(f"Chapter: {chapter.number}")
    typer.echo(f"Title: {chapter.title or '-'}")
    typer.echo(f"Paragraphs: {len(chapter.paragraphs)}")
    typer.echo(f"Characters: {sum(len(paragraph) for paragraph in chapter.paragraphs)}")
    typer.echo("Access status: OK")
    for paragraph in chapter.paragraphs[:preview]:
        typer.echo(f"\n{paragraph}")


@app.command()
def download(url: str = typer.Argument(..., help="URL de la novela"), limit: int | None = typer.Option(None, "--limit", min=1, help="Número máximo de capítulos pendientes"), from_chapter: int | None = typer.Option(None, "--from-chapter", min=0), to_chapter: int | None = typer.Option(None, "--to-chapter", min=0), force: bool = typer.Option(False, "--force", help="Reemplaza source.json existentes de forma explícita")) -> None:
    manager = access_manager()
    try:
        summary = download_service(manager).download_novel(url, limit=limit, from_chapter=from_chapter, to_chapter=to_chapter, force=force)
    finally:
        manager.close()
    _display_download_summary(summary)


def _display_download_summary(summary) -> None:
    typer.echo(f"Novel: {summary.novel_id}")
    typer.echo(f"Chapters: {summary.total_chapters}")
    typer.echo(f"Downloaded now: {summary.downloaded_now}")
    typer.echo(f"Skipped: {summary.skipped}")
    typer.echo(f"Failed: {summary.failed}")
    typer.echo(f"Pending: {summary.pending}")
    typer.echo("Status: PAUSED" if summary.paused else "Status: DOWNLOAD COMPLETED" if summary.completed else "Status: INCOMPLETE")


@app.command()
def translate(url: str = typer.Argument(..., help="URL de la novela")) -> None:
    typer.echo(f"Traducción aún no implementada para: {url}")


@app.command()
def resume(novel_id: str | None = typer.Argument(None, help="Identificador local de novela a reanudar"), limit: int | None = typer.Option(None, "--limit", min=1)) -> None:
    if novel_id is None:
        jobs = ResumeService(repository()).find_pending_jobs()
        if not jobs:
            typer.echo("No pending tasks found.")
            return
        typer.echo("Pending tasks (use 'resume NOVEL_ID' to continue):")
        for index, job in enumerate(jobs, start=1):
            typer.echo(f"\n{index}. {job.novel_id}")
            typer.echo(f"   Chapter: {job.chapter}")
            typer.echo(f"   Stage: {job.stage.value if job.stage else '-'}")
            typer.echo(f"   Chunk: {job.chunk if job.chunk is not None else '-'} / {job.total_chunks if job.total_chunks is not None else '-'}")
        return
    manager = access_manager()
    try:
        summary = download_service(manager).resume_novel(novel_id, limit=limit)
    finally:
        manager.close()
    _display_download_summary(summary)


@app.command()
def status(novel_id: str = typer.Argument(..., help="Identificador de novela")) -> None:
    repo = repository()
    metadata = repo.load_novel_metadata(novel_id)
    typer.echo(f"Novel: {metadata.get('title', novel_id)} ({novel_id})")
    progress = repo.load_progress(novel_id) if repo.progress_exists(novel_id) else None
    chapter_numbers = repo.list_chapters(novel_id)
    downloaded = failed = 0
    for number in chapter_numbers:
        chapter_metadata = repo.load_chapter_metadata(novel_id, number)
        if chapter_metadata.get("status") == "DOWNLOADED":
            downloaded += 1
        if chapter_metadata.get("status") == "FAILED":
            failed += 1
    typer.echo(f"Source: {metadata.get('source', '-')}")
    typer.echo("Chapters:")
    typer.echo(f"Total: {len(chapter_numbers)}")
    typer.echo(f"Downloaded: {downloaded}")
    typer.echo(f"Pending: {len(chapter_numbers) - downloaded - failed}")
    typer.echo(f"Failed: {failed}")
    if progress is None:
        typer.echo("Progress: not started")
        return
    typer.echo(f"Status: {progress.get('overall_status', 'UNKNOWN')}")
    typer.echo("Current task: DOWNLOAD")
    typer.echo(f"Chapter: {progress.get('current_chapter', '-')}")
    typer.echo(f"Stage: {progress.get('current_stage', '-')}")
    typer.echo(f"Chunk: {progress.get('current_chunk', '-')} / {progress.get('total_chunks', '-')}")


@app.command()
def export(novel_id: str = typer.Argument(...), format: str = typer.Option("txt", "--format")) -> None:
    typer.echo(f"Exportación aún no implementada: {novel_id} ({format})")
