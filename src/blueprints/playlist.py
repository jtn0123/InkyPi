import json
import logging
import re
import threading
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, cast

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
from services.playlist_workflows import prepare_add_plugin_workflow
from utils.app_utils import handle_request_files, parse_form
from utils.backend_errors import (
    ClientInputError,
    OperationFailedError,
    ResourceLookupError,
    route_error_boundary,
)
from utils.http_utils import (
    json_error,
    json_success,
)
from utils.messages import PLAYLIST_NAME_REQUIRED_ERROR
from utils.request_models import (
    CODE_VALIDATION,
    PlaylistUpdateRequest,
    RequestModelError,
    parse_device_cycle_request,
    parse_playlist_create_request,
    parse_playlist_name_request,
    parse_playlist_reorder_request,
    parse_playlist_update_request,
)
from utils.time_utils import calculate_seconds, now_device_tz

logger = logging.getLogger(__name__)
playlist_bp = Blueprint("playlist", __name__)

_INSTANCE_NAME_RE = re.compile(r"^[A-Za-z0-9 _-]+$")

# Shared string constants to avoid duplication
_CODE_VALIDATION = CODE_VALIDATION
_MSG_TIME_OVERLAP = "Playlist time range overlaps with existing playlist"
_MSG_INVALID_PLAYLIST_REQUEST = "Invalid playlist request"
_MSG_PLAYLIST_NOT_FOUND = "Playlist not found"

# JTN-781: the "Default" playlist is the canonical fallback shipped with the
# system and auto-created on startup when no playlists exist (see
# PlaylistManager.add_default_playlist + config bootstrap). Deleting it leaves
# the scheduler with nothing to schedule and no UI path to recreate it, so the
# server rejects the delete outright. The match is case-sensitive because every
# other code path (create, update, overlap-warning, plugin auto-add) keys off
# the exact string "Default" — a lowercase "default" is just a user-created
# playlist and is fine to delete.
DEFAULT_PLAYLIST_NAME = "Default"
_MSG_CANNOT_DELETE_DEFAULT = "Cannot delete the default playlist"


