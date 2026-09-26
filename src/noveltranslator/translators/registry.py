from .base import Translator


class TranslatorRegistry:
    def __init__(self) -> None:
        self._translators: dict[str, Translator] = {}

    def register(self, translator: Translator) -> None:
        self._translators[translator.id] = translator

    def resolve(self, translator_id: str) -> Translator:
        return self._translators[translator_id]

    def list(self) -> tuple[str, ...]:
        return tuple(sorted(self._translators))
