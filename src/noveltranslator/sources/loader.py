from .registry import SourceRegistry


def load_sources(registry: SourceRegistry) -> SourceRegistry:
    """Load built-in and local extensions when they are implemented."""
    return registry

