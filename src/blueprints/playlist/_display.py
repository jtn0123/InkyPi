"""``/display_next_in_playlist`` and the minute-cached ``/playlist/eta``."""

import threading
from datetime import datetime
from typing import Any

from flask import current_app, request
from flask.typing import ResponseReturnValue

from refresh_task import PlaylistRefresh, manual_update_timings, schedule
from utils.api_responses import json_success
from utils.backend_errors import (
    ClientInputError,
    ResourceLookupError,
    mapped_render_errors,
    route_error_boundary,
)
from utils.request_models import parse_playlist_name_request
from utils.time_utils import now_device_tz

from ._common import _CODE_VALIDATION, _MSG_PLAYLIST_NOT_FOUND, logger, playlist_bp
from ._schedule import (
    _compute_playlist_rotation_eta,
    _playlist_next_due,
    _safe_next_index,
    _safe_until_next_min,
)

# Simple in-memory cache for ETA computations (per playlist, per-minute)
# Bounded to prevent unbounded growth; entries expire after 1 minute.
_ETA_CACHE_MAX_SIZE = 64
_eta_cache: dict[str, tuple[datetime, dict[str, dict[str, Any]]]] = {}
_eta_cache_lock = threading.Lock()


# Trigger next eligible instance in a specific playlist immediately
@playlist_bp.route("/display_next_in_playlist", methods=["POST"])
def display_next_in_playlist() -> ResponseReturnValue:
    device_config = current_app.config["DEVICE_CONFIG"]
    refresh_task = current_app.config["REFRESH_TASK"]
    playlist_manager = device_config.get_playlist_manager()

    with route_error_boundary(
        "display next in playlist",
        logger=logger,
        hint="Ensure the playlist exists and has an eligible instance to render.",
    ):
        parsed, parse_error = parse_playlist_name_request(
            request.get_json(silent=True),
            missing_message="playlist_name required",
        )
        if parse_error is not None:
            raise ClientInputError(
                parse_error.message,
                status=parse_error.status,
                code=parse_error.code,
                field=parse_error.field,
            )
        if parsed is None:
            raise ClientInputError("Invalid or missing JSON payload", status=400)

        playlist = playlist_manager.get_playlist(parsed.playlist_name)
        if not playlist:
            raise ResourceLookupError(
                _MSG_PLAYLIST_NOT_FOUND,
                status=400,
                code=_CODE_VALIDATION,
                details={"field": "playlist_name"},
            )

        # Determine current time and next eligible
        current_dt = now_device_tz(device_config)

        # The index advance mutates shared config state; hold the config lock
        # (as /display-next does) so it cannot interleave with the refresh
        # thread or another request's update_atomic snapshot/rollback.
        with device_config.locked():
            plugin_instance = playlist.get_next_eligible_plugin(current_dt)
        if not plugin_instance:
            raise ClientInputError(
                "No eligible instance in playlist",
                status=400,
                code=_CODE_VALIDATION,
                field="playlist_name",
            )

        with mapped_render_errors("display_next_in_playlist", logger=logger):
            update_metrics = refresh_task.manual_update(
                PlaylistRefresh(playlist, plugin_instance, force=True)
            )

        def _persist_active_playlist(_cfg: Any) -> None:
            playlist_manager.active_playlist = playlist.name

        device_config.update_atomic(_persist_active_playlist)

        # This refresh's own timings, not refresh_info's (which can still
        # describe the previous refresh when manual_update returns early).
        return json_success(
            "Displayed next instance",
            metrics=manual_update_timings(update_metrics),
            playlist=playlist.name,
        )


@playlist_bp.route("/playlist/eta/<string:playlist_name>", methods=["GET"])
def playlist_eta(playlist_name: str) -> ResponseReturnValue:
    """Return per-instance ETA for the named playlist.

    Cached per minute to keep route lightweight.
    """
    device_config = current_app.config["DEVICE_CONFIG"]
    playlist_manager = device_config.get_playlist_manager()

    pl = playlist_manager.get_playlist(playlist_name)
    if not pl:
        raise ResourceLookupError(
            _MSG_PLAYLIST_NOT_FOUND,
            status=404,
            code=_CODE_VALIDATION,
            details={"field": "playlist_name"},
        )

    # Cache key is playlist name; invalidate once per minute
    now = now_device_tz(device_config)
    floor_min = now.replace(second=0, microsecond=0)

    with _eta_cache_lock:
        cached = _eta_cache.get(playlist_name)
    if cached and cached[0] == floor_min:
        return json_success("ok", eta=cached[1])

    # Compute ETA for this playlist only
    with route_error_boundary(
        "compute playlist eta",
        logger=logger,
        hint="Check playlist timing data and refresh info availability.",
    ):
        # The loop's cycle for this playlist
        cycle_sec = schedule.effective_cycle_seconds(
            pl, schedule.device_interval_seconds(device_config)
        )
        cycle_min = schedule.cycle_minutes(cycle_sec)

        # Determine last refresh and which index is next
        try:
            ri_obj = device_config.get_refresh_info()
            last_dt = (
                ri_obj.get_refresh_datetime()
                if hasattr(ri_obj, "get_refresh_datetime")
                else None
            )
            last_playlist = getattr(ri_obj, "playlist", None)
        except Exception:
            last_dt = None
            last_playlist = None

        try:
            num = len(pl.plugins)
        except Exception:
            num = 0

        next_due = _playlist_next_due(
            pl,
            last_refresh=last_dt if isinstance(last_dt, datetime) else None,
            last_refresh_playlist=last_playlist,
            last_attempt=schedule.last_attempt_of(
                current_app.config.get("REFRESH_TASK")
            ),
            cycle_seconds=cycle_sec,
            now=now,
        )
        next_index = _safe_next_index(pl, num)
        until_next_min = _safe_until_next_min(next_due, cycle_min, now)
        eta_map = _compute_playlist_rotation_eta(
            pl, next_index, until_next_min, cycle_min, now
        )

        # Evict stale entries and cap cache size
        with _eta_cache_lock:
            if len(_eta_cache) >= _ETA_CACHE_MAX_SIZE:
                stale_keys = [k for k, (ts, _) in _eta_cache.items() if ts != floor_min]
                for k in stale_keys:
                    _eta_cache.pop(k, None)
                # If still over limit, drop oldest entries
                while len(_eta_cache) >= _ETA_CACHE_MAX_SIZE:
                    _eta_cache.pop(next(iter(_eta_cache)), None)
            _eta_cache[playlist_name] = (floor_min, eta_map)
        return json_success("ok", eta=eta_map)
