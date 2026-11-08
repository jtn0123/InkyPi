"""Shared state for the ``plugin`` blueprint package.

Holds the :data:`plugin_bp` blueprint object, the package logger, the
duplicated string constants and the small request/response helpers that more
than one route module uses.
"""

import logging
import os
from typing import Any, NoReturn

from flask import Blueprint, abort, request, send_file

from utils.app_utils import handle_request_files, parse_form, resolve_path
from utils.backend_errors import ClientInputError
from utils.http_utils import content_disposition
from utils.request_models import RequestModelError

# Both names are pinned to the pre-split module path ``blueprints.plugin`` so
# log records keep their logger name (log filters and caplog-based tests key
# on it) and the blueprint keeps the same import_name. The blueprint has no
# template/static folder, so its root_path is never consulted.
logger = logging.getLogger("blueprints.plugin")
plugin_bp = Blueprint("plugin", "blueprints.plugin")

# Sonar S1192 — duplicate string constants
_CONFIG_KEY = "DEVICE_CONFIG"
_PLUGIN_ID = "plugin_id"
_ERR_INTERNAL = "An internal error occurred"
_ERR_NOT_FOUND = "Not Found"
_MSG_DISPLAY_UPDATED = "Display updated"
_ERR_PLUGIN_ID_REQUIRED = "plugin_id is required"
_ERR_PLUGIN_INSTANCE_NOT_FOUND = "Plugin instance not found"
_ERR_PLUGIN_NOT_FOUND = "Plugin not found"
_ERR_PLAYLIST_NOT_FOUND = "Playlist not found"
_MSG_CIRCUIT_BREAKER_RESET = "Circuit-breaker reset for plugin instance."


def _raise_request_model_error(error: RequestModelError) -> NoReturn:
    raise ClientInputError(
        error.message,
        status=error.status,
        code=error.code,
        field=error.field,
    )


def _plugin_form_data(*, include_form_for_files: bool = False) -> dict[str, Any]:
    form_data = parse_form(request.form)
    file_args: tuple[Any, ...]
    if include_form_for_files:
        file_args = (request.files, request.form)
    else:
        file_args = (request.files,)
    form_data.update(handle_request_files(*file_args))
    return form_data


def _plugins_dir() -> str:
    """Resolve the current plugin source directory at request time."""
    return resolve_path("plugins")


def _cacheable_send_file(path: str, ttl_env: str = "INKYPI_RENDER_CACHE_TTL_S") -> Any:
    safe_path = os.path.realpath(path)
    if not os.path.isfile(safe_path):
        abort(404)
    resp = send_file(safe_path)
    try:
        ttl = int(os.getenv(ttl_env, "300") or "300")
    except Exception:
        ttl = 300
    ttl = max(0, ttl)
    resp.headers["Cache-Control"] = f"public, max-age={ttl}"
    basename = os.path.basename(safe_path)
    resp.headers["Content-Disposition"] = content_disposition("inline", basename)
    return resp
