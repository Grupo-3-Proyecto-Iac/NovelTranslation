"""Optional local Hugging Face translation backend.

Dependencies are imported only when a translation is requested so the base
installation and CLI remain lightweight.
"""

import time

from noveltranslator.core.exceptions import TranslationFailedError, TranslatorUnavailableError

from .base import Translator
from .models import TranslationRequest, TranslationResult


class HuggingFaceTranslator(Translator):
    id = "huggingface"

    def __init__(self, model: str = "Helsinki-NLP/opus-mt-en-es", *, device: str = "cpu", max_input_tokens: int = 512, max_new_tokens: int = 512, tokenizer=None, model_instance=None) -> None:
        self._model = model
        self.device = device
        self.max_input_tokens = max(32, int(max_input_tokens))
        self.max_new_tokens = max(32, int(max_new_tokens))
        self._tokenizer = tokenizer
        self._model_instance = model_instance

    @property
    def model_id(self) -> str:
        return self._model

    def _load(self) -> None:
        if self._tokenizer is not None and self._model_instance is not None:
            return
        try:
            from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
        except ImportError as exc:
            raise TranslatorUnavailableError("Hugging Face backend requires the optional 'huggingface' dependencies. Install with: pip install -e \".[huggingface]\"") from exc
        try:
            self._tokenizer = AutoTokenizer.from_pretrained(self._model)
            self._model_instance = AutoModelForSeq2SeqLM.from_pretrained(self._model)
            if self.device != "cpu":
                self._model_instance = self._model_instance.to(self.device)
            self._model_instance.eval()
        except Exception as exc:
            raise TranslatorUnavailableError(f"Could not load Hugging Face model: {self._model}") from exc

    def translate(self, request: TranslationRequest) -> TranslationResult:
        started = time.monotonic()
        self._load()
        try:
            encoded = self._tokenizer(request.source_text, return_tensors="pt", truncation=True, max_length=self.max_input_tokens)
            if self.device != "cpu":
                encoded = {key: value.to(self.device) for key, value in encoded.items()}
            generated = self._model_instance.generate(**encoded, max_new_tokens=self.max_new_tokens, num_beams=4, early_stopping=True)
            text = self._tokenizer.decode(generated[0], skip_special_tokens=True).strip()
            if not text:
                raise TranslationFailedError("Hugging Face model returned an empty translation")
            return TranslationResult(text, self.id, self.model_id, request.source_language, request.target_language, elapsed_seconds=time.monotonic() - started)
        except TranslationFailedError:
            raise
        except Exception as exc:
            raise TranslationFailedError(f"Hugging Face translation failed: {type(exc).__name__}") from exc

    def close(self) -> None:
        self._tokenizer = None
        self._model_instance = None
