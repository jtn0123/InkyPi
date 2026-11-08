"""Plugin instance CRUD and instance actions (delete, update, display, retry)."""

import os
from html import escape
from typing import Any

from flask import current_app, request

from plugins.plugin_registry import get_plugin_instance
from refresh_task import PlaylistRefresh
from services.playlist_workflows import validate_plugin_refresh_settings
from services.plugin_workflows import (
    record_saved_settings_change,
    validate_plugin_for_save,
)
from utils.backend_errors import (
    ClientInputError,
    ResourceLookupError,
    UnsupportedMediaTypeRouteError,
    route_error_boundary,
)
from utils.form_utils import sanitize_log_field, validate_plugin_required_fields
from utils.http_utils import json_error, json_success
from utils.plugin_history import record_change as _record_plugin_change
from utils.request_models import (
    RequestModelError,
    parse_plugin_instance_action_request,
    parse_plugin_update_instance_request,
)

from ._common import (
    _CONFIG_KEY,
    _ERR_PLAYLIST_NOT_FOUND,
    _ERR_PLUGIN_INSTANCE_NOT_FOUND,
    _MSG_CIRCUIT_BREAKER_RESET,
    _MSG_DISPLAY_UPDATED,
    _plugin_form_data,
    _raise_request_model_error,
    logger,
    plugin_bp,
)


def _cleanup_plugin_resources(
    device_config: Any,
    plugin_id: str | None,
    plugin_instance_name: str | None,
    plugin_settings: dict[str, Any] | None = None,
) -> None:
    """Clean up cached image and run plugin-specific teardown after instance deletion.

    Both cleanup steps are best-effort: failures are logged as warnings but do not
    propagate so the caller's success response is unaffected.

    ``plugin_settings`` should be the deleted instance's settings dict so that
    plugin-specific cleanup (e.g. image_upload removing uploaded files) can
    inspect its own configuration.
    """
    # Clean up cached plugin instance image
    try:
        image_path = device_config.get_plugin_image_path(
            plugin_id, plugin_instance_name
        )
        if image_path and os.path.isfile(image_path):
            os.remove(image_path)
            logger.info("Removed cached image: %s", image_path)
    except Exception:
        logger.warning(
            "Could not clean up image for %s/%s",
            sanitize_log_field(plugin_id),
            sanitize_log_field(str(plugin_instance_name)),
            exc_info=True,
        )

    # Run plugin-specific cleanup (e.g., image_upload deletes uploaded files)
    try:
        plugin_config = device_config.get_plugin(plugin_id)
        if plugin_config:
            plugin_obj = get_plugin_instance(plugin_config)
            if plugin_obj and hasattr(plugin_obj, "cleanup"):
                plugin_obj.cleanup(plugin_settings or {})
    except Exception:
        logger.warning(
            "Plugin cleanup failed for %s", sanitize_log_field(plugin_id), exc_info=True
        )


@plugin_bp.route("/delete_plugin_instance", methods=["POST", "DELETE"])
def delete_plugin_instance() -> Any:
    device_config = current_app.config[_CONFIG_KEY]
    playlist_manager = device_config.get_playlist_manager()

    if not request.is_json:
        raise UnsupportedMediaTypeRouteError
    parsed, parse_error = parse_plugin_instance_action_request(
        request.get_json(silent=True)
    )
    if parse_error is not None:
        _raise_request_model_error(parse_error)
    if parsed is None:
        _raise_request_model_error(
            RequestModelError(message="Invalid or missing JSON payload", status=400)
        )

    with route_error_boundary(
        "delete plugin instance",
        logger=logger,
        hint="Ensure the playlist and plugin instance exist before deleting.",
    ):
        playlist = playlist_manager.get_playlist(parsed.playlist_name)
        if not playlist:
            raise ResourceLookupError("Playlist not found", status=400)

        existing = playlist.find_plugin(parsed.plugin_id, parsed.plugin_instance)
        plugin_settings = dict(existing.settings) if existing else {}

        del_result: list[bool] = []

        def _do_delete(cfg: Any) -> None:
            del_result.append(
                playlist.delete_plugin(parsed.plugin_id, parsed.plugin_instance)
            )

        device_config.update_atomic(_do_delete)
        if not del_result or not del_result[0]:
            raise ResourceLookupError("Plugin instance not found", status=400)
        _cleanup_plugin_resources(
            device_config,
            parsed.plugin_id,
            parsed.plugin_instance,
            plugin_settings,
        )

    return json_success(message="Deleted plugin instance.")


