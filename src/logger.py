"""Loguru-based structured logging setup."""
import os
import sys
from loguru import logger


def setup_logging(debug: bool = False, log_file: str = "backend/backend.log"):
    """Configure loguru with console + file sinks."""
    logger.remove()

    level = "DEBUG" if debug else os.environ.get("LOG_LEVEL", "INFO")

    logger.add(
        sys.stdout,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan> — <level>{message}</level>",
        level=level,
        colorize=True,
    )

    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    logger.add(
        log_file,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function} — {message}",
        level=level,
        rotation="50 MB",
        retention="30 days",
        compression="gz",
    )

    return logger
