import hashlib
import re

from noveltranslator.core.models import GlossaryTerm


class ProtectedTermProtector:
    """Replaces locked/preserve terms with collision-resistant placeholders."""

    def protect(self, text: str, terms: list[GlossaryTerm]) -> tuple[str, dict[str, str], list[GlossaryTerm]]:
        protected = [term for term in terms if term.locked or term.preserve]
        protected.sort(key=lambda item: len(item.term), reverse=True)
        replacements: dict[str, str] = {}
        used_terms: list[GlossaryTerm] = []
        protected_text = text
        for index, term in enumerate(protected, start=1):
            if term.term not in protected_text:
                continue
            digest = hashlib.sha1(term.term.encode("utf-8")).hexdigest()[:8].upper()
            token = f"__NT_TERM_{index:04d}_{digest}__"
            suffix = 1
            while token in text or token in replacements:
                token = f"__NT_TERM_{index:04d}_{digest}_{suffix}__"
                suffix += 1
            protected_text = protected_text.replace(term.term, token)
            replacements[token] = term.translation if term.locked and term.translation else term.term
            used_terms.append(term)
        return protected_text, replacements, used_terms

    @staticmethod
    def restore(text: str, replacements: dict[str, str]) -> str:
        restored = text
        for token, value in replacements.items():
            restored = restored.replace(token, value)
        return restored


class TranslationValidator:
    def validate(self, translated_text: str, replacements: dict[str, str]) -> str:
        if not isinstance(translated_text, str) or not translated_text.strip():
            raise ValueError("translation is empty")
        if re.search(r"__NT_TERM_[A-Z0-9_]+__", translated_text):
            raise ValueError("translation contains an unreplaced protected-term placeholder")
        for replacement in replacements.values():
            if replacement not in translated_text:
                raise ValueError(f"protected term missing from translation: {replacement}")
        return translated_text.strip()
