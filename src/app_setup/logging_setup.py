"""Logging configuration extracted from inkypi.py (JTN-289).

Two modes:
  * Plain text via the legacy logging.conf file (default)
  * Structured JSON via INKYPI_LOG_FORMAT=json

Optional rotating file output is attached when ``INKYPI_LOG_FILE`` is set.
Rotation parameters (``maxBytes``, ``backupCount``) are read from the
``[rotating_file]`` section of ``src/config/logging.conf`` so the conf file
is the single source of truth for rotation (JTN-712).
"""

from __future__ import annotations

import configparser
import logging
import logging.config
import logging.handlers
import os
import time
from typing import NamedTuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from utils.logging_utils import SecretRedactionFilter, set_log_timezone

_LOGGING_CONF_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "config", "logging.conf"
)


class RotationConfig(NamedTuple):
    """Rotation parameters parsed from logging.conf's [rotating_file] section."""

    max_bytes: int
    backup_count: int
    level: str
    formatter: str


class ExpectedSSEDisconnectFilter(logging.Filter):
    """Drop normal browser disconnect chatter from Waitress SSE streams."""

    _PATHS = ("/api/events", "/api/progress/stream")

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        if "Client disconnected while serving" not in message:
            return True
        return not any(path in message for path in self._PATHS)


def use_json_logging() -> bool:
    """Return True when INKYPI_LOG_FORMAT=json is set."""
    fmt = (os.getenv("INKYPI_LOG_FORMAT") or "").strip().lower()
    return fmt == "json"


def configure_log_timezone(tz_name: str | None) -> None:
    """Align process and structured-log timestamps with the device timezone."""
    try:
        ZoneInfo(str(tz_name)) if tz_name else ZoneInfo("UTC")
    except (ZoneInfoNotFoundError, ValueError):
        set_log_timezone("UTC")
        os.environ["TZ"] = "UTC"
        if hasattr(time, "tzset"):
            time.tzset()
        return

    selected = str(tz_name or "UTC")
    set_log_timezone(selected)
    os.environ["TZ"] = selected
    if hasattr(time, "tzset"):
        time.tzset()


def install_waitress_disconnect_filter() -> None:
    """Suppress expected SSE client-close lines from the Waitress logger."""
    waitress_logger = logging.getLogger("waitress")
    if not any(
        isinstance(f, ExpectedSSEDisconnectFilter) for f in waitress_logger.filters
    ):
        waitress_logger.addFilter(ExpectedSSEDisconnectFilter())


def read_rotation_config(conf_path: str = _LOGGING_CONF_PATH) -> RotationConfig:
    """Parse [rotating_file] from logging.conf and return rotation params.

    Raises:
        ValueError: if the section is missing, maxBytes <= 0, or
            backupCount <= 0. Rotation is load-bearing for 16GB SD cards
            (JTN-712); a misconfigured rotation section is a startup error
            rather than a silent fallback to an unbounded file.
    """
    parser = configparser.ConfigParser()
    parser.read(conf_path)
    section_name = "rotating_file"
    if section_name not in parser:
        raise ValueError(
            f"logging.conf missing required [{section_name}] section at {conf_path}"
        )
    section = parser[section_name]
    max_bytes = int(section.get("maxBytes", "0"))
    backup_count = int(section.get("backupCount", "0"))
    if max_bytes <= 0:
        raise ValueError(
            f"logging.conf [{section_name}] maxBytes must be > 0 (got {max_bytes})"
        )
    if backup_count <= 0:
        raise ValueError(
            f"logging.conf [{section_name}] backupCount must be > 0 "
            f"(got {backup_count})"
        )
    return RotationConfig(
        max_bytes=max_bytes,
        backup_count=backup_count,
        level=section.get("level", "INFO"),
        formatter=section.get("formatter", "fileFormatter"),
    )


def _build_rotation_formatter(
    conf_path: str, formatter_key: str
) -> logging.Formatter | None:
    """Read [formatter_<key>] from logging.conf and build a Formatter.

    Uses RawConfigParser so %(levelname)s-style patterns aren't treated as
    configparser interpolation tokens.
    """
    parser = configparser.RawConfigParser()
    parser.read(conf_path)
    section_name = f"formatter_{formatter_key}"
    if section_name not in parser:
        return None
    fmt = parser[section_name].get("format")
    datefmt = parser[section_name].get("datefmt")
    return logging.Formatter(fmt=fmt, datefmt=datefmt)


def attach_rotating_file_handler(
    log_path: str,
    conf_path: str = _LOGGING_CONF_PATH,
) -> logging.handlers.RotatingFileHandler:
    """Attach a RotatingFileHandler to the root logger and return it.

    Rotation parameters come from [rotating_file] in logging.conf so the
    conf file is the single source of truth (JTN-712).
    """
    cfg = read_rotation_config(conf_path)
    os.makedirs(os.path.dirname(log_path) or ".", exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        log_path,
        maxBytes=cfg.max_bytes,
        backupCount=cfg.backup_count,
    )
    handler.setLevel(cfg.level.upper())
    formatter = _build_rotation_formatter(conf_path, cfg.formatter)
    if formatter is not None:
        handler.setFormatter(formatter)
    logging.getLogger().addHandler(handler)
    return handler


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
            _LOGGING_CONF_PATH,
            disable_existing_loggers=False,
        )

    # Attach the secret-redaction filter to the root logger so it applies to
    # ALL handlers (console, file, dev-mode buffer) and both log formats.
    logging.getLogger().addFilter(SecretRedactionFilter())
    install_waitress_disconnect_filter()

    # Optional rotating file output — only attached when an explicit path is
    # provided via env var, preserving the default console-only behavior.
    log_file = (os.getenv("INKYPI_LOG_FILE") or "").strip()
    if log_file:
        try:
            attach_rotating_file_handler(log_file)
        except (OSError, ValueError) as exc:
            logging.getLogger(__name__).warning(
                "Could not attach rotating file handler at %s: %s", log_file, exc
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
