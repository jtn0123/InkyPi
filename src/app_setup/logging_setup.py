"""Logging configuration extracted from inkypi.py (JTN-289).

Two modes:
  * Plain text via the legacy logging.conf file (default)
  * Structured JSON via INKYPI_LOG_FORMAT=json
"""

from __future__ import annotations

import logging
import logging.config
import os


def use_json_logging() -> bool:
    """Return True when INKYPI_LOG_FORMAT=json is set."""
    fmt = (os.getenv("INKYPI_LOG_FORMAT") or "").strip().lower()
    return fmt == "json"


def setup_logging() -> None:
    """Configure root logging based on the INKYPI_LOG_FORMAT environment."""
    if use_json_logging():
        logging.config.dictConfig(
            {
                "version": 1,
                "disable_existing_loggers": False,
                "formatters": {
                    "json": {
                        "()": "utils.logging_utils.JsonFormatter",
                    }
                },
                "handlers": {
                    "console": {
                        "class": "logging.StreamHandler",
                        "level": os.getenv("INKYPI_LOG_LEVEL", "INFO").upper(),
                        "formatter": "json",
                        "stream": "ext://sys.stdout",
                    }
                },
                "root": {
                    "level": os.getenv("INKYPI_LOG_LEVEL", "INFO").upper(),
                    "handlers": ["console"],
                },
            }
        )
    else:
        logging.config.fileConfig(
            os.path.join(
                os.path.dirname(os.path.dirname(__file__)), "config", "logging.conf"
            ),
            disable_existing_loggers=False,
        )


def install_dev_log_handler() -> None:
    """Attach the in-memory log handler used in development mode."""
    logger = logging.getLogger(__name__)
    try:
        from blueprints.settings import DevModeLogHandler

        dev_handler = DevModeLogHandler()
        dev_handler.setLevel(logging.DEBUG)
        logging.getLogger().addHandler(dev_handler)
        logger.info("Dev mode log handler enabled (in-memory buffer)")
    except Exception as e:
        logger.warning(f"Could not enable dev mode log handler: {e}")
