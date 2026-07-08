"""Structured logging."""

from __future__ import annotations

import logging
import sys

_LOGGER = logging.getLogger("queud_aio")
_INTERACTIVE = False


def set_interactive_mode(enabled: bool = True) -> None:
    global _INTERACTIVE
    _INTERACTIVE = enabled


def setup_logging(
    level: int = logging.INFO,
    *,
    log_file: str | None = None,
    interactive: bool | None = None,
) -> None:
    if interactive is not None:
        set_interactive_mode(interactive)
    if _LOGGER.handlers:
        return

    if _INTERACTIVE and sys.stdout.isatty():
        console_fmt = logging.Formatter("%(message)s")
    else:
        console_fmt = logging.Formatter(
            "[%(asctime)s] %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S"
        )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(console_fmt)
    _LOGGER.addHandler(handler)
    if log_file:
        from pathlib import Path

        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(path, encoding="utf-8")
        file_handler.setFormatter(
            logging.Formatter(
                "[%(asctime)s] %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S"
            )
        )
        _LOGGER.addHandler(file_handler)
    _LOGGER.setLevel(level)


def log(message: str, *, level: int = logging.INFO) -> None:
    setup_logging()
    _LOGGER.log(level, message)


def warn(message: str) -> None:
    log(message, level=logging.WARNING)


def error(message: str) -> None:
    log(message, level=logging.ERROR)