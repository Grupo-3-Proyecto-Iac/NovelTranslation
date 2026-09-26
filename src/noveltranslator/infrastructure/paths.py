from pathlib import Path

from .config import load_yaml


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_ROOT = PROJECT_ROOT / "data"
CONFIG_ROOT = PROJECT_ROOT / "config"


def configured_novels_root() -> Path:
    config_path = CONFIG_ROOT / "config.yaml"
    if not config_path.is_file():
        config_path = CONFIG_ROOT / "config.example.yaml"
    configured = load_yaml(config_path).get("storage", {}).get("base_directory", "data/novels")
    path = Path(configured)
    return (PROJECT_ROOT / path if not path.is_absolute() else path).resolve()

