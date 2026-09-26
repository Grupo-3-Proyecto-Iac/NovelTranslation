from dataclasses import dataclass, field


@dataclass(frozen=True)
class GenericSourceConfig:
    name: str
    domains: tuple[str, ...] = field(default_factory=tuple)

