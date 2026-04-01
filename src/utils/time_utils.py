import logging
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

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
    """Return a tzinfo for the provided timezone name using zoneinfo.

    Falls back to UTC if the timezone string is invalid or missing.
    """
    try:
        if tz_name:
            return ZoneInfo(str(tz_name))
    except Exception as exc:
        logger.warning(f"Invalid timezone '{tz_name}', defaulting to UTC: {exc}")
    return UTC


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
        if "-" in part:
            start_s, end_s = part.split("-", 1)
            try:
                start, end = int(start_s), int(end_s)
            except ValueError:
                continue
            if start > end:
                start, end = end, start
            values.update(v for v in range(start, end + 1) if min_val <= v <= max_val)
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
    from datetime import timedelta

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
