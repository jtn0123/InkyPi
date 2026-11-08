"""Pure time-window and rotation-ETA math shared by the playlist routes.

Overlap detection for playlist create/update and the per-instance
rotation ETA used by both the ``/playlist`` page and ``/playlist/eta``.
"""

from datetime import datetime, timedelta
from typing import Any, cast

from model import Playlist
from utils.http_utils import json_error

from ._common import _CODE_VALIDATION, _MSG_TIME_OVERLAP, logger


def _to_minutes(time_str: str) -> int:
    return int(Playlist._to_minutes(time_str))


def _segments(start_min: int, end_min: int) -> list[tuple[int, int]]:
    if start_min == end_min:
        return []
    if start_min < end_min:
        return [(start_min, end_min)]
    return [(start_min, 24 * 60), (0, end_min)]


def _windows_overlap(start_a: int, end_a: int, start_b: int, end_b: int) -> bool:
    for a0, a1 in _segments(start_a, end_a):
        for b0, b1 in _segments(start_b, end_b):
            if a0 < b1 and b0 < a1:
                return True
    return False


def _default_overlap_warning(
    start_min: int, end_min: int, playlists: Any
) -> str | None:
    """Return an informational warning if the time range overlaps with the Default playlist."""
    try:
        for pl in playlists:
            if getattr(pl, "name", "") == "Default":
                ps = _to_minutes(pl.start_time)
                pe = _to_minutes(pl.end_time)
                if _windows_overlap(start_min, end_min, ps, pe):
                    return (
                        "This playlist overlaps with Default. During its active hours, "
                        "this playlist will take priority."
                    )
                break
    except Exception:
        logger.debug("Could not compute Default overlap warning", exc_info=True)
    return None


def _check_playlist_overlap(
    new_start: int, new_end: int, playlists: Any, exclude_name: str | None = None
) -> Any | None:
    """Check for time window overlap with existing playlists.

    Returns an error response if an overlap is found, or None if clear.
    Skips the playlist named ``exclude_name`` (used when updating an existing
    playlist) and always skips the built-in "Default" playlist.
    """
    for pl in playlists:
        if pl.name == exclude_name or getattr(pl, "name", "") == "Default":
            continue
        ps = _to_minutes(pl.start_time)
        pe = _to_minutes(pl.end_time)
        if _windows_overlap(new_start, new_end, ps, pe):
            return json_error(
                _MSG_TIME_OVERLAP,
                status=400,
                code=_CODE_VALIDATION,
                details={"field": "start_time"},
            )
    return None


def _safe_next_index(pl: Any, num: int) -> int:
    """Return the index of the plugin that will be shown on the next cycle tick."""
    if num == 0:
        return 0
    try:
        if pl.current_plugin_index is None:
            return 0
        if not (0 <= pl.current_plugin_index < num):
            return 0
        return cast(int, pl.current_plugin_index + 1) % num
    except Exception:
        return 0


def _safe_until_next_min(
    is_active: bool, last_dt: datetime | None, cycle_min: int, now: datetime
) -> int:
    """Return minutes until the next cycle tick for a playlist.

    ``is_active`` should be True when ``last_dt`` belongs to this playlist.
    Falls back to ``cycle_min`` on any error.
    """
    if not is_active or last_dt is None:
        return cycle_min
    try:
        return max(
            0,
            int((last_dt + timedelta(minutes=cycle_min) - now).total_seconds() // 60),
        )
    except Exception:
        return cycle_min


def _compute_playlist_rotation_eta(
    pl: Any, next_index: int, until_next_min: int, cycle_min: int, now: datetime
) -> dict[str, dict[str, int | str]]:
    """Compute per-instance rotation ETA for a single playlist.

    Returns a dict mapping instance name to ``{"minutes": int, "at": "HH:MM"}``.
    """
    eta_for_pl: dict[str, dict[str, int | str]] = {}
    num = len(pl.plugins)
    if num == 0:
        return eta_for_pl
    for idx, inst in enumerate(pl.plugins):
        steps = (idx - next_index + num) % num
        total_min = until_next_min + steps * cycle_min
        eta_dt = now + timedelta(minutes=total_min)
        eta_for_pl[inst.name] = {
            "minutes": total_min,
            "at": eta_dt.strftime("%H:%M"),
        }
    return eta_for_pl
