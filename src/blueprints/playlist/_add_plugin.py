"""``/add_plugin``: add a plugin instance to a playlist.

Also holds the add-plugin form parsing helpers; instance-name, refresh and
plugin-settings validation live in :mod:`services.playlist_workflows`.
"""

import json
from collections.abc import Mapping
from typing import Any, cast

from flask import current_app, request

from services.playlist_workflows import prepare_add_plugin_workflow
from utils.app_utils import handle_request_files, parse_form
from utils.backend_errors import OperationFailedError, route_error_boundary
from utils.http_utils import json_error, json_success

from ._common import _CODE_VALIDATION, logger, playlist_bp


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


@playlist_bp.route("/add_plugin", methods=["POST"])
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