def _request_model_error_response(error: RequestModelError) -> Any:
    return json_error(
        error.message,
        status=error.status,
        code=error.code,
        details=error.details or None,
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


def validate_plugin_refresh_settings(
    refresh_settings: Mapping[str, Any],
) -> tuple[dict[str, int | str] | None, Any]:
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

    refresh_config: dict[str, int | str]
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


def _validate_instance_name(raw_name: Any) -> tuple[str | None, Any]:
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


def _form_parse_error(
    message: str, *, status: int = 400, field: str = "refresh_settings"
) -> tuple[None, None, None, Any]:
    """Build a ``(None, None, None, error_response)`` tuple for form parsing."""
    return (
        None,
        None,
        None,
        json_error(
            message, status=status, code=_CODE_VALIDATION, details={"field": field}
        ),
    )


def _parse_refresh_settings_json(
    raw_refresh: Any,
) -> tuple[dict[str, Any] | None, tuple[None, None, None, Any] | None]:
    """Decode *raw_refresh* into a dict.

    Returns ``(refresh_settings, error_tuple)``.  On success the error is
    ``None``; on failure ``refresh_settings`` is ``None``.
    """
    if not raw_refresh or not isinstance(raw_refresh, str):
        return None, _form_parse_error("refresh_settings is required")
    try:
        refresh_settings = json.loads(raw_refresh)
    except (json.JSONDecodeError, ValueError):
        return None, _form_parse_error("Invalid JSON in refresh_settings")
    if not isinstance(refresh_settings, dict):
        return None, _form_parse_error("refresh_settings must be a JSON object")
    return refresh_settings, None


def _parse_add_plugin_form(
    form: Mapping[str, Any], files: Any
) -> tuple[str | None, dict[str, Any] | None, dict[str, Any] | None, Any]:
    """Parse and validate the add_plugin form data.

    Returns ``(plugin_id, plugin_settings, refresh_settings, error_response)``.
    On success ``error_response`` is None; on failure the first three are None.
    """
    plugin_settings = cast(dict[str, Any], cast(Any, parse_form)(form))
    raw_refresh = plugin_settings.pop("refresh_settings", None)
    refresh_settings, err = _parse_refresh_settings_json(raw_refresh)
    if err:
        return err
    plugin_id = plugin_settings.pop("plugin_id", None)
    if not plugin_id or not isinstance(plugin_id, str):
        return _form_parse_error("plugin_id is required", status=422, field="plugin_id")
    plugin_settings.update(cast(dict[str, Any], cast(Any, handle_request_files)(files)))
    if refresh_settings is None:
        return _form_parse_error("refresh_settings is required")
    return plugin_id, plugin_settings, refresh_settings, None


def _validate_plugin_settings_security(
    device_config: Any, plugin_id: str, plugin_settings: Any
) -> Any | None:
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


@playlist_bp.route("/add_plugin", methods=["POST"])  # type: ignore[untyped-decorator]
def add_plugin() -> Any:
    device_config = current_app.config["DEVICE_CONFIG"]
    playlist_manager = device_config.get_playlist_manager()

    with route_error_boundary(
        "add plugin to playlist",
        logger=logger,
        hint="Validate inputs; ensure playlist exists and instance name is not duplicated.",
    ):
        plugin_id, plugin_settings, refresh_settings, parse_err = (
            _parse_add_plugin_form(request.form, request.files)
        )
        if parse_err:
            return parse_err
        assert plugin_id is not None
        assert plugin_settings is not None
        assert refresh_settings is not None

        result = prepare_add_plugin_workflow(
            plugin_id,
            plugin_settings,
            refresh_settings,
            playlist_manager=playlist_manager,
            device_config=device_config,
        )
        if not result.ok:
            error = result.error
            if error is None:
                raise OperationFailedError("Failed to add to playlist")
            return json_error(error.message, **error.as_json_kwargs())
    return json_success("Scheduled refresh configured.")


@playlist_bp.route("/playlists", methods=["GET"])  # type: ignore[untyped-decorator]
def playlists_redirect() -> Any:
    return redirect(url_for("playlist.playlists"))


@playlist_bp.route("/playlist", methods=["GET"])  # type: ignore[untyped-decorator]
def playlists() -> Any:
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
    playlist_timing: dict[str, dict[str, int | str | None]] = {}
    rotation_eta: dict[str, dict[str, dict[str, int | str]]] = {}
    try:
        for pl in playlist_manager.playlists:
            cycle_sec = getattr(pl, "cycle_interval_seconds", None)
            cycle_min = int(
                (int(cycle_sec) if cycle_sec else device_cycle_minutes * 60) // 60
            )
            item: dict[str, int | str | None] = {
                "cycle_minutes": cycle_min,
                "next_in_minutes": None,
                "next_at": None,
            }
            try:
                is_active = bool(
                    last_dt and getattr(ri_obj, "playlist", None) == pl.name
                )
                if is_active:
                    # compute next time
                    next_dt = cast(datetime, last_dt) + timedelta(minutes=cycle_min)
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
                        is_active, cast(datetime | None, last_dt), cycle_min, now
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
        active_nav="playlists",
    )


def _parse_playlist_request_data(
    *,
    form_fields: tuple[str, ...],
    unsupported_message: str = "Unsupported media type",
    unsupported_status: int = 415,
) -> tuple[dict[str, Any] | None, RequestModelError | None]:
    """Parse and validate playlist create/update request data.

    Returns (data_dict, error_response). If error_response is not None, return it.
    """
    if request.is_json:
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return None, RequestModelError("Invalid JSON data")
        return data, None

    form_data = request.form.to_dict()
    if any(k in form_data for k in form_fields):
        return form_data, None
    return None, RequestModelError(unsupported_message, status=unsupported_status)


def _parse_playlist_update_payload(
    data: Any,
) -> tuple[PlaylistUpdateRequest | None, Any]:
    """Validate an /update_playlist request payload."""
    parsed, error = parse_playlist_update_request(data)
    if error is not None:
        return None, _request_model_error_response(error)
    if parsed is None:
        return None, json_error("Invalid playlist payload", status=400)
    return parsed, None


