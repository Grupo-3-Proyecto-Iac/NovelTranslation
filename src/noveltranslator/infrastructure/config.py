from pathlib import Path
from typing import Any

import yaml


def load_yaml(path: str | Path) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as handle:
        values = yaml.safe_load(handle) or {}
    if not isinstance(values, dict):
        raise ValueError("configuration root must be a mapping")
    return validate_config(values)


def validate_config(values: dict[str, Any]) -> dict[str, Any]:
    access = values.get("access", {}) or {}
    delay = access.get("delay", {}) or {}
    minimum = float(delay.get("min_seconds", 0))
    maximum = float(delay.get("max_seconds", 0))
    if minimum < 0 or maximum < 0 or minimum > maximum:
        raise ValueError("access.delay.min_seconds must be <= max_seconds and both must be non-negative")
    if int(access.get("requests_per_minute", 0)) < 0:
        raise ValueError("access.requests_per_minute must be non-negative")
    retry = values.get("retry", {}) or {}
    if int(retry.get("max_attempts", 3)) < 1:
        raise ValueError("retry.max_attempts must be positive")
    if float(retry.get("base_delay_seconds", 0)) < 0 or float(retry.get("max_delay_seconds", 0)) < 0:
        raise ValueError("retry delays must be non-negative")
    chunking = values.get("processing", {}).get("chunking", {}) or {}
    if int(chunking.get("max_characters", 6000)) < int(chunking.get("target_characters", 4500)):
        raise ValueError("processing.chunking.target_characters must be <= max_characters")
    memory = values.get("memory", {}) or {}
    if int(memory.get("translation", {}).get("max_entries_per_request", 20)) < 0 or int(memory.get("context", {}).get("max_items", 20)) < 0:
        raise ValueError("memory limits must be non-negative")
    validation = values.get("validation", {}) or {}
    ratio = validation.get("length_ratio", {}) or {}
    if float(ratio.get("min", 0.35)) <= 0 or float(ratio.get("min", 0.35)) > float(ratio.get("max", 2.50)):
        raise ValueError("validation.length_ratio.min must be positive and <= max")
    return values

