import logging
from datetime import datetime

import pytz

from config import Config

logger = logging.getLogger(__name__)


def calculate_seconds(interval: int, unit: str) -> int:
    seconds = 5 * 60  # default to five minutes
    if unit == "minute":
        seconds = interval * 60
    elif unit == "hour":
        seconds = interval * 60 * 60
    elif unit == "day":
        seconds = interval * 60 * 60 * 24
    else:
        logger.warning(f"Unrecognized unit: {unit}, defaulting to 5 minutes")
    return seconds


def get_timezone(tz_name: str | None):
    """Return a tzinfo for the provided timezone name using pytz.

    Falls back to UTC if the timezone string is invalid or missing.
    """
    try:
        if tz_name:
            return pytz.timezone(str(tz_name))
    except Exception as exc:
        logger.warning(f"Invalid timezone '{tz_name}', defaulting to UTC: {exc}")
    return pytz.UTC


def now_in_timezone(tz_name: str | None = "UTC") -> datetime:
    """Return timezone-aware current datetime for the given timezone name."""
    tz = get_timezone(tz_name)
    return datetime.now(tz)


def now_device_tz(device_config: Config) -> datetime:
    """Return timezone-aware current datetime using device configuration timezone."""
    try:
        tz_name = device_config.get_config("timezone", default="UTC")
    except Exception:
        tz_name = "UTC"
    return now_in_timezone(tz_name)
