"""The refresh loop sleeps until the next refresh is due, not a fixed interval."""

from __future__ import annotations

import threading
from collections import deque
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from model import Playlist, PlaylistManager, RefreshInfo
from refresh_task import schedule
from refresh_task.scheduler import RefreshScheduler

NOW = datetime(2026, 11, 14, 12, 0, 30, tzinfo=UTC)
HOUR = 3600.0
CLOCK = {"plugin_id": "clock", "name": "Clock", "plugin_settings": {}, "refresh": {}}


def _manager(*playlists: Playlist) -> PlaylistManager:
    return PlaylistManager(list(playlists))


def _all_day(cycle: int | None = None, plugins: bool = True) -> Playlist:
    return Playlist(
        "Default",
        "00:00",
        "24:00",
        plugins=[CLOCK] if plugins else [],
        cycle_interval_seconds=cycle,
    )


def _wait(
    manager: PlaylistManager,
    latest: datetime | None,
    last_attempt: datetime | None = None,
    device_interval: float = HOUR,
) -> float:
    return schedule.seconds_until_next_check(
        playlist_manager=manager,
        latest_refresh=latest,
        last_attempt=last_attempt,
        now=NOW,
        device_interval=device_interval,
    )


@pytest.mark.parametrize(
    ("override", "expected"),
    [(300, 300.0), (None, HOUR), (0, HOUR), (-5, HOUR), (True, HOUR)],
)
def test_effective_cycle_uses_a_valid_playlist_override(
    override: Any, expected: float
) -> None:
    playlist = _all_day()
    playlist.cycle_interval_seconds = override
    assert schedule.effective_cycle_seconds(playlist, HOUR) == expected


class _IntervalConfig:
    def __init__(self, value: object) -> None:
        self.value = value

    def get_config(self, key: str, default: object = None) -> object:
        assert key == "plugin_cycle_interval_seconds"
        return self.value


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (900, 900.0),
        (90.5, 90.5),
        ("600", 600.0),
        ("", HOUR),
        ("soon", HOUR),
        (None, HOUR),
        (True, HOUR),
        (0, HOUR),
        (-30, HOUR),
    ],
)
def test_device_interval_reads_the_setting_with_the_loops_fallbacks(
    raw: object, expected: float
) -> None:
    assert schedule.device_interval_seconds(_IntervalConfig(raw)) == expected


def test_device_interval_survives_a_config_read_failure() -> None:
    class _Broken:
        def get_config(self, key: str, default: object = None) -> object:
            raise RuntimeError("config read failed")

    assert schedule.device_interval_seconds(_Broken()) == HOUR


@pytest.mark.parametrize(
    ("seconds", "minutes"), [(HOUR, 60), (300.0, 5), (90.0, 1), (30.0, 1)]
)
def test_cycle_minutes_is_whole_minutes_and_never_zero(
    seconds: float, minutes: int
) -> None:
    assert schedule.cycle_minutes(seconds) == minutes


def test_last_attempt_comes_from_the_running_scheduler() -> None:
    attempt = NOW - timedelta(minutes=3)
    task = SimpleNamespace(scheduler=SimpleNamespace(last_attempt=attempt))

    assert schedule.last_attempt_of(task) == attempt
    assert schedule.last_attempt_of(None) is None
    # A mock task in the web tests mustn't leak a non-datetime into the math.
    task.scheduler.last_attempt = object()
    assert schedule.last_attempt_of(task) is None


def test_an_override_shorter_than_the_device_interval_is_honoured() -> None:
    manager = _manager(_all_day(cycle=300))
    assert _wait(manager, NOW - timedelta(seconds=60)) == pytest.approx(240)


def test_an_override_longer_than_the_device_interval_waits_in_steps() -> None:
    manager = _manager(_all_day(cycle=7200))
    assert _wait(manager, NOW - timedelta(minutes=10)) == HOUR
    # One device interval later it sleeps only the rest of the cycle.
    later = schedule.seconds_until_next_check(
        playlist_manager=manager,
        latest_refresh=NOW - timedelta(minutes=10),
        last_attempt=None,
        now=NOW + timedelta(seconds=HOUR),
        device_interval=HOUR,
    )
    assert later == pytest.approx(7200 - 600 - HOUR)


def test_an_overdue_refresh_after_boot_runs_promptly() -> None:
    manager = _manager(_all_day())
    assert _wait(manager, NOW - timedelta(hours=5)) == schedule.MIN_WAIT_SECONDS
    assert _wait(manager, None) == schedule.MIN_WAIT_SECONDS


def test_a_failed_or_skipped_attempt_waits_a_cycle_before_retrying() -> None:
    manager = _manager(_all_day(cycle=600))
    # latest_refresh is stale because the attempt failed; last_attempt
    # spaces the retry instead of spinning.
    wait = _wait(manager, NOW - timedelta(hours=5), last_attempt=NOW)
    assert wait == pytest.approx(600)


