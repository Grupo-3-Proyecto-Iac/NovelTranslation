from noveltranslator.translators.huggingface import HuggingFaceTranslator
from noveltranslator.translators.models import TranslationRequest


class FakeTokenizer:
    def __call__(self, text, **kwargs):
        return {"input_ids": [1], "attention_mask": [1]}

    def decode(self, generated, **kwargs):
        return "Traducción local"


class FakeModel:
    def eval(self):
        return self

    def generate(self, **kwargs):
        return [[1, 2]]


def test_huggingface_backend_is_lazy_and_supports_injected_model() -> None:
    translator = HuggingFaceTranslator(tokenizer=FakeTokenizer(), model_instance=FakeModel())
    result = translator.translate(TranslationRequest("Hello", "en", "es", "Novel", "Chapter", 1, 1))
    assert translator.id == "huggingface"
    assert result.translated_text == "Traducción local"
    assert result.model_id == "Helsinki-NLP/opus-mt-en-es"
