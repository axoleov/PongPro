"""Central logging configuration.

Uses a rotating file handler so a long-running kiosk/arcade install can never
fill the disk, plus a console handler during development.  A crash hook writes
a self-contained diagnostics report next to the log.
"""

from __future__ import annotations

import logging
import logging.handlers
import platform
import sys
import traceback
from pathlib import Path

from . import paths

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)-26s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_configured = False


def configure(level: int = logging.INFO, console: bool = True) -> Path:
    """Idempotently configure the root ``pongpro`` logger. Returns log file."""
    global _configured
    log_file = paths.log_dir() / "pongpro.log"

    root = logging.getLogger("pongpro")
    if _configured:
        return log_file
    _configured = True

    root.setLevel(level)
    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    file_handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG)
    root.addHandler(file_handler)

    if console:
        stream = logging.StreamHandler(sys.stdout)
        stream.setFormatter(formatter)
        stream.setLevel(level)
        root.addHandler(stream)

    root.debug("Logging initialised -> %s", log_file)
    return log_file


def install_crash_hook(app_version: str) -> None:
    """Write a diagnostic report if an unhandled exception escapes the loop."""

    def _hook(exc_type, exc_value, exc_tb) -> None:  # type: ignore[no-untyped-def]
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        report = paths.log_dir() / "crash_report.txt"
        try:
            lines = [
                f"{platform.platform()}",
                f"Python {sys.version}",
                f"PongPro {app_version}",
                "".join(traceback.format_exception(exc_type, exc_value, exc_tb)),
            ]
            report.write_text("\n".join(lines), encoding="utf-8")
        except OSError:
            pass
        logging.getLogger("pongpro").critical(
            "Unhandled exception - crash report written to %s", report, exc_info=True
        )
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = _hook
