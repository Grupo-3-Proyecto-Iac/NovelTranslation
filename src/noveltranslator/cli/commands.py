import typer

from noveltranslator.application.resume_service import ResumeService
from noveltranslator.infrastructure.paths import configured_novels_root
from noveltranslator.storage.repository import NovelRepository

app = typer.Typer(help="NovelTranslator: adquiere, analiza y traduce novelas web.")
source_app = typer.Typer(help="Gestiona las fuentes registradas.")
novel_app = typer.Typer(help="Gestiona novelas almacenadas localmente.")
app.add_typer(source_app, name="source")
app.add_typer(novel_app, name="novel")


def repository() -> NovelRepository:
    return NovelRepository(configured_novels_root())


@source_app.command("list")
def source_list() -> None:
    typer.echo("No hay fuentes registradas.")


@novel_app.command("list")
def novel_list() -> None:
    novels = repository().list_novels()
    typer.echo("\n".join(novels) if novels else "No novels found.")


@app.command()
def inspect(url: str = typer.Argument(..., help="URL de la novela")) -> None:
    typer.echo(f"Inspección aún no implementada para: {url}")


@app.command()
def download(url: str = typer.Argument(..., help="URL de la novela")) -> None:
    typer.echo(f"Descarga aún no implementada para: {url}")


@app.command()
def translate(url: str = typer.Argument(..., help="URL de la novela")) -> None:
    typer.echo(f"Traducción aún no implementada para: {url}")


@app.command()
def resume() -> None:
    jobs = ResumeService(repository()).find_pending_jobs()
    if not jobs:
        typer.echo("No pending tasks found.")
        return
    typer.echo("Pending tasks:")
    for index, job in enumerate(jobs, start=1):
        typer.echo(f"\n{index}. {job.novel_id}")
        typer.echo(f"   Chapter: {job.chapter}")
        typer.echo(f"   Stage: {job.stage.value if job.stage else '-'}")
        typer.echo(f"   Chunk: {job.chunk if job.chunk is not None else '-'} / {job.total_chunks if job.total_chunks is not None else '-'}")


@app.command()
def status(novel_id: str = typer.Argument(..., help="Identificador de novela")) -> None:
    repo = repository()
    metadata = repo.load_novel_metadata(novel_id)
    typer.echo(f"Novel: {metadata.get('title', novel_id)} ({novel_id})")
    if not repo.progress_exists(novel_id):
        typer.echo("Progress: not started")
        return
    progress = repo.load_progress(novel_id)
    typer.echo(f"Status: {progress.get('overall_status', 'UNKNOWN')}")
    typer.echo(f"Chapter: {progress.get('current_chapter', '-')}")
    typer.echo(f"Stage: {progress.get('current_stage', '-')}")
    typer.echo(f"Chunk: {progress.get('current_chunk', '-')} / {progress.get('total_chunks', '-')}")


@app.command()
def export(novel_id: str = typer.Argument(...), format: str = typer.Option("txt", "--format")) -> None:
    typer.echo(f"Exportación aún no implementada: {novel_id} ({format})")
