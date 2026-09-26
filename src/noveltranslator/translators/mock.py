from .base import Translator
from .models import TranslationRequest, TranslationResult


class MockTranslator(Translator):
    id = "mock"
    model_id = "mock-v1"

    def __init__(self, mapping: dict[str, str] | None = None) -> None:
        self.mapping = mapping or {}
        self.calls = 0

    def translate(self, request: TranslationRequest) -> TranslationResult:
        self.calls += 1
        translated = self.mapping.get(request.source_text, f"[ES] {request.source_text}")
        return TranslationResult(translated, self.id, self.model_id, request.source_language, request.target_language, elapsed_seconds=0.0)
