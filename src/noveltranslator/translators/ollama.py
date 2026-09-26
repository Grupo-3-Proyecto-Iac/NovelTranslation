import time

import httpx

from noveltranslator.core.exceptions import TranslationFailedError, TranslationTimeoutError, TranslatorUnavailableError

from .base import Translator
from .models import TranslationRequest, TranslationResult
from .prompts import build_translation_prompt


class OllamaTranslator(Translator):
    """Optional local Ollama backend; it never starts or installs Ollama."""

    id = "ollama"

    def __init__(self, model: str = "qwen2.5:7b", endpoint: str = "http://127.0.0.1:11434/api/generate", timeout: float = 120.0, client: httpx.Client | None = None) -> None:
        self._model = model
        self.endpoint = endpoint
        self._client = client or httpx.Client(timeout=timeout)
        self._owns_client = client is None

    @property
    def model_id(self) -> str:
        return self._model

    def translate(self, request: TranslationRequest) -> TranslationResult:
        started = time.monotonic()
        payload = {"model": self._model, "prompt": build_translation_prompt(request), "stream": False, "options": {"temperature": 0}}
        try:
            response = self._client.post(self.endpoint, json=payload)
            response.raise_for_status()
            data = response.json()
            text = data.get("response")
            if not isinstance(text, str) or not text.strip():
                raise TranslationFailedError("Ollama returned an empty response")
            return TranslationResult(text.strip(), self.id, self.model_id, request.source_language, request.target_language, elapsed_seconds=time.monotonic() - started)
        except httpx.TimeoutException as exc:
            raise TranslationTimeoutError("Ollama request timed out") from exc
        except httpx.ConnectError as exc:
            raise TranslatorUnavailableError("Ollama server is unavailable") from exc
        except TranslationFailedError:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            raise TranslationFailedError("Ollama translation failed") from exc

    def close(self) -> None:
        if self._owns_client:
            self._client.close()