@playlist_bp.route("/create_playlist", methods=["POST"])  # type: ignore[untyped-decorator]
def create_playlist() -> Any:
    device_config = current_app.config["DEVICE_CONFIG"]
    playlist_manager = device_config.get_playlist_manager()

    data, err = _parse_playlist_request_data(
        form_fields=("playlist_name", "start_time", "end_time", "cycle_minutes")
    )
    if err:
        return _request_model_error_response(err)
    if data is None:
        return json_error("Invalid playlist request", status=400)

    parsed, parse_err = parse_playlist_create_request(data)
    if parse_err is not None:
        return _request_model_error_response(parse_err)
    if parsed is None:
        return json_error("Invalid playlist request", status=400)

    with route_error_boundary(
        "create playlist",
        logger=logger,
        hint="Ensure the playlist name is unique and the config is writable.",
    ):
        playlist = playlist_manager.get_playlist(parsed.playlist_name)
        if playlist:
            raise ClientInputError(
                "A playlist with that name already exists",
                status=400,
                code=_CODE_VALIDATION,
                field="playlist_name",
            )

        # Prevent overlapping time windows
        try:
            overlap_err = _check_playlist_overlap(
                parsed.start_min, parsed.end_min, playlist_manager.playlists
            )
            if overlap_err:
                return overlap_err
        except Exception:
            # best-effort, fallback to allow
            pass

        add_pl_result: list[bool] = []

        def _do_add_playlist(cfg: Any) -> None:
            add_pl_result.append(
                playlist_manager.add_playlist(
                    parsed.playlist_name, parsed.start_time, parsed.end_time
                )
            )
            _apply_cycle_override(
                playlist_manager, parsed.playlist_name, parsed.cycle_minutes_int
            )

        device_config.update_atomic(_do_add_playlist)
        if not add_pl_result or not add_pl_result[0]:
            raise OperationFailedError("Failed to create playlist")

        warning = None
        if parsed.playlist_name != "Default":
            warning = _default_overlap_warning(
                parsed.start_min, parsed.end_min, playlist_manager.playlists
            )

    if warning:
        return json_success("Created new Playlist!", warning=warning)
    return json_success("Created new Playlist!")


def _apply_cycle_override(
    playlist_manager: Any, new_name: str, cycle_minutes_int: int | None
) -> None:
    """Apply optional cycle interval override to a playlist.

    ``cycle_minutes_int`` must already be a validated integer or None.
    """
    if cycle_minutes_int is None:
        return
    playlist = playlist_manager.get_playlist(new_name)
    if playlist:
        playlist.cycle_interval_seconds = cycle_minutes_int * 60


@playlist_bp.route("/update_playlist/<string:playlist_name>", methods=["PUT"])  # type: ignore[untyped-decorator]
def update_playlist(playlist_name: str) -> Any:
    device_config = current_app.config["DEVICE_CONFIG"]
    playlist_manager = device_config.get_playlist_manager()

    data, body_err = _parse_playlist_request_data(
        form_fields=("new_name", "start_time", "end_time", "cycle_minutes"),
        unsupported_message="Invalid JSON data",
        unsupported_status=400,
    )
    if body_err:
        return _request_model_error_response(body_err)
    if data is None:
        return json_error("Invalid playlist request", status=400)

    parsed, err = _parse_playlist_update_payload(data)
    if err:
        return err
    if parsed is None:
        return json_error("Invalid playlist payload", status=400)

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
            parsed.start_min,
            parsed.end_min,
            playlist_manager.playlists,
            exclude_name=playlist_name,
        )
        if overlap_err:
            return overlap_err
    except Exception:
        pass

    upd_result: list[bool] = []
    duplicate_name_result: list[bool] = []

    def _do_update_playlist(cfg: Any) -> None:
        existing_with_new_name = playlist_manager.get_playlist(parsed.new_name)
        if (
            existing_with_new_name is not None
            and existing_with_new_name is not playlist
        ):
            duplicate_name_result.append(True)
            return
        upd_result.append(
            playlist_manager.update_playlist(
                playlist_name, parsed.new_name, parsed.start_time, parsed.end_time
            )
        )
        _apply_cycle_override(
            playlist_manager, parsed.new_name, parsed.cycle_minutes_int
        )

    device_config.update_atomic(_do_update_playlist)
    if duplicate_name_result:
        return json_error(
            "A playlist with that name already exists",
            status=400,
            code=_CODE_VALIDATION,
            details={"field": "new_name"},
        )
    if not upd_result or not upd_result[0]:
        return json_error("Failed to update playlist", status=500)

    # Warn if the updated playlist overlaps with Default.
    warning = None
    if playlist_name != "Default" and parsed.new_name != "Default":
        warning = _default_overlap_warning(
            parsed.start_min, parsed.end_min, playlist_manager.playlists
        )

    if warning:
        return json_success("Updated playlist!", warning=warning)
    return json_success("Updated playlist!")


