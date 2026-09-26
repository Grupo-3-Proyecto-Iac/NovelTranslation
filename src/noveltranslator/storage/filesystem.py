from pathlib import Path
from typing import Any

from noveltranslator.core.exceptions import StorageError

from .serialization import read_json, write_json_atomic


class JsonFilesystemRepository:
    """Small JSON repository rooted at a project data directory."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def _path(self, relative_path: str) -> Path:
        candidate = (self.root / relative_path).resolve()
        root = self.root.resolve()
        if candidate != root and root not in candidate.parents:
            raise StorageError("Repository path escapes its configured root")
        return candidate

    def save_json(self, relative_path: str, data: Any) -> None:
        path = self._path(relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json_atomic(path, data)

    def load_json(self, relative_path: str) -> Any:
        path = self._path(relative_path)
        return read_json(path)

    def exists(self, relative_path: str) -> bool:
        return self._path(relative_path).is_file()

