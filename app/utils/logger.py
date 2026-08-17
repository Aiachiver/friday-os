"""
Centralized logging for FRIDAY OS, built on loguru.

Every module should do:
    from app.utils.logger import get_logger
    log = get_logger(__name__)

instead of `print()` or the stdlib `logging` module directly.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from loguru import Logger

from loguru import logger

from app.core.config import get_settings

_CONFIGURED = False


def configure_logging() -> None:
    """Idempotent. Call once at app startup (main.py does this)."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    settings = get_settings()
    log_level = settings.get("logging.level", settings.secrets.log_level)
    rotate_mb = settings.get("logging.rotate_mb", 10)
    retain_days = settings.get("logging.retain_days", 14)

    log_dir = settings.user_data_root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    logger.remove()  # drop default handler so we control format/level

    logger.add(
        sys.stderr,
        level=log_level,
        colorize=True,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
            "<level>{message}</level>"
        ),
    )

    logger.add(
        log_dir / "friday.log",
        level=log_level,
        rotation=f"{rotate_mb} MB",
        retention=f"{retain_days} days",
        compression="zip",
        encoding="utf-8",
        backtrace=True,
        diagnose=False,  # keep False in prod: avoids leaking variable values in logs
    )

    _CONFIGURED = True


def get_logger(name: str) -> Logger:
    configure_logging()
    return logger.bind(module=name)
