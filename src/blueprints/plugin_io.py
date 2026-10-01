"""Plugin instance export/import endpoints (JTN-448).

GET  /api/plugins/export?instance=<name>   – export one instance as JSON attachment
GET  /api/plugins/export                   – export ALL instances as JSON attachment
POST /api/plugins/import                   – import instances from JSON body or multipart file
"""

from __future__ import annotations

import json
import logging
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

from flask import Blueprint, Response, current_app, jsonify, request

from services.playlist_workflows import validate_plugin_settings_security
from utils.form_utils import sanitize_log_field
from utils.http_utils import JsonResponse, json_error

logger = logging.getLogger(__name__)

plugin_io_bp = Blueprint("plugin_io", __name__)

_CONFIG_KEY = "DEVICE_CONFIG"
_EXPORT_VERSION = 1
_ERR_PLUGIN_INSTANCE_NOT_FOUND = "Plugin instance not found"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _all_instances(playlist_manager: Any) -> list[dict[str, Any]]:
    """Collect all plugin instances across all playlists as export dicts."""
    seen: set[tuple[str, str]] = set()
    instances: list[dict[str, Any]] = []
    for playlist in playlist_manager.playlists:
        for plugin_inst in playlist.plugins:
            key = (plugin_inst.plugin_id, plugin_inst.name)
            if key in seen:
                continue
            seen.add(key)
            instances.append(
                {
                    "plugin_id": plugin_inst.plugin_id,
                    "name": plugin_inst.name,
                    "settings": dict(plugin_inst.settings or {}),
                }
            )
    return instances


def _build_export_payload(instances: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "version": _EXPORT_VERSION,
        "exported_at": datetime.now(UTC).isoformat(),
        "instances": instances,
    }


def _make_json_attachment(payload: dict[str, Any], filename: str) -> Response:
    """Return a Flask response with the payload as a JSON file download."""
    from flask import Response

    data = json.dumps(payload, indent=2)
    resp = Response(
        data,
        status=200,
        mimetype="application/json",
    )
    resp.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


@plugin_io_bp.route("/api/plugins/export", methods=["GET"])
def export_plugins() -> Response | JsonResponse:
    """Export one or all plugin instances as a downloadable JSON file.

    Query parameters:
        instance (str, optional): name of a specific instance to export.
            If omitted, all instances are exported.
    """
    device_config = current_app.config[_CONFIG_KEY]
    playlist_manager = device_config.get_playlist_manager()

    instance_name = request.args.get("instance", "").strip()

    if instance_name:
        # Find across all playlists — return first match
        match = None
        for playlist in playlist_manager.playlists:
            for plugin_inst in playlist.plugins:
                if plugin_inst.name == instance_name:
                    match = plugin_inst
                    break
            if match:
                break

        if not match:
            logger.warning(
                "export_plugin_instances: instance not found name=%s",
                sanitize_log_field(instance_name),
            )
            return json_error(_ERR_PLUGIN_INSTANCE_NOT_FOUND, status=404)

        instances = [
            {
                "plugin_id": match.plugin_id,
                "name": match.name,
                "settings": dict(match.settings or {}),
            }
        ]
        filename = f"inkypi_plugin_{instance_name.replace(' ', '_')}.json"
    else:
        instances = _all_instances(playlist_manager)
        filename = "inkypi_plugins_export.json"

    payload = _build_export_payload(instances)
    return _make_json_attachment(payload, filename)


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------


def _parse_import_body() -> Any | None:
    """Return parsed JSON from request body (JSON or multipart file).

    Returns None when content cannot be parsed as JSON.
    """
    # Priority 1: application/json body
    if request.is_json:
        return request.get_json(silent=True)

    # Priority 2: multipart/form-data file upload
    file = request.files.get("file")
    if file:
        try:
            raw = file.read()
            return json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None

    # Priority 3: raw body (text/plain or similar)
    try:
        raw = request.get_data(as_text=False)
        if raw:
            return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        pass

    return None


def _validate_payload(payload: object) -> tuple[str | None, list[dict[str, Any]]]:
    """Return an error message if the payload shape is invalid, else None."""
    if not isinstance(payload, dict):
        return "Invalid JSON: expected an object", []
    if "version" not in payload:
        return "Missing required field: 'version'", []
    if "instances" not in payload:
        return "Missing required field: 'instances'", []
    raw_instances = payload.get("instances")
    if not isinstance(raw_instances, list):
        return "'instances' must be an array", []
    instances: list[dict[str, Any]] = []
    for i, inst in enumerate(raw_instances):
        if not isinstance(inst, dict):
            return f"instances[{i}] must be an object", []
        if "plugin_id" not in inst:
            return f"instances[{i}] missing required field 'plugin_id'", []
        if "settings" not in inst:
            return f"instances[{i}] missing required field 'settings'", []
        instances.append(cast(dict[str, Any], inst))
    return None, instances


