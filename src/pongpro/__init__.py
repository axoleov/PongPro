"""PongPro - a production-grade Ping Pong game for Windows 10 / Python 3.12.

Public package surface.  Importing this package must never touch the display
or audio subsystems so that unit tests can import gameplay logic headlessly.
"""

from __future__ import annotations

__all__ = ["__version__", "APP_NAME", "BUILD_CHANNEL"]

__version__ = "1.0.0"
APP_NAME = "PongPro"
BUILD_CHANNEL = "stable"
