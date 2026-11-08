"""Playlist create / update / delete, device cycle and plugin reorder."""

from typing import Any

from flask import current_app, request

from utils.backend_errors import (
    ClientInputError,
    OperationFailedError,
    ResourceLookupError,
    route_error_boundary,
)
from utils.http_utils import json_error, json_success
from utils.messages import PLAYLIST_NAME_REQUIRED_ERROR
from utils.request_models import (
    PlaylistUpdateRequest,
    RequestModelError,
    parse_device_cycle_request,
    parse_playlist_create_request,
    parse_playlist_reorder_request,
    parse_playlist_update_request,
)

from ._common import (
    _CODE_VALIDATION,
    _MSG_CANNOT_DELETE_DEFAULT,
    _MSG_PLAYLIST_NOT_FOUND,
    DEFAULT_PLAYLIST_NAME,
    _request_model_error_response,
    logger,
    playlist_bp,
)
from ._schedule import _check_playlist_overlap, _default_overlap_warning


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
) -> tuple[PlaylistUpdateRequest | None, RequestModelError | None]:
    """Validate an /update_playlist request payload."""
    parsed, error = parse_playlist_update_request(data)
    if error is not None:
        return None, error
    if parsed is None:
        return None, RequestModelError("Invalid playlist payload")
    return parsed, None


@playlist_bp.route("/create_playlist", methods=["POST"])
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


@playlist_bp.route("/update_playlist/<string:playlist_name>", methods=["PUT"])
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
        return _request_model_error_response(err)
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


@playlist_bp.route("/delete_playlist/<string:playlist_name>", methods=["DELETE"])
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


@playlist_bp.route("/update_device_cycle", methods=["PUT"])
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


@playlist_bp.route("/reorder_plugins", methods=["POST"])
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

        ordered_payload = parsed.ordered_payload()

        def _do_reorder(_cfg: object) -> None:
            playlist = playlist_manager.get_playlist(parsed.playlist_name)
            if not playlist:
                raise ResourceLookupError(
                    _MSG_PLAYLIST_NOT_FOUND,
                    status=400,
                    code=_CODE_VALIDATION,
                    details={"field": "playlist_name"},
                )
            if not playlist.reorder_plugins(ordered_payload):
                raise ClientInputError(
                    "Invalid order payload", status=400, field="ordered"
                )

        device_config.update_atomic(_do_reorder)

        return json_success("Reordered plugins")
