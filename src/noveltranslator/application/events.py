"""Small progress-event contract shared by application services and the CLI."""

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class ProgressEvent:
    """A user-facing, non-persistent notification emitted while a service runs."""

    stage: str
    action: str
    novel_id: str
    chapter: int | None = None
    current: int | None = None
    total: int | None = None
    message: str = ""


ProgressCallback = Callable[[ProgressEvent], None]


def emit_progress(callback: ProgressCallback | None, event: ProgressEvent) -> None:
    """Notify an optional observer without making UI failures break processing."""

    if callback is None:
        return
    try:
        callback(event)
    except Exception:
        # Progress is observational. A broken terminal/UI must not invalidate a
        # downloaded or translated artifact.
        return
