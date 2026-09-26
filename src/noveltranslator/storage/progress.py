from noveltranslator.core.models import ProgressRecord

from .filesystem import JsonFilesystemRepository


class ProgressStorage:
    def __init__(self, repository: JsonFilesystemRepository) -> None:
        self.repository = repository

    def save(self, record: ProgressRecord) -> None:
        self.repository.save_json("progress.json", record.__dict__ | {"state": record.state.value})

    def load(self) -> dict:
        return self.repository.load_json("progress.json")