@plugin_bp.route("/update_plugin_instance/<string:instance_name>", methods=["PUT"])
def update_plugin_instance(instance_name: str) -> Any:
    device_config = current_app.config[_CONFIG_KEY]
    playlist_manager = device_config.get_playlist_manager()

    with route_error_boundary(
        "update plugin instance",
        logger=logger,
        hint="Check submitted plugin settings and config persistence.",
    ):
        if not instance_name:
            raise ClientInputError(
                "Instance name is required",
                status=422,
                code="validation_error",
                field="instance_name",
            )
        parsed, parse_error = parse_plugin_update_instance_request(
            _plugin_form_data(include_form_for_files=True)
        )
        if parse_error is not None:
            _raise_request_model_error(parse_error)
        if parsed is None:
            raise ClientInputError("Invalid form payload", status=400)
        plugin_id = parsed.plugin_id
        plugin_settings = parsed.plugin_settings
        plugin_instance = playlist_manager.find_plugin(plugin_id, instance_name)
        if not plugin_instance:
            logger.warning(
                "update_instance: plugin instance not found plugin_id=%s instance=%s",
                sanitize_log_field(plugin_id),
                sanitize_log_field(instance_name),
            )
            raise ResourceLookupError(
                _ERR_PLUGIN_INSTANCE_NOT_FOUND,
                status=404,
            )

        # JTN-381: parse and validate refresh_settings if present. The frontend
        # Refresh Settings modal posts this as a JSON-stringified form field;
        # previously it was accepted blindly, saved into settings verbatim,
        # and the new refresh config was never applied — reload silently
        # reverted the user's change while the toast said "success".
        new_refresh_config: dict[str, Any] | None = None
        if parsed.refresh_settings is not None:
            new_refresh_config, refresh_err = validate_plugin_refresh_settings(
                parsed.refresh_settings
            )
            if refresh_err:
                raise ClientInputError(
                    refresh_err.message,
                    status=refresh_err.status,
                    code=refresh_err.code,
                    field=refresh_err.field,
                )

        try:
            plugin_config = device_config.get_plugin(plugin_id)
            plugin = get_plugin_instance(plugin_config) if plugin_config else None
        except Exception:
            logger.warning(
                "Could not load plugin for validation: %s",
                sanitize_log_field(plugin_id),
                exc_info=True,
            )
            plugin = None
        validation_error = validate_plugin_for_save(
            plugin,
            plugin_settings,
            sanitize_log_field(plugin_id),
            validate_plugin_required_fields,
        )
        if validation_error is not None:
            if validation_error.status == 503:
                return json_error(
                    "Plugin validation is unavailable; settings were not saved.",
                    status=503,
                    code="backend_unavailable",
                )
            return json_error(
                escape(validation_error.message, quote=True),
                status=400,
                code="validation_error",
            )

        before_settings = dict(plugin_instance.settings or {})

        def _do_update_instance(cfg: Any) -> None:
            plugin_instance.settings = plugin_settings
            if new_refresh_config is not None:
                plugin_instance.refresh = new_refresh_config

        device_config.update_atomic(_do_update_instance)
        history_warning = record_saved_settings_change(
            device_config=device_config,
            instance_name=instance_name,
            before_settings=before_settings,
            after_settings=plugin_settings,
            plugin_log_id=sanitize_log_field(plugin_id),
            record_change_fn=_record_plugin_change,
        )

    return json_success(
        message=escape(
            history_warning or f"Updated plugin instance {instance_name}.", quote=True
        ),
        warnings=[escape(history_warning, quote=True)] if history_warning else [],
    )


@plugin_bp.route("/display_plugin_instance", methods=["POST"])
def display_plugin_instance() -> Any:
    device_config = current_app.config[_CONFIG_KEY]
    refresh_task = current_app.config["REFRESH_TASK"]
    playlist_manager = device_config.get_playlist_manager()

    if not request.is_json:
        raise UnsupportedMediaTypeRouteError
    parsed, parse_error = parse_plugin_instance_action_request(
        request.get_json(silent=True)
    )
    if parse_error is not None:
        _raise_request_model_error(parse_error)
    if parsed is None:
        _raise_request_model_error(
            RequestModelError(message="Invalid or missing JSON payload", status=400)
        )

    with route_error_boundary(
        "display plugin instance",
        logger=logger,
        hint="Ensure the playlist exists and the refresh task can run the instance.",
    ):
        playlist = playlist_manager.get_playlist(parsed.playlist_name)
        if not playlist:
            logger.warning(
                "display_plugin_instance: playlist not found name=%s",
                sanitize_log_field(parsed.playlist_name),
            )
            raise ResourceLookupError(_ERR_PLAYLIST_NOT_FOUND, status=400)

        plugin_instance = playlist.find_plugin(parsed.plugin_id, parsed.plugin_instance)
        if not plugin_instance:
            logger.warning(
                "display_plugin_instance: plugin instance not found "
                "playlist=%s plugin_id=%s instance=%s",
                sanitize_log_field(parsed.playlist_name),
                sanitize_log_field(parsed.plugin_id),
                sanitize_log_field(parsed.plugin_instance),
            )
            raise ResourceLookupError(
                _ERR_PLUGIN_INSTANCE_NOT_FOUND,
                status=400,
            )

        refresh_task.manual_update(
            PlaylistRefresh(playlist, plugin_instance, force=True)
        )

    return json_success(message=_MSG_DISPLAY_UPDATED)


@plugin_bp.route(
    "/plugin_instance/<string:plugin_id>/<string:instance_name>/force_retry",
    methods=["POST"],
)
def force_retry_plugin_instance(plugin_id: str, instance_name: str) -> Any:
    """Clear the circuit-breaker paused state for a plugin instance.

    Allows a paused plugin to be retried on the next scheduler cycle without
    waiting for a successful refresh to reset it automatically.
    """
    refresh_task = current_app.config.get("REFRESH_TASK")
    if refresh_task is None:
        return json_error("Refresh task not available", status=503)
    if not hasattr(refresh_task, "reset_circuit_breaker"):
        return json_error("Circuit-breaker reset not supported", status=501)
    found = refresh_task.reset_circuit_breaker(plugin_id, instance_name)
    if not found:
        logger.warning(
            "force_retry: plugin instance not found plugin_id=%s instance=%s",
            sanitize_log_field(plugin_id),
            sanitize_log_field(instance_name),
        )
        return json_error(
            _ERR_PLUGIN_INSTANCE_NOT_FOUND,
            status=404,
        )
    logger.info(
        "Circuit-breaker reset for plugin_id=%s instance=%s",
        sanitize_log_field(plugin_id),
        sanitize_log_field(instance_name),
    )
    return json_success(
        message=_MSG_CIRCUIT_BREAKER_RESET,
    )
