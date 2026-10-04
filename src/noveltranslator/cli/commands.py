from dataclasses import replace
import os

import typer
from rich.progress import BarColumn, Progress, TaskProgressColumn, TextColumn, TimeElapsedColumn, TimeRemainingColumn

from noveltranslator.access.http_client import HttpClient
from noveltranslator.access.browser_client import BrowserClient
from noveltranslator.access.manager import AccessManager
from noveltranslator.access.models import AccessConfig, RetryConfig
from noveltranslator.application.resume_service import ResumeService
from noveltranslator.application.download_service import DownloadService
from noveltranslator.application.browser_capture_service import BrowserCaptureService
from noveltranslator.application.html_import_service import HtmlImportService
from noveltranslator.application.analysis_service import AnalysisService
from noveltranslator.application.translation_service import TranslationService
from noveltranslator.application.export_service import ExportService
from noveltranslator.core.models import Chapter, TranslationMemoryEntry
from noveltranslator.core.exceptions import ExportError, NovelTranslatorError
from noveltranslator.core.models import GlossaryTerm
from noveltranslator.core.enums import GlossaryStatus
from noveltranslator.processing.glossary import GlossaryManager
from noveltranslator.processing.memory import MemoryManager
from noveltranslator.processing.splitter import TextSplitter
from noveltranslator.processing.normalizer import TextNormalizer
from noveltranslator.infrastructure.config import load_yaml
from noveltranslator.infrastructure.paths import CONFIG_ROOT, DATA_ROOT, configured_novels_root
from noveltranslator.sources.loader import default_registry
from noveltranslator.storage.repository import NovelRepository
from noveltranslator.translators import HuggingFaceTranslator, MockTranslator, OllamaTranslator, TranslatorRegistry
from noveltranslator.validation.chunk_validator import ChunkValidator
from noveltranslator.application.validation_service import ValidationService
from noveltranslator.application.translation_repair_service import TranslationRepairService
from noveltranslator.application.events import ProgressCallback
from noveltranslator.cli.progress import RunProgress
from noveltranslator.audio import AudioGenerationService

app = typer.Typer(help="NovelTranslator: adquiere, analiza y traduce novelas web.")
source_app = typer.Typer(help="Gestiona las fuentes registradas.")
novel_app = typer.Typer(help="Gestiona novelas almacenadas localmente.")
access_app = typer.Typer(help="Diagnósticos controlados de acceso HTTP.")
glossary_app = typer.Typer(help="Consulta y edición manual del glosario.")
app.add_typer(source_app, name="source")
app.add_typer(novel_app, name="novel")
app.add_typer(access_app, name="access")
app.add_typer(glossary_app, name="glossary")
translator_app = typer.Typer(help="Gestiona los traductores disponibles.")
translation_app = typer.Typer(help="Consulta traducciones persistidas.")
memory_app = typer.Typer(help="Gestiona la memoria de traducción.")
context_app = typer.Typer(help="Consulta el contexto narrativo persistido.")
validation_app = typer.Typer(help="Consulta resultados de validación.")
app.add_typer(translator_app, name="translator")
app.add_typer(translation_app, name="translation")
app.add_typer(memory_app, name="memory")
app.add_typer(context_app, name="context")
app.add_typer(validation_app, name="validation")


@app.callback()
def main(assisted_browser: bool = typer.Option(False, "--assisted-browser", help="Abre un navegador visible si HTTP queda bloqueado")) -> None:
    """Configura opciones globales de ejecución."""
    if assisted_browser:
        os.environ["NOVELTRANSLATOR_ASSISTED_BROWSER"] = "1"


def repository() -> NovelRepository:
    return NovelRepository(configured_novels_root())


def access_manager(no_delay: bool = False, assisted_browser: bool = False) -> AccessManager:
    config_path = CONFIG_ROOT / "config.yaml"
    if not config_path.is_file():
        config_path = CONFIG_ROOT / "config.example.yaml"
    values = load_yaml(config_path)
    access_config = AccessConfig.from_mapping(values.get("access", {}))
    if no_delay:
        access_config = replace(access_config, min_delay_seconds=0, max_delay_seconds=0, requests_per_minute=0)
    assisted_browser = assisted_browser or os.getenv("NOVELTRANSLATOR_ASSISTED_BROWSER", "").lower() in {"1", "true", "yes", "on"}
    browser = BrowserClient(profile_directory=DATA_ROOT / "sessions" / "browser") if assisted_browser else None
    return AccessManager(HttpClient(access_config, RetryConfig.from_mapping(values.get("retry", {}))), browser)


def download_service(manager: AccessManager, progress_callback: ProgressCallback | None = None) -> DownloadService:
    config_path = CONFIG_ROOT / "config.yaml"
    if not config_path.is_file():
        config_path = CONFIG_ROOT / "config.example.yaml"
    values = load_yaml(config_path)
    options = values.get("download", {})
    return DownloadService(default_registry(manager), repository(), on_chapter_error=options.get("on_chapter_error", "stop"), skip_existing=bool(options.get("skip_existing", True)), refresh_metadata=bool(options.get("refresh_metadata", True)), progress_callback=progress_callback)