def test_the_wait_ends_when_a_playlist_window_changes() -> None:
    morning = Playlist("Morning", "06:00", "12:10", plugins=[CLOCK])
    manager = _manager(morning)
    # Due in an hour, but Morning ends at 12:10, 9.5 minutes from now.
    assert _wait(manager, NOW) == pytest.approx(9 * 60 + 30)


def test_with_no_active_playlist_it_wakes_when_the_next_one_starts() -> None:
    evening = Playlist("Evening", "12:20", "22:00", plugins=[CLOCK])
    assert _wait(_manager(evening), NOW) == pytest.approx(19 * 60 + 30)


def test_a_playlist_with_no_plugins_waits_the_device_interval() -> None:
    assert _wait(_manager(_all_day(plugins=False)), None) == HOUR


def test_a_future_refresh_time_from_clock_skew_waits_the_device_interval() -> None:
    manager = _manager(_all_day())
    assert _wait(manager, NOW + timedelta(days=1)) == HOUR


def test_a_naive_refresh_time_is_read_in_device_time() -> None:
    manager = _manager(_all_day(cycle=300))
    naive = (NOW - timedelta(seconds=100)).replace(tzinfo=None)
    assert _wait(manager, naive) == pytest.approx(200)


def test_window_change_ignores_bad_times() -> None:
    playlists = [Playlist("Bad", "nope", "25:00"), Playlist("Ok", "13:00", "14:00")]
    boundary = schedule.next_window_change(playlists, NOW)
    assert boundary == datetime(2026, 11, 14, 13, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# RefreshScheduler
# ---------------------------------------------------------------------------


class _Config:
    def __init__(self, manager: Any, refresh_time: datetime | None) -> None:
        self.manager = manager
        self.refresh_info = RefreshInfo(
            refresh_type="Playlist",
            plugin_id="clock",
            refresh_time=refresh_time.isoformat() if refresh_time else None,
            image_hash=None,
        )
        self.interval: object = HOUR

    def get_config(self, key: str, default: object = None) -> object:
        if key == "plugin_cycle_interval_seconds":
            return self.interval
        return default

    def get_playlist_manager(self) -> Any:
        return self.manager

    def get_refresh_info(self) -> Any:
        return self.refresh_info


def _scheduler(
    config: _Config, now: datetime = NOW
) -> tuple[RefreshScheduler, list[float]]:
    condition = threading.Condition()
    waits: list[float] = []

    def fake_wait(timeout: float | None = None) -> bool:
        waits.append(float(timeout or 0))
        return False

    condition.wait = fake_wait  # type: ignore[method-assign]
    scheduler = RefreshScheduler(
        device_config=config,
        condition=condition,
        manual_update_requests=deque(),
        get_current_datetime=lambda: now,
    )
    return scheduler, waits


def test_scheduler_sleeps_until_the_playlist_override_is_due() -> None:
    config = _Config(_manager(_all_day(cycle=300)), NOW - timedelta(seconds=60))
    scheduler, waits = _scheduler(config)
    scheduler.wait_for_trigger(is_running=lambda: True)
    assert waits == [pytest.approx(240)]


def test_scheduler_records_an_attempt_only_when_a_refresh_is_due() -> None:
    config = _Config(_manager(_all_day(cycle=300)), NOW - timedelta(seconds=60))
    scheduler, _ = _scheduler(config)
    scheduler.wait_for_trigger(is_running=lambda: True)
    assert scheduler.last_attempt is None

    config.refresh_info.refresh_time = (NOW - timedelta(minutes=10)).isoformat()
    scheduler.wait_for_trigger(is_running=lambda: True)
    assert scheduler.last_attempt == NOW


def test_scheduler_spaces_retries_after_a_due_attempt() -> None:
    config = _Config(_manager(_all_day(cycle=600)), NOW - timedelta(hours=5))
    scheduler, waits = _scheduler(config)
    scheduler.wait_for_trigger(is_running=lambda: True)  # due: attempt recorded
    scheduler.wait_for_trigger(is_running=lambda: True)  # refresh did not land
    assert waits == [schedule.MIN_WAIT_SECONDS, pytest.approx(600)]


@pytest.mark.parametrize("interval", [0, -1, "0", "junk", True])
def test_scheduler_never_waits_zero_for_a_bad_device_interval(
    interval: object,
) -> None:
    config = _Config(_manager(_all_day(plugins=False)), None)
    config.interval = interval
    scheduler, waits = _scheduler(config)
    scheduler.wait_for_trigger(is_running=lambda: True)
    assert waits == [HOUR]


def test_scheduler_falls_back_to_the_device_interval_on_odd_config() -> None:
    config = _Config(object(), None)
    scheduler, waits = _scheduler(config)
    scheduler.wait_for_trigger(is_running=lambda: True)
    assert waits == [HOUR]
    assert scheduler.last_attempt is None
