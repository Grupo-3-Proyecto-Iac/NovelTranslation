import pytest

from noveltranslator.infrastructure.config import load_yaml, validate_config


def test_example_configuration_loads() -> None:
    config = load_yaml("config/config.example.yaml")
    assert config["access"]["concurrency"] == 1
    assert config["retry"]["max_attempts"] == 3


@pytest.mark.parametrize(
    "config",
    [
        {"access": {"delay": {"min_seconds": 5, "max_seconds": 1}}},
        {"retry": {"max_attempts": 0}},
        {"validation": {"length_ratio": {"min": 3, "max": 2}}},
    ],
)
def test_invalid_configuration_fails_clearly(config) -> None:
    with pytest.raises(ValueError):
        validate_config(config)