def analysis_service(progress_callback: ProgressCallback | None = None) -> AnalysisService:
    config_path = CONFIG_ROOT / "config.yaml"
    if not config_path.is_file():
        config_path = CONFIG_ROOT / "config.example.yaml"
    values = load_yaml(config_path)
    chunking = values.get("processing", {}).get("chunking", {})
    splitter = TextSplitter(max_characters=int(chunking.get("max_characters", 6000)), target_characters=int(chunking.get("target_characters", 4500)), overlap_paragraphs=int(chunking.get("overlap_paragraphs", 1)))
    return AnalysisService(repository(), splitter=splitter, progress_callback=progress_callback)


def translation_registry() -> tuple[TranslatorRegistry, dict]:
    config_path = CONFIG_ROOT / "config.yaml"
    if not config_path.is_file():
        config_path = CONFIG_ROOT / "config.example.yaml"
    values = load_yaml(config_path)
    options = dict(values.get("translation", {}))
    options["memory"] = values.get("memory", {})
    options["validation"] = values.get("validation", {})
    registry = TranslatorRegistry()
    registry.register(MockTranslator())
    registry.register(OllamaTranslator(model=str(options.get("model", "qwen2.5:7b"))))
    registry.register(HuggingFaceTranslator(model=str(options.get("huggingface_model", "Helsinki-NLP/opus-mt-en-es")), device=str(options.get("huggingface_device", "cpu"))))
    return registry, options


def close_translation_registry(registry: TranslatorRegistry) -> None:
    for translator_id in registry.list():
        registry.resolve(translator_id).close()


def memory_manager(novel_id: str) -> MemoryManager:
    return MemoryManager(repository(), novel_id)


def translation_service(registry: TranslatorRegistry, options: dict, progress_callback: ProgressCallback | None = None) -> TranslationService:
    memory = options.get("memory", {})
    validation = options.get("validation", {})
    ratio = validation.get("length_ratio", {})
    untranslated = validation.get("untranslated_detection", {})
    chunk_validator = ChunkValidator(min_length_ratio=float(ratio.get("min", 0.35)), max_length_ratio=float(ratio.get("max", 2.50)), untranslated_threshold=float(untranslated.get("warning_threshold", 0.30)), untranslated_enabled=bool(untranslated.get("enabled", True)), locked_missing_is_failure=bool(validation.get("locked_terms", {}).get("missing_is_failure", True)))
    return TranslationService(
        repository(),
        registry,
        max_attempts=int(options.get("retry", {}).get("max_attempts", 1)),
        memory_enabled=bool(memory.get("enabled", True)),
        max_translation_entries=int(memory.get("translation", {}).get("max_entries_per_request", 20)),
        max_context_items=int(memory.get("context", {}).get("max_items", 20)),
        previous_chapters=int(memory.get("context", {}).get("previous_chapters", 2)),
        auto_validate=bool(validation.get("auto_validate_after_translation", False)),
        validation_service=ValidationService(repository(), chunk_validator=chunk_validator),
        progress_callback=progress_callback,
    )


def validation_service_from_config(progress_callback: ProgressCallback | None = None) -> ValidationService:
    config_path = CONFIG_ROOT / "config.yaml"
    if not config_path.is_file():
        config_path = CONFIG_ROOT / "config.example.yaml"
    values = load_yaml(config_path)
    options = values.get("validation", {})
    ratio = options.get("length_ratio", {})
    untranslated = options.get("untranslated_detection", {})
    validator = ChunkValidator(min_length_ratio=float(ratio.get("min", 0.35)), max_length_ratio=float(ratio.get("max", 2.50)), untranslated_threshold=float(untranslated.get("warning_threshold", 0.30)), untranslated_enabled=bool(untranslated.get("enabled", True)), locked_missing_is_failure=bool(options.get("locked_terms", {}).get("missing_is_failure", True)))
    return ValidationService(repository(), chunk_validator=validator, progress_callback=progress_callback)


@source_app.command("list")
def source_list() -> None:
    registry = default_registry()
    try:
        for source in registry.list():
            typer.echo(source.name)
    finally:
        for source in registry.list():
            source.access_manager.close()


@translator_app.command("list")
def translator_list() -> None:
    registry, _ = translation_registry()
    try:
        for translator_id in registry.list():
            translator = registry.resolve(translator_id)
            typer.echo(f"{translator.id}\t{translator.model_id}")
    finally:
        close_translation_registry(registry)


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


