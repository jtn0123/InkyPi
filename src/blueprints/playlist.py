import json
import logging
import re
import threading
from datetime import UTC, datetime, timedelta

from flask import (
    Blueprint,
    current_app,
    has_app_context,
    redirect,
    render_template,
    request,
    url_for,
)

from model import Playlist
from refresh_task import PlaylistRefresh
from utils.app_utils import handle_request_files, parse_form
from utils.http_utils import (
    json_error,
    json_internal_error,
    json_success,
    reissue_json_error,
)
from utils.messages import PLAYLIST_NAME_REQUIRED_ERROR
from utils.time_utils import calculate_seconds, now_device_tz

logger = logging.getLogger(__name__)
playlist_bp = Blueprint("playlist", __name__)

_PLAYLIST_NAME_MAX_LEN = 64
_PLAYLIST_NAME_RE = re.compile(r"^[\w\s\-]+$", re.UNICODE)
_INSTANCE_NAME_RE = re.compile(r"^[A-Za-z0-9 _-]+$")

# Shared string constants to avoid duplication
_CODE_VALIDATION = "validation_error"
_MSG_INVALID_TIME_FORMAT = "Invalid start/end time format"
_MSG_SAME_TIME = "Start time and End time cannot be the same"
_MSG_TIME_OVERLAP = "Playlist time range overlaps with existing playlist"
_MSG_INVALID_PLAYLIST_REQUEST = "Invalid playlist request"
_MSG_PLAYLIST_NOT_FOUND = "Playlist not found"


def _validate_playlist_name(name, field="playlist_name"):
    """Validate playlist name format. Returns (cleaned_name, error_response) tuple.

    ``field`` is the form field name echoed back in ``details.field`` so the
    frontend can highlight the offending input.
    """
    if not name or not name.strip():
        return None, json_error(
            PLAYLIST_NAME_REQUIRED_ERROR,
            status=400,
            code=_CODE_VALIDATION,
            details={"field": field},
        )
    name = name.strip()
    if len(name) > _PLAYLIST_NAME_MAX_LEN:
        return None, json_error(
            f"Playlist name must be {_PLAYLIST_NAME_MAX_LEN} characters or fewer",
            status=400,
            code=_CODE_VALIDATION,
            details={"field": field},
        )
    if not _PLAYLIST_NAME_RE.match(name):
        return None, json_error(
            "Playlist name may only contain letters, numbers, spaces, hyphens, and underscores",
            status=400,
            code=_CODE_VALIDATION,
            details={"field": field},
        )
    return name, None


# Simple in-memory cache for ETA computations (per playlist, per-minute)
# Bounded to prevent unbounded growth; entries expire after 1 minute.
_ETA_CACHE_MAX_SIZE = 64
_eta_cache: dict[str, tuple[datetime, dict[str, dict]]] = {}
_eta_cache_lock = threading.Lock()


def _safe_now_device_tz(device_config) -> datetime:
    try:
        return now_device_tz(device_config)
    except Exception:
        return datetime.now(UTC)


def _to_minutes(time_str: str) -> int:
    return Playlist._to_minutes(time_str)


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


def _default_overlap_warning(start_min, end_min, playlists):
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


def _check_playlist_overlap(new_start, new_end, playlists, exclude_name=None):
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


