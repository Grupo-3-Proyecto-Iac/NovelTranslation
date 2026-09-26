"""Central JSON serialization helpers used by every storage component."""

import json
import os
import tempfile
import logging
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from noveltranslator.core.exceptions import CorruptedDataError, StorageError

logger = logging.getLogger("noveltranslator.storage")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def to_json_value(value: Any) -> Any:
    if is_dataclass(value):
        return to_json_value(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): to_json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_json_value(item) for item in value]
    return value


def write_json_atomic(path: str | Path, data: Any) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=".tmp", prefix=f"{destination.name}.",
            dir=destination.parent, delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            json.dump(to_json_value(data), handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, destination)
        logger.debug("JSON atomically written: %s", destination)
    except OSError as exc:
        raise StorageError(f"Could not atomically write JSON: {destination}") from exc
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink(missing_ok=True)


def read_json(path: str | Path) -> Any:
    source = Path(path)
    try:
        return json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        logger.error("Corrupted JSON detected: %s", source)
        raise CorruptedDataError(f"Corrupted JSON file: {source}") from exc
    except OSError as exc:
        raise StorageError(f"Could not read JSON file: {source}") from exc