@app.command()
def analyze(novel_id: str = typer.Argument(..., help="Identificador local de novela"), limit: int | None = typer.Option(None, "--limit", min=1), from_chapter: int | None = typer.Option(None, "--from-chapter", min=0), to_chapter: int | None = typer.Option(None, "--to-chapter", min=0), force: bool = typer.Option(False, "--force")) -> None:
    with RunProgress() as reporter:
        summary = analysis_service(reporter).analyze_novel(novel_id, limit=limit, from_chapter=from_chapter, to_chapter=to_chapter, force=force)
    typer.echo(f"Novel: {summary.novel_id}")
    typer.echo(f"Analyzed now: {summary.analyzed_now}")
    typer.echo(f"Skipped: {summary.skipped}")
    typer.echo(f"Failed: {summary.failed}")
    typer.echo(f"Pending: {summary.pending}")
    typer.echo("Status: ANALYSIS COMPLETED" if summary.completed else "Status: INCOMPLETE")


@app.command("audio")
def audio(
    novel_id: str = typer.Argument(..., help="Identificador local de novela"),
    translation_id: str = typer.Option("hf-opus-v3", "--translation-id", help="Traducción persistida que se narrará"),
    voice: str = typer.Option("M5", "--voice", help="Estilo de voz Supertonic"),
    speed: float = typer.Option(1.40, "--speed", min=0.5, max=2.0, help="Velocidad de lectura"),
    steps: int = typer.Option(8, "--steps", min=1, max=100, help="Pasos de síntesis: menos es más rápido"),
    from_chapter: int | None = typer.Option(None, "--from-chapter", min=0),
    to_chapter: int | None = typer.Option(None, "--to-chapter", min=0),
    pause_seconds: float = typer.Option(0.25, "--pause-seconds", min=0.0, help="Silencio entre unidades habladas"),
    tail_silence_seconds: float = typer.Option(0.35, "--tail-silence-seconds", min=0.0, help="Silencio final para evitar cortes"),
    threads: int = typer.Option(4, "--threads", min=1, max=16, help="Hilos máximos del motor local"),
    max_unit_characters: int = typer.Option(900, "--max-unit-characters", min=100, help="Límite seguro de caracteres por unidad"),
    overwrite: bool = typer.Option(False, "--overwrite", help="Regenera el capítulo aunque ya exista"),
) -> None:
    """Genera un WAV por capítulo y un manifest de sincronización."""
    progress = Progress(
        TextColumn("{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
    )
    chapter_task = progress.add_task("Capítulos", total=1)
    unit_task = progress.add_task("Preparando audio", total=1)

    def update_audio_progress(event: dict[str, object]) -> None:
        event_name = event.get("event")
        chapter = int(event.get("chapter", 0))
        chapter_position = int(event.get("chapter_position", 0))
        chapters_total = int(event.get("chapters_total", 1))
        units_total = int(event.get("units_total", 1))
        chunks_total = int(event.get("chunks_total", 1))
        chapter_completed = event_name in {"chapter_completed", "chapter_skipped"}
        progress.update(
            chapter_task,
            total=chapters_total,
            completed=chapter_position if chapter_completed else max(0, chapter_position - 1),
            description=f"Capítulos · {chapter_position}/{chapters_total} · actual {chapter:03d}",
        )
        if event_name == "chapter_started":
            progress.update(
                unit_task,
                total=max(1, units_total),
                completed=0,
                description=f"Capítulo {chapter:03d} · preparando {chunks_total} chunks",
            )
        elif event_name == "unit_completed":
            unit_position = int(event.get("unit_position", 0))
            chunk_position = int(event.get("chunk_position", 0))
            chunk_index = int(event.get("chunk_index", 0))
            progress.update(
                unit_task,
                total=max(1, units_total),
                completed=unit_position,
                description=(
                    f"Capítulo {chapter:03d} · chunk {chunk_position}/{chunks_total} "
                    f"(id {chunk_index:03d}) · unidad {unit_position}/{units_total}"
                ),
            )
        elif event_name in {"chapter_completed", "chapter_skipped"}:
            label = "omitido" if event_name == "chapter_skipped" else "completado"
            progress.update(
                unit_task,
                total=max(1, units_total),
                completed=max(1, units_total),
                description=f"Capítulo {chapter:03d} · {label}",
            )
            progress.update(
                chapter_task,
                total=chapters_total,
                completed=chapter_position,
                description=f"Capítulos · {chapter_position}/{chapters_total} · {label}",
            )

    try:
        with progress:
            summary = AudioGenerationService(
                repository(),
                progress_callback=lambda message: None,
                progress_detail_callback=update_audio_progress,
            ).generate_novel(
                novel_id,
                translation_id=translation_id,
                voice=voice,
                speed=speed,
                steps=steps,
                from_chapter=from_chapter,
                to_chapter=to_chapter,
                overwrite=overwrite,
                pause_seconds=pause_seconds,
                tail_silence_seconds=tail_silence_seconds,
                threads=threads,
                max_unit_characters=max_unit_characters,
            )
    except (NovelTranslatorError, KeyError, ValueError, OSError, RuntimeError) as error:
        typer.echo(f"Generación de audio detenida: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"Novel: {summary.novel_id}")
    typer.echo(f"Chapters processed: {summary.chapters_processed}")
    typer.echo(f"Units generated: {summary.segments_generated}")
    typer.echo(f"Units skipped: {summary.segments_skipped}")
    for path in summary.output_paths:
        typer.echo(f"Output: {path}")


@novel_app.command("list")
def novel_list() -> None:
    repo = repository()
    novels = repo.list_novels()
    if not novels:
        typer.echo("No novels found.")
        return
    typer.echo("ID\tChapters\tTranslated\tStatus")
    for novel_id in novels:
        progress = repo.load_progress(novel_id) if repo.progress_exists(novel_id) else {}
        translation_id = progress.get("translation_id", "default")
        chapters = repo.list_chapters(novel_id)
        translated = sum(bool(repo.list_translation_chunks(novel_id, number, translation_id)) for number in chapters)
        typer.echo(f"{novel_id}\t{len(chapters)}\t{translated}\t{progress.get('overall_status', 'PENDING')}")


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
    reporter = RunProgress()
    try:
        with reporter:
            service = download_service(manager)
            if hasattr(service, "progress_callback"):
                service.progress_callback = reporter
            summary = service.download_novel(url, limit=limit, from_chapter=from_chapter, to_chapter=to_chapter, force=force)
    finally:
        manager.close()
    _display_download_summary(summary)


@app.command()
def run(
    url: str = typer.Argument(..., help="URL de la novela"),
    limit: int | None = typer.Option(None, "--limit", min=1, help="Capítulos nuevos a procesar en esta ejecución"),
    from_chapter: int | None = typer.Option(None, "--from-chapter", min=0, help="Primer capítulo incluido"),
    to_chapter: int | None = typer.Option(None, "--to-chapter", min=0, help="Último capítulo incluido"),
    translator: str | None = typer.Option(None, "--translator", help="Traductor: mock, huggingface u ollama"),
    translation_id: str = typer.Option("default", "--translation-id", help="Identificador de la traducción persistida"),
    format: str = typer.Option("epub", "--format", help="Formato final: txt, json, html o epub"),
    include_warnings: bool = typer.Option(False, "--include-warnings", help="Incluye capítulos con advertencias de validación"),
    allow_partial: bool = typer.Option(False, "--allow-partial", help="Permite exportar capítulos con chunks faltantes"),
    overwrite: bool = typer.Option(True, "--overwrite/--no-overwrite", help="Reemplaza el archivo de exportación existente (por defecto en run)"),
    force: bool = typer.Option(False, "--force", help="Reprocesa artefactos existentes de forma explícita"),
) -> None:
    """Ejecuta el flujo completo y muestra su progreso en tiempo real."""
    reporter = RunProgress()
    manager = None
    registry = None
    try:
        with reporter:
            reporter.info("Iniciando pipeline: descarga -> análisis -> traducción -> validación -> exportación")
            manager = access_manager()
            download_summary = download_service(manager, reporter).download_novel(url, limit=limit, from_chapter=from_chapter, to_chapter=to_chapter, force=force)
            novel_id = download_summary.novel_id
            reporter.info(f"Novela local: {novel_id} · {download_summary.downloaded_now} descargados · {download_summary.skipped} omitidos · {download_summary.pending} pendientes")

            analysis_summary = analysis_service(reporter).analyze_novel(novel_id, limit=limit, from_chapter=from_chapter, to_chapter=to_chapter, force=force)
            reporter.info(f"Análisis: {analysis_summary.analyzed_now} nuevos · {analysis_summary.skipped} omitidos · {analysis_summary.pending} pendientes")

            registry, options = translation_registry()
            selected_translator = translator or str(options.get("provider", "mock"))
            translation_summary = translation_service(registry, options, reporter).translate_novel(
                novel_id,
                translation_id=translation_id,
                translator_id=selected_translator,
                source_language=options.get("source_language"),
                target_language=str(options.get("target_language", "es")),
                limit=limit,
                from_chapter=from_chapter,
                to_chapter=to_chapter,
                force=force,
            )
            reporter.info(f"Traducción: {translation_summary.chunks_translated} chunks nuevos · {translation_summary.chunks_skipped} omitidos · {translation_summary.pending} pendientes")

            validation_summary = validation_service_from_config(reporter).validate_novel(
                novel_id,
                translation_id=translation_id,
                limit=limit,
                from_chapter=from_chapter,
                to_chapter=to_chapter,
                reuse_existing=True,
            )
            reporter.info(f"Validación: {validation_summary.ok} OK · {validation_summary.warnings} avisos · {validation_summary.failed} fallidos")

            result = ExportService(repository(), progress_callback=reporter).export_novel(
                novel_id,
                format_id=format,
                translation_id=translation_id,
                include_warnings=include_warnings,
                allow_partial=allow_partial,
                overwrite=overwrite,
                from_chapter=from_chapter,
                to_chapter=to_chapter,
            )
            reporter.info(f"Pipeline terminado. Archivo: {result.output_path}")
    except (NovelTranslatorError, ExportError, KeyError, ValueError, OSError) as error:
        reporter.info(f"Pipeline detenido: {error}")
        raise typer.Exit(code=1) from error
    finally:
        if registry is not None:
            close_translation_registry(registry)
        if manager is not None:
            manager.close()


def _display_download_summary(summary) -> None:
    typer.echo(f"Novel: {summary.novel_id}")
    typer.echo(f"Chapters: {summary.total_chapters}")
    typer.echo(f"Downloaded now: {summary.downloaded_now}")
    typer.echo(f"Skipped: {summary.skipped}")
    typer.echo(f"Failed: {summary.failed}")
    typer.echo(f"Pending: {summary.pending}")
    typer.echo("Status: PAUSED" if summary.paused else "Status: DOWNLOAD COMPLETED" if summary.completed else "Status: INCOMPLETE")


@app.command()
def translate(novel_id: str = typer.Argument(..., help="Identificador local de novela"), limit: int | None = typer.Option(None, "--limit", min=1), translation_id: str = typer.Option("default", "--translation-id"), translator: str | None = typer.Option(None, "--translator"), from_chapter: int | None = typer.Option(None, "--from-chapter", min=0), to_chapter: int | None = typer.Option(None, "--to-chapter", min=0), force: bool = typer.Option(False, "--force")) -> None:
    registry, options = translation_registry()
    selected = translator or str(options.get("provider", "mock"))
    try:
        with RunProgress() as reporter:
            summary = translation_service(registry, options, reporter).translate_novel(novel_id, translation_id=translation_id, translator_id=selected, source_language=options.get("source_language"), target_language=str(options.get("target_language", "es")), limit=limit, from_chapter=from_chapter, to_chapter=to_chapter, force=force)
    except NovelTranslatorError as error:
        typer.echo(f"Translation failed: {error}", err=True)
        raise typer.Exit(code=1) from error
    finally:
        close_translation_registry(registry)
    typer.echo(f"Novel: {summary.novel_id}")
    typer.echo(f"Translator: {selected}")
    typer.echo(f"Translated now: {summary.chunks_translated}")
    typer.echo(f"Skipped: {summary.chunks_skipped}")
    typer.echo(f"Failed: {summary.chunks_failed}")
    typer.echo(f"Pending: {summary.pending}")
    typer.echo("Status: PAUSED" if summary.paused else "Status: TRANSLATION COMPLETED" if summary.completed else "Status: INCOMPLETE")
    return


@translation_app.command("show")
def translation_show(novel_id: str = typer.Argument(...), chapter: int = typer.Argument(..., min=1), chunk: int = typer.Argument(..., min=0), translation_id: str = typer.Option("default", "--translation-id")) -> None:
    data = repository().load_translation_chunk(novel_id, chapter, translation_id, chunk)
    typer.echo(f"Novel: {novel_id}")
    typer.echo(f"Chapter: {chapter:03d}  Chunk: {chunk:03d}")
    typer.echo(f"Translator: {data.get('translator_id', '-')} / {data.get('model_id', '-')}")
    typer.echo("Source:")
    typer.echo(data.get("source_text", ""))
    typer.echo("Translation:")
    typer.echo(data.get("translated_text", ""))


@app.command()
def validate(novel_id: str = typer.Argument(..., help="Identificador local de novela"), limit: int | None = typer.Option(None, "--limit", min=1), translation_id: str = typer.Option("default", "--translation-id"), from_chapter: int | None = typer.Option(None, "--from-chapter", min=0), to_chapter: int | None = typer.Option(None, "--to-chapter", min=0)) -> None:
    with RunProgress() as reporter:
        summary = validation_service_from_config(reporter).validate_novel(novel_id, translation_id=translation_id, limit=limit, from_chapter=from_chapter, to_chapter=to_chapter)
    _display_validation_summary(summary)


def _display_validation_summary(summary) -> None:
    typer.echo(f"Novel: {summary.novel_id}")
    typer.echo(f"Chapters: {summary.chapters_total}")
    typer.echo(f"OK: {summary.ok}")
    typer.echo(f"Warnings: {summary.warnings}")
    typer.echo(f"Failed: {summary.failed}")
    typer.echo(f"Needs review: {summary.needs_review}")


@validation_app.command("show")
def validation_show(novel_id: str = typer.Argument(...), chapter: int = typer.Argument(..., min=1), translation_id: str = typer.Option("default", "--translation-id")) -> None:
    data = repository().load_validation_result(novel_id, chapter, translation_id)
    typer.echo(f"Status: {data.get('status', 'UNKNOWN')}")
    typer.echo(f"Needs review: {data.get('needs_review', False)}")
    typer.echo("Errors:")
    for issue in data.get("errors", []):
        typer.echo(f"- {issue.get('code')}: {issue.get('message')}")
    typer.echo("Warnings:")
    for issue in data.get("warnings", []):
        typer.echo(f"- {issue.get('code')}: {issue.get('message')}")


@validation_app.command("list")
def validation_list(novel_id: str = typer.Argument(...), translation_id: str = typer.Option("default", "--translation-id"), status_filter: str | None = typer.Option(None, "--status")) -> None:
    for result in repository().list_validation_results(novel_id, translation_id):
        if status_filter and result.get("status", "").casefold() != status_filter.casefold():
            continue
        typer.echo(f"Chapter {int(result.get('chapter_number', 0)):03d}: {result.get('status', 'UNKNOWN')}" + (" [needs review]" if result.get("needs_review") else ""))


@validation_app.command("report")
def validation_report(novel_id: str = typer.Argument(...), translation_id: str = typer.Option("default", "--translation-id")) -> None:
    summary = validation_service_from_config().validate_novel(novel_id, translation_id=translation_id, reuse_existing=True)
    _display_validation_summary(summary)
    if summary.issues_by_code:
        typer.echo("Top issues:")
        for code, count in sorted(summary.issues_by_code.items(), key=lambda item: (-item[1], item[0])):
            typer.echo(f"{code}: {count}")


@memory_app.command("list")
def memory_list(novel_id: str = typer.Argument(...), status: str | None = typer.Option(None, "--status")) -> None:
    entries = memory_manager(novel_id).load_translation_memory()
    for entry in entries:
        if status and entry.status != status.upper():
            continue
        preferred = " preferred" if entry.preferred else ""
        typer.echo(f"{entry.source_text} -> {entry.translated_text} [{entry.status}{preferred}] ({entry.translation_id}, ch={entry.chapter_number}, chunk={entry.chunk_index})")


@memory_app.command("add")
def memory_add(novel_id: str = typer.Argument(...), source: str = typer.Option(..., "--source"), translation: str = typer.Option(..., "--translation"), translation_id: str = typer.Option("default", "--translation-id"), source_language: str = typer.Option("en", "--source-language"), target_language: str = typer.Option("es", "--target-language"), preferred: bool = typer.Option(True, "--preferred/--not-preferred")) -> None:
    entry = TranslationMemoryEntry(f"manual-{abs(hash((source, translation, translation_id)))}", source, translation, source_language, target_language, None, None, "", None, translation_id, "ACTIVE", preferred)
    saved = memory_manager(novel_id).add_translation_entry(entry)
    typer.echo(f"Added: {saved.source_text} -> {saved.translated_text} [{saved.status}]")


@memory_app.command("search")
def memory_search(novel_id: str = typer.Argument(...), text: str = typer.Argument(...), limit: int = typer.Option(20, "--limit", min=1)) -> None:
    entries = memory_manager(novel_id).find_relevant(text, max_items=limit)
    for entry in entries:
        typer.echo(f"{entry.source_text} -> {entry.translated_text} [{entry.status}]")


@context_app.command("show")
def context_show(novel_id: str = typer.Argument(...), chapter: int | None = typer.Option(None, "--chapter", min=1), limit: int = typer.Option(20, "--limit", min=1)) -> None:
    repo = repository()
    if chapter is not None:
        data = repo.load_chapter_context(novel_id, chapter)
        typer.echo(f"Chapter: {chapter:03d}")
        for item in data.get("summary", []):
            typer.echo(f"- {item}")
        typer.echo(f"Entities: {', '.join(data.get('entities', [])) or '-'}")
        return
    items = memory_manager(novel_id).load_context_memory()[-limit:]
    for item in items:
        typer.echo(f"[ch={item.chapter_number}] {item.text} ({', '.join(item.entities) or '-'})")


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
    pending = next((job for job in ResumeService(repository()).find_pending_jobs() if job.novel_id == novel_id), None)
    if pending and pending.stage and pending.stage.value == "ANALYZING":
        summary = analysis_service().analyze_novel(novel_id, limit=limit)
        typer.echo(f"Analysis resumed: {summary.analyzed_now} analyzed, {summary.pending} pending")
        return
    if pending and pending.stage and pending.stage.value == "VALIDATING":
        progress = repository().load_progress(novel_id)
        summary = validation_service_from_config().validate_novel(novel_id, translation_id=progress.get("translation_id") or "default", limit=limit, reuse_existing=True)
        typer.echo(f"Validation resumed: {summary.ok} OK, {summary.warnings} warnings, {summary.failed} failed")
        return
    if pending and pending.stage and pending.stage.value == "TRANSLATING":
        progress = repository().load_progress(novel_id)
        registry, options = translation_registry()
        try:
            summary = translation_service(registry, options).translate_novel(novel_id, translation_id=progress.get("translation_id") or "default", translator_id=str(options.get("provider", "mock")), source_language=options.get("source_language"), target_language=str(options.get("target_language", "es")), limit=limit)
        finally:
            close_translation_registry(registry)
        typer.echo(f"Translation resumed: {summary.chunks_translated} translated, {summary.pending} pending")
        return
    manager = access_manager()
    try:
        summary = download_service(manager).resume_novel(novel_id, limit=limit)
    finally:
        manager.close()
    _display_download_summary(summary)


@glossary_app.command("list")
def glossary_list(novel_id: str = typer.Argument(...)) -> None:
    for item in GlossaryManager(repository(), novel_id).list_terms():
        lock = " locked" if item.locked else ""
        typer.echo(f"{item.term} -> {item.translation or '-'} [{item.status.value}]{lock}")


@glossary_app.command("show")
def glossary_show(novel_id: str = typer.Argument(...), term: str = typer.Argument(...)) -> None:
    item = GlossaryManager(repository(), novel_id).get(term)
    if item is None:
        raise typer.BadParameter(f"Term not found: {term}")
    typer.echo(f"Term: {item.term}")
    typer.echo(f"Type: {item.type}")
    typer.echo(f"Translation: {item.translation or '-'}")
    typer.echo(f"Status: {item.status.value}")
    typer.echo(f"Locked: {item.locked}")


@glossary_app.command("lock")
def glossary_lock(novel_id: str = typer.Argument(...), term: str = typer.Argument(...)) -> None:
    item = GlossaryManager(repository(), novel_id).lock(term)
    typer.echo(f"Locked: {item.term}")


@glossary_app.command("set")
def glossary_set(novel_id: str = typer.Argument(...), term: str = typer.Argument(...), translation: str = typer.Option(..., "--translation")) -> None:
    manager = GlossaryManager(repository(), novel_id)
    if manager.exists(term):
        item = manager.update(term, translation=translation, status=GlossaryStatus.CONFIRMED, source="manual")
    else:
        item = manager.add(GlossaryTerm(term, "OTHER", translation, False, GlossaryStatus.CONFIRMED, "manual"))
    typer.echo(f"Updated: {item.term} -> {item.translation}")


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
    translation_id = progress.get("translation_id", "default") if progress else "default"
    translated_chunks = sum(len(repo.list_translation_chunks(novel_id, number, translation_id)) for number in chapter_numbers)
    typer.echo(f"Translated chunks: {translated_chunks}")
    validation_results = repo.list_validation_results(novel_id, translation_id)
    typer.echo(f"Validated OK: {sum(result.get('status') == 'OK' for result in validation_results)}")
    typer.echo(f"Warnings: {sum(result.get('status') == 'WARNING' for result in validation_results)}")
    typer.echo(f"Failed validation: {sum(result.get('status') == 'FAILED' for result in validation_results)}")
    typer.echo(f"Needs review: {sum(bool(result.get('needs_review')) for result in validation_results)}")
    export_dir = repo.root / novel_id / "exports"
    for export_format in ("epub", "txt", "json", "html"):
        typer.echo(f"Export {export_format.upper()}: {'yes' if any(export_dir.glob(f'*.{export_format}')) else 'no'}")
    if progress is None:
        typer.echo("Progress: not started")
        return
    typer.echo(f"Status: {progress.get('overall_status', 'UNKNOWN')}")
    typer.echo(f"Current task: {progress.get('current_stage', 'DOWNLOAD')}")
    typer.echo(f"Chapter: {progress.get('current_chapter', '-')}")
    typer.echo(f"Stage: {progress.get('current_stage', '-')}")
    typer.echo(f"Chunk: {progress.get('current_chunk', '-')} / {progress.get('total_chunks', '-')}")


@app.command()
def export(novel_id: str = typer.Argument(...), format: str = typer.Option("txt", "--format", help="Formato: txt, json, html o epub"), translation_id: str = typer.Option("default", "--translation-id"), include_warnings: bool = typer.Option(False, "--include-warnings"), overwrite: bool = typer.Option(False, "--overwrite"), allow_partial: bool = typer.Option(False, "--allow-partial"), from_chapter: int | None = typer.Option(None, "--from-chapter", min=0), to_chapter: int | None = typer.Option(None, "--to-chapter", min=0)) -> None:
    try:
        result = ExportService(repository()).export_novel(novel_id, format_id=format, translation_id=translation_id, include_warnings=include_warnings, overwrite=overwrite, allow_partial=allow_partial, from_chapter=from_chapter, to_chapter=to_chapter)
    except (ExportError, KeyError, ValueError, OSError) as error:
        typer.echo(f"Export failed: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"Format: {result.format}")
    typer.echo(f"Output: {result.output_path}")
    typer.echo(f"Chapters exported: {result.chapters_exported}")
    typer.echo(f"Chapters skipped: {result.chapters_skipped}")
    for warning in result.warnings:
        typer.echo(f"Warning: {warning}")
    return


@app.command("capture-html")
def capture_html(
    url: str = typer.Argument(..., help="URL de la novela"),
    from_chapter: int = typer.Option(..., "--from-chapter", min=1, help="Primer capítulo incluido"),
    to_chapter: int = typer.Option(..., "--to-chapter", min=1, help="Último capítulo incluido"),
    delay_seconds: float = typer.Option(30.0, "--delay-seconds", min=15.0, help="Pausa mínima entre capítulos"),
    overwrite: bool = typer.Option(False, "--overwrite", help="Reemplaza HTML ya capturado"),
) -> None:
    """Guarda HTML visible usando una sola ventana de navegador asistido."""
    manager = None
    try:
        manager = access_manager(assisted_browser=True)
        registry = default_registry(manager)
        source = registry.resolve(url)
        novel = source.get_novel(url)
        chapters = source.get_chapters(novel)
        browser = manager.browser_client
        if browser is None:
            raise RuntimeError("No se pudo inicializar el navegador asistido")
        summary = BrowserCaptureService(browser, DATA_ROOT / "sessions" / "captures").capture(
            novel,
            chapters,
            from_chapter=from_chapter,
            to_chapter=to_chapter,
            delay_seconds=delay_seconds,
            overwrite=overwrite,
        )
    except (NovelTranslatorError, KeyError, ValueError, OSError, RuntimeError) as error:
        typer.echo(f"Captura detenida: {error}", err=True)
        raise typer.Exit(code=1) from error
    finally:
        if manager is not None:
            manager.close()
    typer.echo(f"Novel: {summary.novel_id}")
    typer.echo(f"HTML capturados: {summary.captured}")
    typer.echo(f"Omitidos: {summary.skipped}")
    typer.echo(f"Fallidos: {summary.failed}")
    typer.echo(f"Directorio: {summary.output_directory}")


@app.command("import-html")
def import_html(
    novel_id: str = typer.Argument(..., help="Identificador local de novela"),
    directory: str | None = typer.Option(None, "--directory", help="Directorio con archivos NNN.html"),
    force: bool = typer.Option(False, "--force", help="Reemplaza source.json existentes"),
) -> None:
    """Importa HTML capturado localmente como source.json, sin usar la red."""
    root = directory or str(DATA_ROOT / "sessions" / "captures" / novel_id)
    try:
        summary = HtmlImportService(repository()).import_directory(novel_id, root, force=force)
    except (NovelTranslatorError, KeyError, ValueError, OSError) as error:
        typer.echo(f"Importación detenida: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"Novel: {summary.novel_id}")
    typer.echo(f"HTML importados: {summary.imported}")
    typer.echo(f"Omitidos: {summary.skipped}")
    typer.echo(f"Fallidos: {summary.failed}")
    typer.echo(f"Archivos revisados: {summary.total_files}")


@app.command("repair-source")
def repair_source(
    novel_id: str = typer.Argument(..., help="Identificador local de novela"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Solo informa sin modificar source.json"),
) -> None:
    """Corrige codificación mojibake en fuentes locales, sin usar la red."""
    repo = repository()
    normalizer = TextNormalizer()
    changed = 0
    for number in repo.list_chapters(novel_id):
        if not repo.source_exists(novel_id, number):
            continue
        payload = repo.load_source(novel_id, number)
        original = payload.get("paragraphs", [])
        repaired = normalizer.normalize(original)
        if repaired == original:
            continue
        changed += 1
        typer.echo(f"Codificación detectada: capítulo {number:03d}")
        if not dry_run:
            repo.save_source(novel_id, number, payload.get("language", "en"), repaired)
            repo.save_chapter_metadata(novel_id, number, {"status": "DOWNLOADED", "encoding_repaired": True})
    typer.echo(f"Capítulos corregibles: {changed}")
    typer.echo("Modo: simulación" if dry_run else "Fuentes corregidas")


@app.command("repair-translations")
def repair_translations(
    novel_id: str = typer.Argument(..., help="Identificador local de novela"),
    translation_id: str = typer.Option("default", "--translation-id", help="Traducción persistida a corregir"),
    from_chapter: int | None = typer.Option(None, "--from-chapter", min=1),
    to_chapter: int | None = typer.Option(None, "--to-chapter", min=1),
    dry_run: bool = typer.Option(False, "--dry-run", help="Solo informa sin modificar chunks"),
) -> None:
    """Corrige chunks existentes usando términos bloqueados del glosario."""
    try:
        summary = TranslationRepairService(repository()).repair_novel(
            novel_id,
            translation_id,
            from_chapter=from_chapter,
            to_chapter=to_chapter,
            dry_run=dry_run,
        )
    except (NovelTranslatorError, KeyError, ValueError, OSError) as error:
        typer.echo(f"Corrección detenida: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"Novel: {summary.novel_id}")
    typer.echo(f"Translation: {summary.translation_id}")
    typer.echo(f"Chunks revisados: {summary.chunks_scanned}")
    typer.echo(f"Chunks corregidos: {summary.chunks_changed}")
    typer.echo(f"Capítulos afectados: {summary.chapters_changed}")
    typer.echo(f"Reemplazos: {summary.replacements}")
    typer.echo("Modo: simulación" if dry_run else "Chunks corregidos")