def validate_plugin_refresh_settings(refresh_settings):
    """Validate the refresh portion of an add_plugin request.

    Returns ``(refresh_config, error_response)``.  Exactly one of the two
    values will be non-None.
    """
    refresh_type = refresh_settings.get("refreshType")
    if not refresh_type or refresh_type not in ["interval", "scheduled"]:
        return None, json_error(
            "Refresh type is required",
            status=422,
            code=_CODE_VALIDATION,
            details={"field": "refreshType"},
        )

    if refresh_type == "interval":
        unit = refresh_settings.get("unit")
        interval = refresh_settings.get("interval")
        if not unit or unit not in ["minute", "hour", "day"]:
            return None, json_error(
                "Refresh interval unit is required",
                status=422,
                code=_CODE_VALIDATION,
                details={"field": "unit"},
            )
        if not interval:
            return None, json_error(
                "Refresh interval is required",
                status=422,
                code=_CODE_VALIDATION,
                details={"field": "interval"},
            )
        try:
            interval_int = int(interval)
        except (ValueError, TypeError):
            return None, json_error(
                "Refresh interval must be a number",
                status=422,
                code=_CODE_VALIDATION,
                details={"field": "interval"},
            )
        if interval_int < 1 or interval_int > 999:
            return None, json_error(
                "Refresh interval must be between 1 and 999",
                status=422,
                code=_CODE_VALIDATION,
                details={"field": "interval"},
            )
        refresh_config = {"interval": calculate_seconds(interval_int, unit)}
    else:
        refresh_time = refresh_settings.get("refreshTime")
        if not refresh_time:
            return None, json_error(
                "Refresh time is required",
                status=422,
                code=_CODE_VALIDATION,
                details={"field": "refreshTime"},
            )
        if not isinstance(refresh_time, str):
            return None, json_error(
                "Refresh time must be in HH:MM format",
                status=422,
                code=_CODE_VALIDATION,
                details={"field": "refreshTime"},
            )
        refresh_time = refresh_time.strip()
        try:
            # Format-only validation; the parsed datetime is discarded. No tz needed.
            datetime.strptime(refresh_time, "%H:%M")  # noqa: DTZ007
        except ValueError:
            return None, json_error(
                "Refresh time must be in HH:MM format",
                status=422,
                code=_CODE_VALIDATION,
                details={"field": "refreshTime"},
            )
        refresh_config = {"scheduled": refresh_time}

    return refresh_config, None


def _safe_next_index(pl, num: int) -> int:
    """Return the index of the plugin that will be shown on the next cycle tick."""
    if num == 0:
        return 0
    try:
        if pl.current_plugin_index is None:
            return 0
        if not (0 <= pl.current_plugin_index < num):
            return 0
        return (pl.current_plugin_index + 1) % num
    except Exception:
        return 0


def _safe_until_next_min(is_active, last_dt, cycle_min: int, now) -> int:
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


def _compute_playlist_rotation_eta(pl, next_index, until_next_min, cycle_min, now):
    """Compute per-instance rotation ETA for a single playlist.

    Returns a dict mapping instance name to ``{"minutes": int, "at": "HH:MM"}``.
    """
    eta_for_pl: dict[str, dict] = {}
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


def _validate_instance_name(raw_name):
    """Validate and normalise an instance name.

    Returns ``(name, error_response)``.  Exactly one will be non-None.
    """
    name = raw_name.strip() if raw_name else ""
    if not name:
        return None, json_error(
            "Instance name is required",
            status=422,
            code=_CODE_VALIDATION,
            details={"field": "instance_name"},
        )
    if len(name) > 64:
        return None, json_error(
            "Instance name must be 64 characters or fewer",
            status=422,
            code=_CODE_VALIDATION,
            details={"field": "instance_name"},
        )
    if not _INSTANCE_NAME_RE.match(name):
        return None, json_error(
            "Instance name can only contain letters, numbers, spaces, underscores, and hyphens",
            status=422,
            code=_CODE_VALIDATION,
            details={"field": "instance_name"},
        )
    return name, None


