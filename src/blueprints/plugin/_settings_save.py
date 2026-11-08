"""Plugin settings save routes, including HTMX partial responses (JTN-506)."""

import json
from typing import Any

from flask import current_app, make_response, render_template, request

from plugins.plugin_registry import get_plugin_instance
from services.plugin_workflows import save_plugin_settings_workflow
from utils.backend_errors import ClientInputError
from utils.form_utils import sanitize_log_field, validate_plugin_required_fields
from utils.http_utils import json_error, json_success
from utils.plugin_history import record_change as _record_plugin_change
from utils.request_models import parse_plugin_settings_form_request

from ._common import (
    _CONFIG_KEY,
    _ERR_INTERNAL,
    _PLUGIN_ID,
    _plugin_form_data,
    logger,
    plugin_bp,
)


@plugin_bp.route("/save_plugin_settings", methods=["POST"])
def save_plugin_settings() -> Any:
    device_config = current_app.config[_CONFIG_KEY]
    playlist_manager = device_config.get_playlist_manager()
    htmx = _is_htmx_request()

    try:
        parsed, parse_error = parse_plugin_settings_form_request(_plugin_form_data())
        if parse_error is not None:
            if htmx:
                return _render_plugin_form_error(
                    parse_error.message,
                    status=parse_error.status,
                    field=parse_error.field,
                )
            return json_error(
                parse_error.message,
                status=parse_error.status,
                code=parse_error.code,
                details=parse_error.details,
            )
        if parsed is None:
            raise ClientInputError("Invalid form payload", status=400)
        return _save_plugin_settings_common(
            plugin_id=parsed.plugin_id,
            plugin_settings=parsed.plugin_settings,
            device_config=device_config,
            playlist_manager=playlist_manager,
        )
    except Exception as e:
        logger.exception("Error saving plugin settings: %s", e)
        if htmx:
            return _render_plugin_form_error(_ERR_INTERNAL, status=500)
        return json_error(_ERR_INTERNAL, status=500)


@plugin_bp.route("/plugin/<string:plugin_id>/save", methods=["POST"])
def save_plugin_settings_alias(plugin_id: str) -> Any:
    """Backward-compatible route alias for plugin settings save."""
    device_config = current_app.config[_CONFIG_KEY]
    playlist_manager = device_config.get_playlist_manager()

    try:
        plugin_settings = _plugin_form_data()
        plugin_settings.pop(_PLUGIN_ID, None)
        return _save_plugin_settings_common(
            plugin_id=plugin_id,
            plugin_settings=plugin_settings,
            device_config=device_config,
            playlist_manager=playlist_manager,
        )
    except Exception:
        logger.exception("Error saving plugin settings (alias)")
        if _is_htmx_request():
            return _render_plugin_form_error(_ERR_INTERNAL, status=500)
        return json_error(_ERR_INTERNAL, status=500)


def _is_htmx_request() -> bool:
    """Return True when the current request originated from HTMX (JTN-506)."""
    try:
        header_value = request.headers.get("HX-Request", "")
        return isinstance(header_value, str) and header_value.lower() == "true"
    except RuntimeError:
        # Outside an active request context
        return False


def _render_plugin_form_error(
    message: str, status: int = 400, field: str | None = None
) -> Any:
    """Return an HTML error partial for the plugin settings form (JTN-506).

    HTMX swaps error content into ``#plugin-form-errors``; Flask clients that
    still speak JSON never see this branch because it's gated on the
    ``HX-Request`` header in the caller.
    """
    html = render_template(
        "partials/plugin_form_errors.html",
        error=message,
        field=field,
    )
    resp = make_response(html, status)
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    return resp


def _render_plugin_form_success(message: str) -> Any:
    """Return an HTMX success partial; fires ``pluginSettingsSaved`` toast event."""
    html = render_template(
        "partials/plugin_form_errors.html",
        error=None,
        message=message,
    )
    resp = make_response(html, 200)
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    # HX-Trigger lets the existing toast JS fire without a duplicate modal path
    resp.headers["HX-Trigger"] = json.dumps(
        {"pluginSettingsSaved": {"message": message}}
    )
    return resp


def _save_plugin_settings_common(
    plugin_id: str,
    plugin_settings: dict[str, Any],
    device_config: Any,
    playlist_manager: Any,
) -> Any:
    htmx = _is_htmx_request()
    result = save_plugin_settings_workflow(
        plugin_id,
        plugin_settings,
        device_config,
        playlist_manager,
        get_plugin_instance_fn=get_plugin_instance,
        validate_required_fields_fn=validate_plugin_required_fields,
        record_change_fn=_record_plugin_change,
    )
    if not result.ok:
        error = result.error
        if error is None:
            logger.error(
                "_save_plugin_settings_common: workflow failed without error plugin_id=%s",
                sanitize_log_field(plugin_id),
            )
            if htmx:
                return _render_plugin_form_error(_ERR_INTERNAL, status=500)
            return json_error(_ERR_INTERNAL, status=500, code="internal_error")
        if htmx:
            return _render_plugin_form_error(
                error.message,
                status=error.status,
                field=error.field,
            )
        return json_error(error.message, **error.as_json_kwargs())

    success_message = result.message
    if htmx:
        return _render_plugin_form_success(success_message)
    return json_success(
        message=success_message,
        instance_name=result.instance_name,
        warnings=result.warnings,
    )
