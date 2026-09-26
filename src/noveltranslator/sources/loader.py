from .registry import SourceRegistry
from .lorenovels import LorenovelsSource
from noveltranslator.access.manager import AccessManager


def load_sources(registry: SourceRegistry, access_manager: AccessManager | None = None) -> SourceRegistry:
    """Register built-in sources; local extensions can be added later."""
    registry.register(LorenovelsSource(access_manager))
    return registry


def default_registry(access_manager: AccessManager | None = None) -> SourceRegistry:
    return load_sources(SourceRegistry(), access_manager)