def _parse_add_plugin_form(form, files):
    """Parse and validate the add_plugin form data.

    Returns ``(plugin_id, plugin_settings, refresh_settings, error_response)``.
    On success ``error_response`` is None; on failure the first three are None.
    """
    plugin_settings = parse_form(form)
    raw_refresh = plugin_settings.pop("refresh_settings", None)
    if not raw_refresh or not isinstance(raw_refresh, str):
        return (
            None,
            None,
            None,
            json_error(
                "refresh_settings is required",
                status=400,
                code=_CODE_VALIDATION,
                details={"field": "refresh_settings"},
            ),
        )
    try:
        refresh_settings = json.loads(raw_refresh)
    except (json.JSONDecodeError, ValueError):
        return (
            None,
            None,
            None,
            json_error(
                "Invalid JSON in refresh_settings",
                status=400,
                code=_CODE_VALIDATION,
                details={"field": "refresh_settings"},
            ),
        )
    if not isinstance(refresh_settings, dict):
        return (
            None,
            None,
            None,
            json_error(
                "refresh_settings must be a JSON object",
                status=400,
                code=_CODE_VALIDATION,
                details={"field": "refresh_settings"},
            ),
        )
    plugin_id = plugin_settings.pop("plugin_id", None)
    if not plugin_id or not isinstance(plugin_id, str):
        return (
            None,
            None,
            None,
            json_error(
                "plugin_id is required",
                status=422,
                code=_CODE_VALIDATION,
                details={"field": "plugin_id"},
            ),
        )
    plugin_settings.update(handle_request_files(files))
    return plugin_id, plugin_settings, refresh_settings, None


def _validate_plugin_settings_security(device_config, plugin_id, plugin_settings):
    """JTN-451: Run plugin-specific validation (e.g. URL scheme checks).

    Returns an error response if validation fails, or None on success.
    Only validates when the settings dict has actual user values.
    """
    if not plugin_settings:
        return None
    plugin_config = device_config.get_plugin(plugin_id)
    if not plugin_config:
        return None
    try:
        from plugins.plugin_registry import get_plugin_instance as _get_pi

        plugin_obj = _get_pi(plugin_config)
        settings_error = plugin_obj.validate_settings(plugin_settings)
        if settings_error:
            return json_error(settings_error, status=400)
    except Exception:
        logger.debug("Could not validate plugin schema for %s", plugin_id)
    return None


@playlist_bp.route("/add_plugin", methods=["POST"])
def add_plugin():
    device_config = current_app.config["DEVICE_CONFIG"]
    playlist_manager = device_config.get_playlist_manager()

    try:
        plugin_id, plugin_settings, refresh_settings, parse_err = (
            _parse_add_plugin_form(request.form, request.files)
        )
        if parse_err:
            return parse_err

        playlist = refresh_settings.get("playlist")
        if not playlist:
            return json_error(
                PLAYLIST_NAME_REQUIRED_ERROR,
                status=422,
                code=_CODE_VALIDATION,
                details={"field": "playlist"},
            )
        instance_name, name_err = _validate_instance_name(
            refresh_settings.get("instance_name")
        )
        if name_err:
            return name_err

        existing = playlist_manager.find_plugin(plugin_id, instance_name)
        if existing:
            return json_error(
                f"Plugin instance '{instance_name}' already exists",
                status=400,
                code=_CODE_VALIDATION,
                details={"field": "instance_name"},
            )

        refresh_config, refresh_err = validate_plugin_refresh_settings(refresh_settings)
        if refresh_err:
            return refresh_err

        security_err = _validate_plugin_settings_security(
            device_config, plugin_id, plugin_settings
        )
        if security_err:
            return security_err

        plugin_dict = {
            "plugin_id": plugin_id,
            "refresh": refresh_config,
            "plugin_settings": plugin_settings,
            "name": instance_name,
        }
        add_result: list[bool] = []

        def _do_add(cfg):
            add_result.append(
                playlist_manager.add_plugin_to_playlist(playlist, plugin_dict)
            )

        device_config.update_atomic(_do_add)
        if not add_result or not add_result[0]:
            return json_error("Failed to add to playlist", status=500)
    except Exception:
        return json_internal_error(
            "add plugin to playlist",
            details={
                "hint": "Validate inputs; ensure playlist exists and instance name isn’t duplicated.",
            },
        )
    return json_success("Scheduled refresh configured.")