@playlist_bp.route("/delete_playlist/<string:playlist_name>", methods=["DELETE"])  # type: ignore[untyped-decorator]
def delete_playlist(playlist_name: str) -> Any:
    device_config = current_app.config["DEVICE_CONFIG"]
    playlist_manager = device_config.get_playlist_manager()

    if not playlist_name:
        return json_error(
            PLAYLIST_NAME_REQUIRED_ERROR,
            status=400,
            code=_CODE_VALIDATION,
            details={"field": "playlist_name"},
        )

    # JTN-781: refuse to delete the canonical "Default" playlist. This match is
    # intentionally case-sensitive to mirror how "Default" is treated elsewhere
    # (create/update/overlap-warning/plugin auto-add all key off the exact
    # string). A user-created playlist named "default" is a different playlist
    # and remains deletable.
    if playlist_name == DEFAULT_PLAYLIST_NAME:
        return json_error(
            _MSG_CANNOT_DELETE_DEFAULT,
            status=400,
            code=_CODE_VALIDATION,
            details={"field": "playlist_name"},
        )

    playlist = playlist_manager.get_playlist(playlist_name)
    if not playlist:
        # JTN-782: missing playlist is a 404 Not Found, not a 400 validation
        # error. Keep the field attribution so the UI can still surface the
        # offending input when it wants to.
        return json_error(
            "Playlist does not exist",
            status=404,
            code="not_found",
            details={"field": "playlist_name"},
        )

    device_config.update_atomic(
        lambda cfg: playlist_manager.delete_playlist(playlist_name)
    )

    return json_success("Deleted playlist!")


@playlist_bp.route("/update_device_cycle", methods=["PUT"])  # type: ignore[untyped-decorator]
def update_device_cycle() -> Any:
    device_config = current_app.config["DEVICE_CONFIG"]
    refresh_task = current_app.config["REFRESH_TASK"]
    parsed, parse_error = parse_device_cycle_request(request.get_json(silent=True))
    if parse_error is not None:
        return _request_model_error_response(parse_error)
    if parsed is None:
        return json_error("Invalid minutes", status=400)

    with route_error_boundary(
        "update_device_cycle",
        logger=logger,
        hint="Check config write permissions.",
    ):
        device_config.update_value(
            "plugin_cycle_interval_seconds", parsed.minutes * 60, write=True
        )
        try:
            refresh_task.signal_config_change()
        except Exception:
            pass
        return json_success("Device refresh cadence updated.")


@playlist_bp.route("/reorder_plugins", methods=["POST"])  # type: ignore[untyped-decorator]
def reorder_plugins() -> Any:
    device_config = current_app.config["DEVICE_CONFIG"]
    playlist_manager = device_config.get_playlist_manager()

    with route_error_boundary(
        "reorder plugins",
        logger=logger,
        hint="Validate payload shape and ensure the playlist exists.",
    ):
        parsed, parse_error = parse_playlist_reorder_request(
            request.get_json(silent=True)
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

        reorder_result: list[bool] = []
        ordered_payload = parsed.ordered_payload()

        def _do_reorder(cfg: Any) -> None:
            reorder_result.append(playlist.reorder_plugins(ordered_payload))

        device_config.update_atomic(_do_reorder)
        if not reorder_result or not reorder_result[0]:
            raise ClientInputError("Invalid order payload", status=400)

        return json_success("Reordered plugins")


# Trigger next eligible instance in a specific playlist immediately
@playlist_bp.route("/display_next_in_playlist", methods=["POST"])  # type: ignore[untyped-decorator]
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


@playlist_bp.route("/playlist/eta/<string:playlist_name>", methods=["GET"])  # type: ignore[untyped-decorator]
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

        is_active = bool(last_dt and getattr(ri_obj, "playlist", None) == playlist_name)
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


@playlist_bp.app_template_filter("format_relative_time")  # type: ignore[untyped-decorator]
def format_relative_time(iso_date_string: str) -> str:
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
