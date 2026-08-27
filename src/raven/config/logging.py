"""File-based application logging that does not corrupt the terminal display."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from platformdirs import user_log_path


def configure_logging() -> None:
    """Send Raven diagnostics to a bounded user-local log file."""
    raven_logger = logging.getLogger("raven")
    if any(getattr(handler, "name", None) == "raven-file" for handler in raven_logger.handlers):
        return
    log_directory = user_log_path("raven", appauthor=False)
    log_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    handler = RotatingFileHandler(
        log_directory / "raven.log",
        maxBytes=1_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    handler.name = "raven-file"
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    raven_logger.setLevel(logging.INFO)
    raven_logger.addHandler(handler)
    raven_logger.propagate = False