@playlist_bp.route("/playlists", methods=["GET"])
def playlists_redirect():
    return redirect(url_for("playlist.playlists"))


@playlist_bp.route("/playlist", methods=["GET"])
def playlists():
    device_config = current_app.config["DEVICE_CONFIG"]
    playlist_manager = device_config.get_playlist_manager()
    refresh_info = device_config.get_refresh_info()
    plugins_list = device_config.get_plugins()

    # Include latest metrics for badge rendering
    metrics = None
    try:
        ri_obj = device_config.get_refresh_info()
        metrics = {
            "request_ms": getattr(ri_obj, "request_ms", None),
            "generate_ms": getattr(ri_obj, "generate_ms", None),
            "preprocess_ms": getattr(ri_obj, "preprocess_ms", None),
            "display_ms": getattr(ri_obj, "display_ms", None),
            "plugin_id": getattr(ri_obj, "plugin_id", None),
            "playlist": getattr(ri_obj, "playlist", None),
            "plugin_instance": getattr(ri_obj, "plugin_instance", None),
        }
    except Exception:
        metrics = None
    # compute device current time string and cycle info per playlist
    try:
        now = now_device_tz(device_config)
        now_str = now.strftime("%Y-%m-%d %H:%M:%S %Z")
        tz_off_min = int((now.utcoffset() or timedelta(0)).total_seconds() // 60)
    except Exception:
        now_str = ""
        tz_off_min = 0
    try:
        device_cycle_minutes = int(
            int(device_config.get_config("plugin_cycle_interval_seconds", default=3600))
            // 60
        )
    except Exception:
        device_cycle_minutes = 60

    # Build per-playlist timing metadata: cycle and next refresh (if active)
    try:
        ri_obj = device_config.get_refresh_info()
        last_dt = (
            ri_obj.get_refresh_datetime()
            if hasattr(ri_obj, "get_refresh_datetime")
            else None
        )
    except Exception:
        last_dt = None
    playlist_timing: dict[str, dict] = {}
    rotation_eta: dict[str, dict] = {}
    try:
        for pl in playlist_manager.playlists:
            cycle_sec = getattr(pl, "cycle_interval_seconds", None)
            cycle_min = int(
                (int(cycle_sec) if cycle_sec else device_cycle_minutes * 60) // 60
            )
            item: dict = {
                "cycle_minutes": cycle_min,
                "next_in_minutes": None,
                "next_at": None,
            }
            try:
                is_active = last_dt and getattr(ri_obj, "playlist", None) == pl.name
                if is_active:
                    # compute next time
                    next_dt = last_dt + timedelta(minutes=cycle_min)
                    delta_min = int(max(0, (next_dt - now).total_seconds() // 60))
                    item["next_in_minutes"] = delta_min
                    try:
                        item["next_at"] = next_dt.strftime("%Y-%m-%d %H:%M")
                    except Exception:
                        item["next_at"] = None
                # Also compute rotation ETA for each plugin in this playlist
                try:
                    num = len(pl.plugins)
                    next_index = _safe_next_index(pl, num)
                    until_next_min = _safe_until_next_min(
                        is_active, last_dt, cycle_min, now
                    )
                    rotation_eta[pl.name] = _compute_playlist_rotation_eta(
                        pl, next_index, until_next_min, cycle_min, now
                    )
                except Exception:
                    rotation_eta[pl.name] = {}
            except Exception:
                pass
            playlist_timing[pl.name] = item
    except Exception:
        playlist_timing = {}

    return render_template(
        "playlist.html",
        playlist_config=playlist_manager.to_dict(),
        refresh_info=refresh_info.to_dict(),
        plugins={p["id"]: p for p in plugins_list},
        metrics=metrics,
        now_str=now_str,
        tz_off_min=tz_off_min,
        device_cycle_minutes=device_cycle_minutes,
        playlist_timing=playlist_timing,
        rotation_eta=rotation_eta,
    )


def _parse_playlist_request_data():
    """Parse and validate playlist create/update request data.

    Returns (data_dict, error_response). If error_response is not None, return it.
    """
    data = request.get_json(silent=True)
    if data is None:
        form_data = request.form.to_dict()
        if any(k in form_data for k in ("playlist_name", "start_time", "end_time")):
            data = form_data
        else:
            return None, json_error("Unsupported media type", status=415)
    if not isinstance(data, dict):
        return None, json_error("Invalid JSON data", status=400)
    return data, None


def _validate_playlist_times(start_time, end_time):
    """Validate and convert time strings to minutes.

    Returns (start_min, end_min, error_response).
    """
    if not start_time:
        missing_field = "start_time"
    elif not end_time:
        missing_field = "end_time"
    else:
        missing_field = None
    if missing_field is not None:
        return (
            None,
            None,
            json_error(
                "Start time and End time are required",
                status=400,
                code=_CODE_VALIDATION,
                details={"field": missing_field},
            ),
        )
    try:
        start_min = _to_minutes(start_time)
    except Exception:
        return (
            None,
            None,
            json_error(
                _MSG_INVALID_TIME_FORMAT,
                status=400,
                code=_CODE_VALIDATION,
                details={"field": "start_time"},
            ),
        )
    try:
        end_min = _to_minutes(end_time)
    except Exception:
        return (
            None,
            None,
            json_error(
                _MSG_INVALID_TIME_FORMAT,
                status=400,
                code=_CODE_VALIDATION,
                details={"field": "end_time"},
            ),
        )
    if start_min == end_min:
        return (
            None,
            None,
            json_error(
                _MSG_SAME_TIME,
                status=400,
                code=_CODE_VALIDATION,
                details={"field": "end_time"},
            ),
        )
    return start_min, end_min, None


@playlist_bp.route("/create_playlist", methods=["POST"])
def create_playlist():
    device_config = current_app.config["DEVICE_CONFIG"]
    playlist_manager = device_config.get_playlist_manager()

    data, err = _parse_playlist_request_data()
    if err:
        return reissue_json_error(err, _MSG_INVALID_PLAYLIST_REQUEST)

    playlist_name, name_err = _validate_playlist_name(data.get("playlist_name"))
    if name_err:
        return name_err
    start_min, end_min, time_err = _validate_playlist_times(
        data.get("start_time"), data.get("end_time")
    )
    if time_err:
        return time_err

    try:
        playlist = playlist_manager.get_playlist(playlist_name)
        if playlist:
            return json_error(
                "A playlist with that name already exists",
                status=400,
                code=_CODE_VALIDATION,
                details={"field": "playlist_name"},
            )

        # Prevent overlapping time windows
        try:
            overlap_err = _check_playlist_overlap(
                start_min, end_min, playlist_manager.playlists
            )
            if overlap_err:
                return overlap_err
        except Exception:
            # best-effort, fallback to allow
            pass

        add_pl_result: list[bool] = []

        def _do_add_playlist(cfg):
            add_pl_result.append(
                playlist_manager.add_playlist(
                    playlist_name, data.get("start_time"), data.get("end_time")
                )
            )

        device_config.update_atomic(_do_add_playlist)
        if not add_pl_result or not add_pl_result[0]:
            return json_error("Failed to create playlist", status=500)

        warning = None
        if playlist_name != "Default":
            warning = _default_overlap_warning(
                start_min, end_min, playlist_manager.playlists
            )

    except Exception as e:
        logger.exception("EXCEPTION CAUGHT: " + str(e))
        return json_internal_error(
            "create playlist",
            details={
                "hint": "Ensure unique name and valid time range; check config write permissions.",
            },
        )

    if warning:
        return json_success("Created new Playlist!", warning=warning)
    return json_success("Created new Playlist!")


_CYCLE_MINUTES_MIN = 1
_CYCLE_MINUTES_MAX = 1440


def _validate_cycle_minutes(cycle_minutes):
    """Validate cycle_minutes value.

    Returns ``(int_value, error_response)``.  If cycle_minutes is None/absent,
    returns ``(None, None)`` to indicate "use device default".
    """
    if cycle_minutes is None:
        return None, None
    try:
        cm = int(cycle_minutes)
    except (ValueError, TypeError):
        return None, json_error(
            "cycle_minutes must be an integer",
            status=400,
            code=_CODE_VALIDATION,
            details={"field": "cycle_minutes"},
        )
    if cm < _CYCLE_MINUTES_MIN or cm > _CYCLE_MINUTES_MAX:
        return None, json_error(
            f"cycle_minutes must be between {_CYCLE_MINUTES_MIN} and {_CYCLE_MINUTES_MAX}",
            status=400,
            code=_CODE_VALIDATION,
            details={"field": "cycle_minutes"},
        )
    return cm, None


def _apply_cycle_override(playlist_manager, new_name, cycle_minutes_int):
    """Apply optional cycle interval override to a playlist.

    ``cycle_minutes_int`` must already be a validated integer or None.
    """
    if cycle_minutes_int is None:
        return
    playlist = playlist_manager.get_playlist(new_name)
    if playlist:
        playlist.cycle_interval_seconds = cycle_minutes_int * 60


def _validate_update_playlist_payload(data):
    """Validate an /update_playlist request payload.

    Returns ``(parsed, error_response)``; exactly one is non-None.  ``parsed``
    is a dict with ``new_name``, ``start_time``, ``end_time``, ``start_min``,
    ``end_min``, ``cycle_minutes_int``.
    """
    new_name, name_err = _validate_playlist_name(data.get("new_name"), field="new_name")
    if name_err:
        return None, name_err
    start_time = data.get("start_time")
    end_time = data.get("end_time")
    if not start_time or not end_time:
        missing_field = "start_time" if not start_time else "end_time"
        return None, json_error(
            "Missing required fields",
            status=400,
            code=_CODE_VALIDATION,
            details={"field": missing_field},
        )
    start_min, end_min, time_err = _validate_playlist_times(start_time, end_time)
    if time_err:
        return None, time_err
    cycle_minutes_int, cycle_err = _validate_cycle_minutes(data.get("cycle_minutes"))
    if cycle_err:
        return None, cycle_err
    return {
        "new_name": new_name,
        "start_time": start_time,
        "end_time": end_time,
        "start_min": start_min,
        "end_min": end_min,
        "cycle_minutes_int": cycle_minutes_int,
    }, None


@playlist_bp.route("/update_playlist/<string:playlist_name>", methods=["PUT"])
def update_playlist(playlist_name):
    device_config = current_app.config["DEVICE_CONFIG"]
    playlist_manager = device_config.get_playlist_manager()

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return json_error("Invalid JSON data", status=400)

    parsed, err = _validate_update_playlist_payload(data)
    if err:
        return err
    new_name = parsed["new_name"]
    start_time = parsed["start_time"]
    end_time = parsed["end_time"]
    start_min = parsed["start_min"]
    end_min = parsed["end_min"]
    cycle_minutes_int = parsed["cycle_minutes_int"]

    playlist = playlist_manager.get_playlist(playlist_name)
    if not playlist:
        return json_error(
            "Playlist does not exist",
            status=400,
            code=_CODE_VALIDATION,
            details={"field": "playlist_name"},
        )

    # Prevent overlapping (exclude the playlist being updated)
    try:
        overlap_err = _check_playlist_overlap(
            start_min, end_min, playlist_manager.playlists, exclude_name=playlist_name
        )
        if overlap_err:
            return overlap_err
    except Exception:
        pass

    upd_result: list[bool] = []

    def _do_update_playlist(cfg):
        upd_result.append(
            playlist_manager.update_playlist(
                playlist_name, new_name, start_time, end_time
            )
        )
        _apply_cycle_override(playlist_manager, new_name, cycle_minutes_int)

    device_config.update_atomic(_do_update_playlist)
    if not upd_result or not upd_result[0]:
        return json_error("Failed to update playlist", status=500)

    # Warn if the updated playlist overlaps with Default.
    warning = None
    if playlist_name != "Default" and new_name != "Default":
        warning = _default_overlap_warning(
            start_min, end_min, playlist_manager.playlists
        )

    if warning:
        return json_success("Updated playlist!", warning=warning)
    return json_success("Updated playlist!")


@playlist_bp.route("/delete_playlist/<string:playlist_name>", methods=["DELETE"])
def delete_playlist(playlist_name):
    device_config = current_app.config["DEVICE_CONFIG"]
    playlist_manager = device_config.get_playlist_manager()

    if not playlist_name:
        return json_error(
            PLAYLIST_NAME_REQUIRED_ERROR,
            status=400,
            code=_CODE_VALIDATION,
            details={"field": "playlist_name"},
        )

    playlist = playlist_manager.get_playlist(playlist_name)
    if not playlist:
        return json_error(
            "Playlist does not exist",
            status=400,
            code=_CODE_VALIDATION,
            details={"field": "playlist_name"},
        )

    device_config.update_atomic(
        lambda cfg: playlist_manager.delete_playlist(playlist_name)
    )

    return json_success("Deleted playlist!")


@playlist_bp.route("/update_device_cycle", methods=["PUT"])
def update_device_cycle():
    device_config = current_app.config["DEVICE_CONFIG"]
    refresh_task = current_app.config["REFRESH_TASK"]
    data = request.get_json(silent=True) or {}
    minutes = data.get("minutes") or 0
    try:
        m = int(minutes)
        if m < 1 or m > 1440:
            return json_error(
                "Minutes must be between 1 and 1440",
                status=400,
                code=_CODE_VALIDATION,
                details={"field": "minutes"},
            )
    except Exception:
        return json_error(
            "Invalid minutes",
            status=400,
            code=_CODE_VALIDATION,
            details={"field": "minutes"},
        )
    try:
        device_config.update_value("plugin_cycle_interval_seconds", m * 60, write=True)
        try:
            refresh_task.signal_config_change()
        except Exception:
            pass
        return json_success("Device refresh cadence updated.")
    except Exception:
        return json_internal_error(
            "update_device_cycle", details={"hint": "Check config write permissions."}
        )


@playlist_bp.route("/reorder_plugins", methods=["POST"])
def reorder_plugins():
    device_config = current_app.config["DEVICE_CONFIG"]
    playlist_manager = device_config.get_playlist_manager()

    try:
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return json_error("Invalid or missing JSON payload", status=400)
        playlist_name = data.get("playlist_name")
        ordered = data.get("ordered")  # list of {plugin_id, name}
        if not playlist_name:
            return json_error(
                "playlist_name and ordered list are required",
                status=400,
                code=_CODE_VALIDATION,
                details={"field": "playlist_name"},
            )
        if not isinstance(ordered, list):
            return json_error(
                "playlist_name and ordered list are required",
                status=400,
                code=_CODE_VALIDATION,
                details={"field": "ordered"},
            )

        playlist = playlist_manager.get_playlist(playlist_name)
        if not playlist:
            return json_error(
                _MSG_PLAYLIST_NOT_FOUND,
                status=400,
                code=_CODE_VALIDATION,
                details={"field": "playlist_name"},
            )

        reorder_result: list[bool] = []

        def _do_reorder(cfg):
            reorder_result.append(playlist.reorder_plugins(ordered))

        device_config.update_atomic(_do_reorder)
        if not reorder_result or not reorder_result[0]:
            return json_error("Invalid order payload", status=400)

        return json_success("Reordered plugins")
    except Exception:
        return json_internal_error(
            "reorder plugins",
            details={"hint": "Validate payload shape and ensure playlist exists."},
        )


# Trigger next eligible instance in a specific playlist immediately
@playlist_bp.route("/display_next_in_playlist", methods=["POST"])
def display_next_in_playlist():
    device_config = current_app.config["DEVICE_CONFIG"]
    refresh_task = current_app.config["REFRESH_TASK"]
    playlist_manager = device_config.get_playlist_manager()

    try:
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return json_error("Invalid or missing JSON payload", status=400)
        playlist_name = data.get("playlist_name")
        if not playlist_name:
            return json_error(
                "playlist_name required",
                status=400,
                code=_CODE_VALIDATION,
                details={"field": "playlist_name"},
            )

        playlist = playlist_manager.get_playlist(playlist_name)
        if not playlist:
            return json_error(
                _MSG_PLAYLIST_NOT_FOUND,
                status=400,
                code=_CODE_VALIDATION,
                details={"field": "playlist_name"},
            )

        # Determine current time and next eligible
        current_dt = _safe_now_device_tz(device_config)

        plugin_instance = playlist.get_next_eligible_plugin(current_dt)
        if not plugin_instance:
            return json_error(
                "No eligible instance in playlist",
                status=400,
                code=_CODE_VALIDATION,
                details={"field": "playlist_name"},
            )

        refresh_task.manual_update(
            PlaylistRefresh(playlist, plugin_instance, force=True)
        )

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

        return json_success("Displayed next instance", metrics=metrics)
    except Exception:
        return json_internal_error("display next in playlist")


@playlist_bp.route("/playlist/eta/<string:playlist_name>", methods=["GET"])
def playlist_eta(playlist_name: str):
    """Return per-instance ETA for the named playlist.

    Cached per minute to keep route lightweight.
    """
    device_config = current_app.config["DEVICE_CONFIG"]
    playlist_manager = device_config.get_playlist_manager()

    pl = playlist_manager.get_playlist(playlist_name)
    if not pl:
        return json_error(
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
    try:
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

        is_active = last_dt and getattr(ri_obj, "playlist", None) == playlist_name
        next_index = _safe_next_index(pl, num)
        until_next_min = _safe_until_next_min(is_active, last_dt, cycle_min, now)
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
    except Exception:
        return json_internal_error("compute playlist eta")


@playlist_bp.app_template_filter("format_relative_time")
def format_relative_time(iso_date_string):
    # Parse the input ISO date string
    dt = datetime.fromisoformat(iso_date_string)

    # Get the timezone from the parsed datetime
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)

    # Get the current time using the device's configured timezone, if available
    if has_app_context():
        try:
            now = now_device_tz(current_app.config["DEVICE_CONFIG"])  # timezone-aware
        except Exception:
            now = datetime.now(dt.tzinfo)
    else:
        now = datetime.now(dt.tzinfo)

    # Align the input datetime to the device timezone for consistent comparisons
    dt_local = dt.astimezone(now.tzinfo)
    delta = now - dt_local

    # Compute time difference
    diff_seconds = delta.total_seconds()
    diff_minutes = diff_seconds / 60

    # Define formatting
    time_format = "%I:%M %p"  # Example: 04:30 PM
    month_day_format = "%b %d at " + time_format  # Example: Feb 12 at 04:30 PM

    # Determine relative time string
    if diff_seconds < 120:
        return "just now"
    if diff_minutes < 60:
        return f"{int(diff_minutes)} minutes ago"
    # Use rolling windows to avoid midnight boundary flakiness across TZs
    if diff_seconds < 60 * 60 * 24:
        return "today at " + dt_local.strftime(time_format).lstrip("0")
    if diff_seconds < 60 * 60 * 48:
        return "yesterday at " + dt_local.strftime(time_format).lstrip("0")
    return dt_local.strftime(month_day_format).replace(
        " 0", " "
    )  # Removes leading zero in day
