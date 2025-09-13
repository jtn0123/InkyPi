import pytz

from utils.time_utils import get_timezone, now_in_timezone


def test_get_timezone_valid():
    tz = get_timezone("US/Eastern")
    assert tz == pytz.timezone("US/Eastern")


def test_get_timezone_invalid():
    tz = get_timezone("Invalid/Zone")
    assert tz == pytz.UTC


def test_get_timezone_none():
    tz = get_timezone(None)
    assert tz == pytz.UTC


def test_now_in_timezone_returns_aware_datetime():
    dt = now_in_timezone("US/Eastern")
    assert dt.tzinfo is not None
    assert dt.tzinfo.zone == "US/Eastern"


def test_now_in_timezone_default_utc():
    dt = now_in_timezone()
    assert dt.tzinfo is not None
    assert dt.tzinfo.zone == "UTC"
