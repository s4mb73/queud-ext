"""Structured logging."""

from __future__ import annotations

import logging
import sys

_LOGGER = logging.getLogger("rugby_sa")


def setup_logging(level: int = logging.INFO) -> None:
    if _LOGGER.handlers:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("[%(asctime)s] %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")
    )
    _LOGGER.addHandler(handler)
    _LOGGER.setLevel(level)


def log(message: str, *, level: int = logging.INFO) -> None:
    setup_logging()
    _LOGGER.log(level, message)


def warn(message: str) -> None:
    log(message, level=logging.WARNING)


def error(message: str) -> None:
    log(message, level=logging.ERROR)