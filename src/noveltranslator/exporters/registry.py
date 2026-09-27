from .base import Exporter


class ExporterRegistry:
    def __init__(self) -> None:
        self._exporters: dict[str, Exporter] = {}

    def register(self, exporter: Exporter) -> None:
        self._exporters[exporter.format_id] = exporter

    def resolve(self, format_id: str) -> Exporter:
        key = format_id.casefold()
        if key not in self._exporters:
            raise KeyError(f"Unsupported export format: {format_id}")
        return self._exporters[key]

    def list(self) -> tuple[str, ...]:
        return tuple(sorted(self._exporters))
