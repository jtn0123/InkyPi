# pyright: reportMissingImports=false
"""Tests for utils/time_utils.py — additional coverage."""

from datetime import UTC
from typing import Any

from utils.time_utils import (
    get_timezone,
    now_device_tz,
    now_in_timezone,
    parse_cron_field,
)


def test_get_timezone_valid() -> None:
    tz = get_timezone("US/Eastern")
    assert tz is not None
    assert str(tz) == "US/Eastern"


def test_get_timezone_invalid() -> None:
    tz = get_timezone("Invalid/Timezone")
    assert tz == UTC


def test_get_timezone_none() -> None:
    tz = get_timezone(None)
    assert tz == UTC


def test_now_in_timezone_returns_aware_datetime() -> None:
    result = now_in_timezone("US/Pacific")
    assert result.tzinfo is not None
    assert (
        "Pacific" in str(result.tzinfo)
        or "PST" in str(result.tzinfo)
        or "PDT" in str(result.tzinfo)
    )


def test_now_in_timezone_defaults_to_utc() -> None:
    result = now_in_timezone()
    assert result.tzinfo is not None


def test_now_device_tz_reads_from_config() -> Any:
    class FakeConfig:
        def get_config(self, key: Any, default: Any = None) -> Any:
            return "US/Eastern"

    result = now_device_tz(FakeConfig())
    assert result.tzinfo is not None


def test_now_device_tz_falls_back_on_exception() -> None:
    class BadConfig:
        def get_config(self, key: Any, default: Any = None) -> None:
            raise RuntimeError("config broken")

    result = now_device_tz(BadConfig())
    assert result.tzinfo is not None


def test_parse_cron_field_wildcard() -> None:
    result = parse_cron_field("*", 0, 59)
    assert result == set(range(60))


def test_parse_cron_field_range() -> None:
    result = parse_cron_field("1-5", 0, 59)
    assert result == {1, 2, 3, 4, 5}


def test_parse_cron_field_list() -> None:
    result = parse_cron_field("1,3,5", 0, 59)
    assert result == {1, 3, 5}


def test_parse_cron_field_invalid_range() -> None:
    """Range with non-integer parts should be skipped."""
    result = parse_cron_field("a-b", 0, 59)
    assert result == set()
