from .filesystem import JsonFilesystemRepository


class CacheStorage(JsonFilesystemRepository):
    """Named repository for cache data; invalidation policy comes later."""

