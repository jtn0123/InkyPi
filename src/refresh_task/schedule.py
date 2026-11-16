"""When the refresh loop should next look at the playlist.

Pure functions, so the scheduler and the routes that predict the next
refresh can share one answer. Playlists are duck-typed: anything with
``start_time``/``end_time`` ("HH:MM") and ``cycle_interval_seconds``.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any

from utils.time_utils import parse_hhmm

# Floor for a computed wait. A refresh that is already overdue still waits
# this long, so a state the loop cannot act on can never spin it.
MIN_WAIT_SECONDS = 5.0

# The device interval when plugin_cycle_interval_seconds is unset or unusable.
DEFAULT_DEVICE_INTERVAL_SECONDS = 60.0 * 60

_MINUTES_PER_DAY = 24 * 60


def device_interval_seconds(device_config: Any) -> float:
    """Return the device-wide refresh interval in seconds.

    Unset, unreadable, zero or negative values mean an hour: zero or less
    would make the loop spin.
    """
    try:
        raw = device_config.get_config(
            "plugin_cycle_interval_seconds", default=DEFAULT_DEVICE_INTERVAL_SECONDS
        )
    except Exception:
        return DEFAULT_DEVICE_INTERVAL_SECONDS
    value = DEFAULT_DEVICE_INTERVAL_SECONDS
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        value = float(raw)
    elif isinstance(raw, str):
        try:
            value = float(raw or DEFAULT_DEVICE_INTERVAL_SECONDS)
        except ValueError:
            pass
    return value if value > 0 else DEFAULT_DEVICE_INTERVAL_SECONDS


def cycle_minutes(cycle_seconds: float) -> int:
    """Return a cycle in whole minutes for display ("Every N min"), never 0."""
    return max(1, int(cycle_seconds // 60))


def last_attempt_of(refresh_task: object) -> datetime | None:
    """Return when the running loop last acted on a due refresh, if known.

    Routes predicting the next refresh pass this to :func:`next_due_at`, so
    after a failed or skipped refresh they show the same time the loop will
    act, not "Due now" for a whole cycle.
    """
    scheduler = getattr(refresh_task, "scheduler", None)
    value = getattr(scheduler, "last_attempt", None)
    return value if isinstance(value, datetime) else None


def effective_cycle_seconds(playlist: Any, device_interval: float) -> float:
    """Return the playlist's own cycle when it sets one, else the device's."""
    override = getattr(playlist, "cycle_interval_seconds", None)
    if (
        isinstance(override, (int, float))
        and not isinstance(override, bool)
        and override > 0
    ):
        return float(override)
    return device_interval


def next_due_at(
    latest_refresh: datetime | None,
    last_attempt: datetime | None,
    cycle_seconds: float,
    now: datetime,
) -> datetime:
    """Return when the next scheduled refresh is due.

    ``last_attempt`` is the last time the loop acted on a due refresh,
    whatever the outcome. Counting it spaces retries a cycle apart when a
    refresh fails, or is skipped for a blackout or a fully paused playlist,
    since none of those move ``latest_refresh``.
    """
    anchors = [_aware(d, now) for d in (latest_refresh, last_attempt) if d]
    if not anchors:
        return now
    return max(anchors) + timedelta(seconds=cycle_seconds)


def next_window_change(playlists: Iterable[Any], now: datetime) -> datetime | None:
    """Return the next playlist start or end time after *now*, if any."""
    now_minute = now.hour * 60 + now.minute
    start_of_minute = now.replace(second=0, microsecond=0)
    best: datetime | None = None
    for playlist in playlists:
        for value in (
            getattr(playlist, "start_time", None),
            getattr(playlist, "end_time", None),
        ):
            minute = _minutes(value)
            if minute is None:
                continue
            delta = (minute - now_minute) % _MINUTES_PER_DAY or _MINUTES_PER_DAY
            boundary = start_of_minute + timedelta(minutes=delta)
            if best is None or boundary < best:
                best = boundary
    return best


def seconds_until_next_check(
    *,
    playlist_manager: Any,
    latest_refresh: datetime | None,
    last_attempt: datetime | None,
    now: datetime,
    device_interval: float,
) -> float:
    """Return how long the loop may sleep before the playlist needs a look.

    That is until the active playlist's next refresh is due, or until a
    playlist window opens or closes (the active playlist, and so the cycle,
    may change there). Never longer than the device interval, never shorter
    than :data:`MIN_WAIT_SECONDS`.
    """
    playlist = playlist_manager.determine_active_playlist(now)
    wait = device_interval
    if playlist is not None and getattr(playlist, "plugins", None):
        cycle = effective_cycle_seconds(playlist, device_interval)
        due = next_due_at(latest_refresh, last_attempt, cycle, now)
        wait = (due - now).total_seconds()
    boundary = next_window_change(getattr(playlist_manager, "playlists", ()), now)
    if boundary is not None:
        wait = min(wait, (boundary - now).total_seconds())
    return max(MIN_WAIT_SECONDS, min(wait, device_interval))


def is_due(
    *,
    playlist_manager: Any,
    latest_refresh: datetime | None,
    last_attempt: datetime | None,
    now: datetime,
    device_interval: float,
) -> bool:
    """Return whether the active playlist's scheduled refresh is due now."""
    playlist = playlist_manager.determine_active_playlist(now)
    if playlist is None or not getattr(playlist, "plugins", None):
        return False
    cycle = effective_cycle_seconds(playlist, device_interval)
    return now >= next_due_at(latest_refresh, last_attempt, cycle, now)


def _aware(value: datetime, now: datetime) -> datetime:
    """Give a naive timestamp (legacy configs) the device timezone."""
    if value.tzinfo is None and now.tzinfo is not None:
        return value.replace(tzinfo=now.tzinfo)
    return value


def _minutes(value: object) -> int | None:
    """Minutes past midnight for a playlist time ("24:00" is midnight), or None."""
    try:
        return parse_hhmm(value) % _MINUTES_PER_DAY
    except ValueError:
        return None
