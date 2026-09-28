import hashlib
import re

from noveltranslator.core.models import GlossaryTerm


class ProtectedTermProtector:
    """Replaces locked/preserve terms with collision-resistant placeholders."""

    def split(self, text: str, terms: list[GlossaryTerm]) -> list[tuple[bool, str, GlossaryTerm | None]]:
        """Split text so protected glossary terms never enter the model.

        Returning literal translated segments avoids relying on model-specific
        placeholder preservation, which Marian can otherwise corrupt.
        """
        protected = [term for term in terms if term.locked or term.preserve]
        protected.sort(key=lambda item: len(item.term), reverse=True)
        if not protected:
            return [(False, text, None)]
        pattern = re.compile("|".join(re.escape(term.term) for term in protected), re.IGNORECASE)
        result: list[tuple[bool, str, GlossaryTerm | None]] = []
        cursor = 0
        for match in pattern.finditer(text):
            if match.start() > cursor:
                result.append((False, text[cursor:match.start()], None))
            matched = next(term for term in protected if term.term.casefold() == match.group(0).casefold())
            replacement = matched.translation if matched.locked and matched.translation else match.group(0)
            result.append((True, replacement, matched))
            cursor = match.end()
        if cursor < len(text):
            result.append((False, text[cursor:], None))
        return result or [(False, text, None)]

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


class FormattingProtector:
    """Identifies formatting atoms that a translation model may normalize away."""

    _pattern = re.compile(
        r"[ \t]{2,}|\n+|\.{3,}|…+|\*+|[!?]{2,}|"
        r"\b[\w]+(?:[-–—][\w]+)+\b|(?<!\w)[-–—]{1,3}(?!\w)"
    )
    _hyphenated_pattern = re.compile(r"^\w+(?:[-–—]\w+)+$", re.UNICODE)
    _interjection_roots = {"ah", "ahem", "bang", "blah", "ha", "he", "hm", "hmm", "ho", "mm", "oof", "oh", "phew", "tch", "tsk", "tut", "ugh", "uh"}

    @classmethod
    def _is_format_atom(cls, value: str) -> bool:
        if not cls._hyphenated_pattern.fullmatch(value):
            return True
        parts = re.split(r"[-–—]", value.casefold())
        return any(part in cls._interjection_roots for part in parts) or len(set(parts)) == 1 or all(len(part) <= 3 for part in parts)

    def split(self, text: str) -> list[tuple[bool, str]]:
        """Split text into translatable parts and literal formatting atoms."""
        parts: list[tuple[bool, str]] = []
        cursor = 0
        for match in self._pattern.finditer(text):
            if not self._is_format_atom(match.group(0)):
                continue
            if match.start() > cursor:
                parts.append((False, text[cursor:match.start()]))
            parts.append((True, match.group(0)))
            cursor = match.end()
        if cursor < len(text):
            parts.append((False, text[cursor:]))
        return parts or [(False, text)]

    def protect(self, text: str) -> tuple[str, dict[str, str]]:
        replacements: dict[str, str] = {}

        def replace(match: re.Match[str]) -> str:
            value = match.group(0)
            if not self._is_format_atom(value):
                return value
            digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:8].upper()
            token = f"__NT_FMT_{len(replacements):04d}_{digest}__"
            while token in replacements or token in text:
                token = f"{token}_X"
            replacements[token] = value
            return token

        return self._pattern.sub(replace, text), replacements

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
        if re.search(r"__NT_(?:TERM|FMT)_[A-Z0-9_]+__", translated_text):
            raise ValueError("translation contains an unreplaced protected-term placeholder")
        for replacement in replacements.values():
            if replacement not in translated_text:
                raise ValueError(f"protected term missing from translation: {replacement}")
        return translated_text.strip()