@dataclass(frozen=True)
class _ImportInstance:
    plugin_id: str
    name: str
    settings: dict[str, Any]


def _prepare_import_instances(
    device_config: Any, instances: list[dict[str, Any]]
) -> tuple[list[_ImportInstance], list[str], JsonResponse | None]:
    """Validate the entire installed batch before touching playlist state."""
    installed_ids = {
        plugin["id"]
        for plugin in device_config.get_plugins()
        if isinstance(plugin, dict) and "id" in plugin
    }
    prepared: list[_ImportInstance] = []
    skipped: list[str] = []
    for index, instance in enumerate(instances):
        plugin_id = str(instance["plugin_id"]).strip()
        if plugin_id not in installed_ids:
            logger.info("plugin_import: skipping unknown plugin_id=%r", plugin_id)
            if plugin_id not in skipped:
                skipped.append(plugin_id)
            continue
        field = f"instances[{index}].settings"
        settings = instance["settings"]
        if not isinstance(settings, dict):
            return (
                [],
                skipped,
                json_error(
                    f"{field} must be an object", status=400, details={"field": field}
                ),
            )
        settings = deepcopy(settings)
        error = validate_plugin_settings_security(device_config, plugin_id, settings)
        if error is not None:
            return (
                [],
                skipped,
                json_error(
                    f"{field}: {error.message}",
                    status=error.status,
                    code=error.code,
                    details={"field": field},
                ),
            )
        name = str(instance.get("name", "")).strip() or plugin_id
        prepared.append(_ImportInstance(plugin_id, name, settings))
    return prepared, skipped, None


def _unique_import_name(name: str, existing_names: set[str]) -> str:
    if name not in existing_names:
        return name
    candidate = f"{name} (imported)"
    suffix = 1
    while candidate in existing_names:
        suffix += 1
        candidate = f"{name} (imported {suffix})"
    return candidate


def _add_import_instances(
    device_config: Any, prepared: list[_ImportInstance]
) -> list[str]:
    """Commit creation, collision resolution and additions under one lock."""
    renamed: list[str] = []
    if not prepared:
        return renamed

    def apply_import(_config: object) -> None:
        manager = device_config.get_playlist_manager()
        existing_names = {
            plugin.name for playlist in manager.playlists for plugin in playlist.plugins
        }
        playlist = manager.get_playlist("Default")
        if playlist is None:
            manager.add_playlist("Default")
            playlist = manager.get_playlist("Default")
        if playlist is None:
            raise RuntimeError("Could not create import playlist")
        for instance in prepared:
            name = _unique_import_name(instance.name, existing_names)
            if name != instance.name:
                renamed.append(f"{instance.name} → {name}")
            added = playlist.add_plugin(
                {
                    "plugin_id": instance.plugin_id,
                    "name": name,
                    "refresh": {"interval": 3600},
                    "plugin_settings": instance.settings,
                }
            )
            if not added:
                raise RuntimeError("Could not add imported plugin")
            existing_names.add(name)

    device_config.update_atomic(apply_import)
    return renamed


@plugin_io_bp.route("/api/plugins/import", methods=["POST"])
def import_plugins() -> (
    tuple[Response | dict[str, Any], int] | Response | dict[str, Any]
):
    """Import plugin instances from a JSON body or multipart file upload.

    Returns:
        JSON with keys:
            imported (int): number of instances successfully imported
            skipped  (list[str]): plugin_ids not installed on this device
            renamed  (list[str]): instances renamed to avoid name collisions
    """
    device_config = current_app.config[_CONFIG_KEY]
    payload = _parse_import_body()
    if payload is None:
        return json_error("Could not parse JSON from request", status=400)

    validation_error, instances = _validate_payload(payload)
    if validation_error is not None:
        return json_error(validation_error, status=400)

    try:
        prepared, skipped, import_error = _prepare_import_instances(
            device_config, instances
        )
        if import_error is not None:
            return import_error
        renamed = _add_import_instances(device_config, prepared)
    except Exception:
        logger.exception("plugin import failed")
        return json_error(
            "An internal error occurred",
            status=500,
            code="internal_error",
            details={"context": "import plugins"},
        )

    return jsonify(
        {
            "success": True,
            "imported": len(prepared),
            "skipped": skipped,
            "renamed": renamed,
        }
    )
