class NovelTranslatorError(Exception):
    """Base exception for expected application errors."""


class SourceNotFoundError(NovelTranslatorError):
    pass


class StorageError(NovelTranslatorError):
    pass


class CorruptedDataError(StorageError):
    """Raised when a persisted JSON document cannot be decoded."""


class NovelNotFoundError(StorageError):
    pass


class ChapterNotFoundError(StorageError):
    pass


class SourceError(NovelTranslatorError):
    """Base exception for source parsing and access failures."""


class AccessError(NovelTranslatorError):
    """Base exception for controlled network access failures."""


class AnalysisError(NovelTranslatorError):
    """Base exception for local analysis failures."""


class ValidationError(NovelTranslatorError):
    """Base exception for validation failures."""


class NovelMetadataNotFoundError(SourceError):
    pass


class ChapterContentNotFoundError(SourceError):
    pass


class InvalidChapterContentError(SourceError):
    pass


class AccessBlockedError(SourceError):
    pass


class TranslationError(NovelTranslatorError):
    pass


class TranslatorUnavailableError(TranslationError):
    pass


class TranslationTimeoutError(TranslationError):
    pass


class TranslationFailedError(TranslationError):
    pass


class InvalidTranslationError(TranslationError):
    pass


class ExportError(NovelTranslatorError):
    """Raised when an export cannot be assembled safely."""

