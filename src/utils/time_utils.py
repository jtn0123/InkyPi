import logging
import re
from datetime import UTC, datetime, timedelta, tzinfo
from typing import Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from utils import config_schema

logger = logging.getLogger(__name__)

# H:MM or HH:MM; which of these are real times is the schema's rule.
_HHMM_SHAPE = re.compile(r"([0-9]{1,2}):([0-9]{2})")
_PLAYLIST_TIME_RULE = ("playlist_config", "playlists", "start_time")


def format_hhmm(minutes: int) -> str:
    """The stored ``HH:MM`` for minutes past midnight (1440 is ``24:00``)."""
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def parse_hhmm(value: object) -> int:
    """Minutes past midnight for a playlist time; ``24:00`` is 1440.

    The one reader of playlist times. It accepts exactly the times the device
    config schema allows for a playlist's ``start_time`` (00:00 to 23:59, and
    24:00), and also a one-digit hour such as ``8:00`` as a person types it;
    :func:`format_hhmm` gives the two-digit form to store. Raises
    ``ValueError`` for anything else.
    """
    match = _HHMM_SHAPE.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        raise ValueError(f"not an HH:MM time: {value!r}")
    minutes = int(match[1]) * 60 + int(match[2])
    if not config_schema.matches_pattern(
        f"{match[1]:0>2}:{match[2]}", *_PLAYLIST_TIME_RULE
    ):
        raise ValueError(f"not a time from 00:00 to 24:00: {value!r}")
    return minutes


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


def get_timezone(tz_name: str | None) -> tzinfo:
    """Return a tzinfo for the provided timezone name using zoneinfo.

    Falls back to UTC if the timezone string is invalid or missing. Never
    raises: a name longer than the filesystem allows makes ``ZoneInfo``
    raise ``OSError``.
    """
    try:
        if tz_name:
            return ZoneInfo(str(tz_name))
    except (ZoneInfoNotFoundError, ValueError, OSError) as exc:
        logger.warning("Invalid timezone '%s', defaulting to UTC: %s", tz_name, exc)
    return UTC


def now_in_timezone(tz_name: str | None = "UTC") -> datetime:
    """Return timezone-aware current datetime for the given timezone name."""
    tz = get_timezone(tz_name)
    return datetime.now(tz)


class TimezoneConfigLike(Protocol):
    def get_config(self, key: str, default: object = None) -> object: ...


def now_device_tz(device_config: TimezoneConfigLike | None) -> datetime:
    """Return "now" in the device's time zone, or in UTC without a config.

    Never raises: an unreadable or invalid time zone gives UTC (and
    :func:`get_timezone` logs why), so callers need no fallback of their own.
    """
    if device_config is None:
        return datetime.now(UTC)
    try:
        tz_name = device_config.get_config("timezone", default="UTC")
    except Exception:
        tz_name = "UTC"
    return now_in_timezone(tz_name if isinstance(tz_name, str) else None)


def parse_cron_field(field: str, min_val: int, max_val: int) -> set[int]:
    """Parse a basic cron field into allowed integer values."""
    field = (field or "").strip()
    if field == "*":
        return set(range(min_val, max_val + 1))

    values: set[int] = set()
    for part in field.split(","):
        part = part.strip()
        if not part:
            continue
        # Step syntax: "*/N" and "a-b/N". Without this, int("*/6") raises and
        # the part is skipped, so "*/6" silently parsed to the empty set — a
        # schedule that never fires rather than an error.
        step = 1
        if "/" in part:
            part, _, step_s = part.partition("/")
            try:
                step = int(step_s)
            except ValueError:
                continue
            if step < 1:
                continue
            part = part.strip()
            if part == "*":
                part = f"{min_val}-{max_val}"
        if "-" in part:
            start_s, end_s = part.split("-", 1)
            try:
                start, end = int(start_s), int(end_s)
            except ValueError:
                continue
            if start > end:
                start, end = end, start
            values.update(
                v for v in range(start, end + 1, step) if min_val <= v <= max_val
            )
        else:
            try:
                value = int(part)
            except ValueError:
                continue
            if min_val <= value <= max_val:
                values.add(value)
    return values


def get_next_occurrence(cron_expr: str, now: datetime | None = None) -> datetime | None:
    """Return next datetime matching a simple 5-field cron expression.

    Supported fields: minute hour day-of-month month day-of-week.
    """
    if now is None:
        now = datetime.now(UTC)

    parts = cron_expr.split()
    if len(parts) != 5:
        return None

    minute_f, hour_f, dom_f, month_f, dow_f = parts
    dom_is_wildcard = dom_f.strip() == "*"
    dow_is_wildcard = dow_f.strip() == "*"
    minutes = parse_cron_field(minute_f, 0, 59)
    hours = parse_cron_field(hour_f, 0, 23)
    dom = parse_cron_field(dom_f, 1, 31)
    months = parse_cron_field(month_f, 1, 12)
    dow = parse_cron_field(dow_f, 0, 6)

    candidate = now.replace(second=0, microsecond=0)
    for _ in range(60 * 24 * 366):  # up to 1 year search
        candidate += timedelta(minutes=1)
        if candidate.minute not in minutes:
            continue
        if candidate.hour not in hours:
            continue
        if candidate.month not in months:
            continue
        dom_match = candidate.day in dom
        # Python Monday=0..Sunday=6, cron Sunday=0. Map to cron style.
        cron_dow = (candidate.weekday() + 1) % 7
        dow_match = cron_dow in dow
        if dom_is_wildcard or dow_is_wildcard:
            if not (dom_match and dow_match):
                continue
        else:
            if not (dom_match or dow_match):
                continue
        return candidate
    return None
