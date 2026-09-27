"""Central JSON serialization helpers used by every storage component."""

import json
import time
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

_ATOMIC_REPLACE_ATTEMPTS = 4
_ATOMIC_REPLACE_DELAYS = (0.05, 0.10, 0.20)


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
        replace_error: OSError | None = None
        for attempt in range(1, _ATOMIC_REPLACE_ATTEMPTS + 1):
            try:
                os.replace(temporary_path, destination)
                replace_error = None
                break
            except PermissionError as exc:
                replace_error = exc
                if attempt == _ATOMIC_REPLACE_ATTEMPTS:
                    raise
                delay = _ATOMIC_REPLACE_DELAYS[attempt - 1]
                logger.warning(
                    "Atomic JSON replace temporarily blocked; retrying in %.2fs (%d/%d): %s",
                    delay, attempt, _ATOMIC_REPLACE_ATTEMPTS, destination,
                )
                time.sleep(delay)
        if replace_error is not None:
            raise replace_error
        logger.debug("JSON atomically written: %s", destination)
    except OSError as exc:
        raise StorageError(
            f"Could not atomically write JSON: {destination} "
            f"({type(exc).__name__}: {exc})"
        ) from exc
    finally:
        if temporary_path is not None and temporary_path.exists():
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                logger.warning("Could not remove temporary JSON file: %s", temporary_path)


def read_json(path: str | Path) -> Any:
    source = Path(path)
    try:
        return json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        logger.error("Corrupted JSON detected: %s", source)
        raise CorruptedDataError(f"Corrupted JSON file: {source}") from exc
    except OSError as exc:
        raise StorageError(f"Could not read JSON file: {source}") from exc
