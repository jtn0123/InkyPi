# pyright: reportMissingImports=false
"""Tests for utils/time_utils.py — additional coverage."""
import pytz
import pytest


def test_get_timezone_valid():
    from utils.time_utils import get_timezone

    tz = get_timezone("US/Eastern")
    assert tz is not None
    assert str(tz) == "US/Eastern"


def test_get_timezone_invalid():
    from utils.time_utils import get_timezone

    tz = get_timezone("Invalid/Timezone")
    assert tz == pytz.UTC


def test_get_timezone_none():
    from utils.time_utils import get_timezone

    tz = get_timezone(None)
    assert tz == pytz.UTC


def test_parse_cron_field_wildcard():
    from utils.time_utils import parse_cron_field

    result = parse_cron_field("*", 0, 59)
    assert result == set(range(0, 60))


def test_parse_cron_field_range():
    from utils.time_utils import parse_cron_field

    result = parse_cron_field("1-5", 0, 59)
    assert result == {1, 2, 3, 4, 5}


def test_parse_cron_field_list():
    from utils.time_utils import parse_cron_field

    result = parse_cron_field("1,3,5", 0, 59)
    assert result == {1, 3, 5}
