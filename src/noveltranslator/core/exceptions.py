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


class NovelMetadataNotFoundError(SourceError):
    pass


class ChapterContentNotFoundError(SourceError):
    pass


class InvalidChapterContentError(SourceError):
    pass


class AccessBlockedError(SourceError):
    pass

