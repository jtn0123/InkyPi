# pyright: reportMissingImports=false
"""Tests for utils/time_utils.py — additional coverage."""
import pytz

from utils.time_utils import (
    get_timezone,
    now_device_tz,
    now_in_timezone,
    parse_cron_field,
)


def test_get_timezone_valid():
    tz = get_timezone("US/Eastern")
    assert tz is not None
    assert str(tz) == "US/Eastern"


def test_get_timezone_invalid():
    tz = get_timezone("Invalid/Timezone")
    assert tz == pytz.UTC


def test_get_timezone_none():
    tz = get_timezone(None)
    assert tz == pytz.UTC


def test_now_in_timezone_returns_aware_datetime():
    result = now_in_timezone("US/Pacific")
    assert result.tzinfo is not None
    assert (
        "Pacific" in str(result.tzinfo)
        or "PST" in str(result.tzinfo)
        or "PDT" in str(result.tzinfo)
    )


def test_now_in_timezone_defaults_to_utc():
    result = now_in_timezone()
    assert result.tzinfo is not None


def test_now_device_tz_reads_from_config():
    class FakeConfig:
        def get_config(self, key, default=None):
            return "US/Eastern"

    result = now_device_tz(FakeConfig())
    assert result.tzinfo is not None


def test_now_device_tz_falls_back_on_exception():
    class BadConfig:
        def get_config(self, key, default=None):
            raise RuntimeError("config broken")

    result = now_device_tz(BadConfig())
    assert result.tzinfo is not None


def test_parse_cron_field_wildcard():
    result = parse_cron_field("*", 0, 59)
    assert result == set(range(0, 60))


def test_parse_cron_field_range():
    result = parse_cron_field("1-5", 0, 59)
    assert result == {1, 2, 3, 4, 5}


def test_parse_cron_field_list():
    result = parse_cron_field("1,3,5", 0, 59)
    assert result == {1, 3, 5}


def test_parse_cron_field_invalid_range():
    """Range with non-integer parts should be skipped."""
    result = parse_cron_field("a-b", 0, 59)
    assert result == set()
