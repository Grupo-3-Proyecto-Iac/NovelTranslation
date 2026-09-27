"""Rich presentation for the single-command pipeline."""

from rich.console import Console
from rich.progress import BarColumn, Progress, TextColumn, TimeElapsedColumn, TimeRemainingColumn
from rich.text import Text

from noveltranslator.application.events import ProgressEvent


class RunProgress:
    """Renders service events as persistent stage progress bars and status text."""

    _labels = {
        "download": "Descarga",
        "analysis": "Análisis",
        "translation": "Traducción",
        "validation": "Validación",
        "export": "Exportación",
    }

    def __init__(self, console: Console | None = None) -> None:
        self.console = console or Console()
        self.progress = Progress(
            TextColumn("{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
            console=self.console,
        )
        self._tasks: dict[str, int] = {}

    def __enter__(self) -> "RunProgress":
        self.progress.start()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.progress.stop()

    def __call__(self, event: ProgressEvent) -> None:
        label = self._labels.get(event.stage, event.stage.title())
        if event.action == "stage_started":
            total = max(1, event.total or 1)
            task_id = self.progress.add_task(f"{label}: {event.message}", total=total)
            self._tasks[event.stage] = task_id
            return

        task_id = self._tasks.get(event.stage)
        if task_id is None:
            return

        if event.action in {"item_started", "chunk_started", "chunk_skipped", "chunk_completed"}:
            if event.message:
                self.progress.update(task_id, description=f"{label}: {event.message}")
            return

        if event.action in {"item_completed", "item_skipped", "item_failed"}:
            task = self.progress.tasks[task_id]
            target = event.current if event.current is not None else int(task.completed) + 1
            self.progress.update(task_id, completed=min(target, int(task.total or target)), description=f"{label}: {event.message or 'procesando'}")
            return

        if event.action == "stage_completed":
            total = int(self.progress.tasks[task_id].total or event.total or 1)
            completed = min(int(event.current if event.current is not None else total), total)
            self.progress.update(task_id, completed=completed, description=f"{label}: {event.message or 'completado'}")

    def info(self, message: str) -> None:
        """Print a non-progress message without corrupting the live display."""

        self.progress.console.print(Text(message))
