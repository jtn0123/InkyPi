"""``now_device_tz`` never raises, so callers need no fallback of their own.

main.py, the playlist blueprint and history each wrapped it in their own
try/except because ``ZoneInfo`` can raise ``OSError`` (a name longer than
the filesystem allows), which ``get_timezone`` didn't catch.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from utils.time_utils import get_timezone, now_device_tz


class _Config:
    def __init__(self, timezone: object) -> None:
        self.timezone = timezone

    def get_config(self, key: str, default: object = None) -> object:
        return self.timezone if key == "timezone" else default


class _BrokenConfig:
    def get_config(self, key: str, default: object = None) -> object:
        raise RuntimeError("config unreadable")


def _close_to_now(value: datetime) -> bool:
    return abs((value - datetime.now(UTC)).total_seconds()) < 5


def _is_utc(value: datetime) -> bool:
    return value.utcoffset() == timedelta(0)


@pytest.mark.parametrize(
    "name",
    ["Not/AZone", "America", "../etc/passwd", "UTC\x00", "A" * 300, "", None, 42],
    ids=[
        "unknown",
        "directory",
        "traversal",
        "nul",
        "too-long",
        "empty",
        "none",
        "int",
    ],
)
def test_a_bad_time_zone_gives_utc(name: object) -> None:
    now = now_device_tz(_Config(name))
    assert _is_utc(now)
    assert _close_to_now(now)


def test_get_timezone_survives_a_name_too_long_for_the_filesystem() -> None:
    assert get_timezone("A" * 300) is UTC


def test_an_unreadable_config_gives_utc() -> None:
    assert _is_utc(now_device_tz(_BrokenConfig()))


def test_no_config_gives_utc() -> None:
    assert _is_utc(now_device_tz(None))


def test_the_device_time_zone_is_used() -> None:
    now = now_device_tz(_Config("America/Los_Angeles"))
    assert now.tzinfo == ZoneInfo("America/Los_Angeles")
    assert _close_to_now(now)


def test_history_uses_the_device_time_zone(
    flask_app: Any, device_config_dev: Any
) -> None:
    from blueprints.history import _now_in_device_tz

    device_config_dev.update_value("timezone", "Asia/Tokyo")
    with flask_app.app_context():
        assert _now_in_device_tz().tzinfo == ZoneInfo("Asia/Tokyo")


def test_history_outside_an_app_gives_utc() -> None:
    from blueprints.history import _now_in_device_tz

    assert _is_utc(_now_in_device_tz())
