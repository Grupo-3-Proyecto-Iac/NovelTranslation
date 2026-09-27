from abc import ABC, abstractmethod

from .models import TranslationRequest, TranslationResult


class Translator(ABC):
    @property
    @abstractmethod
    def id(self) -> str:
        raise NotImplementedError

    @property
    @abstractmethod
    def model_id(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def translate(self, request: TranslationRequest) -> TranslationResult:
        raise NotImplementedError

    def translate_batch(self, requests: list[TranslationRequest]) -> list[TranslationResult]:
        """Translate several requests while preserving their order."""
        return [self.translate(request) for request in requests]

    def close(self) -> None:
        pass
