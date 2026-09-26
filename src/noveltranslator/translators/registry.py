class TranslatorRegistry:
    def __init__(self) -> None:
        self._translators = {}

    def register(self, translator) -> None:
        self._translators[translator.name] = translator

    def resolve(self, name: str):
        return self._translators[name]

