import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


def configure_logging(log_directory: str | Path | None = None, level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger("noveltranslator")
    logger.setLevel(level)
    if not logger.handlers:
        logger.addHandler(logging.StreamHandler())
    if log_directory is not None:
        directory = Path(log_directory)
        directory.mkdir(parents=True, exist_ok=True)
        logger.addHandler(RotatingFileHandler(directory / "noveltranslator.log", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"))
    return logger

