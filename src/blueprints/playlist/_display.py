"""``/display_next_in_playlist`` and the minute-cached ``/playlist/eta``."""

import threading
from datetime import UTC, datetime
from typing import Any, cast

from flask import current_app, request

from refresh_task import PlaylistRefresh
from utils.backend_errors import (
    ClientInputError,
    ResourceLookupError,
    route_error_boundary,
)
from utils.http_utils import json_success
from utils.request_models import parse_playlist_name_request
from utils.time_utils import now_device_tz

from ._common import _CODE_VALIDATION, _MSG_PLAYLIST_NOT_FOUND, logger, playlist_bp
from ._schedule import (
    _compute_playlist_rotation_eta,
    _safe_next_index,
    _safe_until_next_min,
)

# Simple in-memory cache for ETA computations (per playlist, per-minute)
# Bounded to prevent unbounded growth; entries expire after 1 minute.
_ETA_CACHE_MAX_SIZE = 64
_eta_cache: dict[str, tuple[datetime, dict[str, dict[str, Any]]]] = {}
_eta_cache_lock = threading.Lock()


def _safe_now_device_tz(device_config: Any) -> datetime:
    try:
        return cast(datetime, now_device_tz(device_config))  # type: ignore[redundant-cast, unused-ignore]
    except Exception:
        return datetime.now(UTC)


# Trigger next eligible instance in a specific playlist immediately
@playlist_bp.route("/display_next_in_playlist", methods=["POST"])
def display_next_in_playlist() -> Any:
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
        current_dt = _safe_now_device_tz(device_config)

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

        refresh_task.manual_update(
            PlaylistRefresh(playlist, plugin_instance, force=True)
        )

        def _persist_active_playlist(_cfg: Any) -> None:
            playlist_manager.active_playlist = playlist.name

        device_config.update_atomic(_persist_active_playlist)

        # Include latest metrics from refresh info if available
        metrics = {}
        try:
            ri = device_config.get_refresh_info()
            metrics = {
                "request_ms": getattr(ri, "request_ms", None),
                "generate_ms": getattr(ri, "generate_ms", None),
                "preprocess_ms": getattr(ri, "preprocess_ms", None),
                "display_ms": getattr(ri, "display_ms", None),
            }
        except Exception:
            pass

        return json_success(
            "Displayed next instance", metrics=metrics, playlist=playlist.name
        )


@playlist_bp.route("/playlist/eta/<string:playlist_name>", methods=["GET"])
def playlist_eta(playlist_name: str) -> Any:
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
    now = _safe_now_device_tz(device_config)
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
        # Determine cycle in minutes
        try:
            device_cycle_minutes = int(
                device_config.get_config("plugin_cycle_interval_seconds", default=3600)
                // 60
            )
        except Exception:
            device_cycle_minutes = 60
        cycle_sec = getattr(pl, "cycle_interval_seconds", None)
        cycle_min = int((cycle_sec or device_cycle_minutes * 60) // 60)

        # Determine last refresh and which index is next
        try:
            ri_obj = device_config.get_refresh_info()
            last_dt = (
                ri_obj.get_refresh_datetime()
                if hasattr(ri_obj, "get_refresh_datetime")
                else None
            )
        except Exception:
            last_dt = None

        try:
            num = len(pl.plugins)
        except Exception:
            num = 0

        is_active = (
            last_dt is not None and getattr(ri_obj, "playlist", None) == playlist_name
        )
        next_index = _safe_next_index(pl, num)
        until_next_min = _safe_until_next_min(
            is_active, cast(datetime | None, last_dt), cycle_min, now
        )
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
