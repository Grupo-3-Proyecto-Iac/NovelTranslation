from noveltranslator.infrastructure.config import load_yaml


def test_example_configuration_loads() -> None:
    config = load_yaml("config/config.example.yaml")
    assert config["access"]["concurrency"] == 1
    assert config["retry"]["max_attempts"] == 3

