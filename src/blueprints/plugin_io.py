"""Plugin instance export/import endpoints (JTN-448).

GET  /api/plugins/export?instance=<name>   – export one instance as JSON attachment
GET  /api/plugins/export                   – export ALL instances as JSON attachment
POST /api/plugins/import                   – import instances from JSON body or multipart file
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from flask import Blueprint, current_app, jsonify, request

from utils.form_utils import sanitize_log_field
from utils.http_utils import json_error

logger = logging.getLogger(__name__)

plugin_io_bp = Blueprint("plugin_io", __name__)

_CONFIG_KEY = "DEVICE_CONFIG"
_EXPORT_VERSION = 1
_ERR_PLUGIN_INSTANCE_NOT_FOUND = "Plugin instance not found"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _all_instances(playlist_manager) -> list[dict]:
    """Collect all plugin instances across all playlists as export dicts."""
    seen: set[tuple[str, str]] = set()
    instances: list[dict] = []
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


def _build_export_payload(instances: list[dict]) -> dict:
    return {
        "version": _EXPORT_VERSION,
        "exported_at": datetime.now(UTC).isoformat(),
        "instances": instances,
    }


def _make_json_attachment(payload: dict, filename: str):
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
def export_plugins():
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


def _parse_import_body() -> dict | None:
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


def _validate_payload(payload: object) -> str | None:
    """Return an error message if the payload shape is invalid, else None."""
    if not isinstance(payload, dict):
        return "Invalid JSON: expected an object"
    if "version" not in payload:
        return "Missing required field: 'version'"
    if "instances" not in payload:
        return "Missing required field: 'instances'"
    if not isinstance(payload["instances"], list):
        return "'instances' must be an array"
    for i, inst in enumerate(payload["instances"]):
        if not isinstance(inst, dict):
            return f"instances[{i}] must be an object"
        if "plugin_id" not in inst:
            return f"instances[{i}] missing required field 'plugin_id'"
        if "settings" not in inst:
            return f"instances[{i}] missing required field 'settings'"
    return None


@plugin_io_bp.route("/api/plugins/import", methods=["POST"])
def import_plugins():
    """Import plugin instances from a JSON body or multipart file upload.

    Returns:
        JSON with keys:
            imported (int): number of instances successfully imported
            skipped  (list[str]): plugin_ids not installed on this device
            renamed  (list[str]): instances renamed to avoid name collisions
    """
    device_config = current_app.config[_CONFIG_KEY]
    playlist_manager = device_config.get_playlist_manager()

    payload = _parse_import_body()
    if payload is None:
        return json_error("Could not parse JSON from request", status=400)

    validation_error = _validate_payload(payload)
    if validation_error:
        return json_error(validation_error, status=400)

    # Build set of installed plugin_ids for fast lookup
    installed_ids: set[str] = {
        p["id"]
        for p in device_config.get_plugins()
        if isinstance(p, dict) and "id" in p
    }

    # Collect existing instance names across all playlists for collision detection
    existing_names: set[str] = {
        plugin_inst.name
        for playlist in playlist_manager.playlists
        for plugin_inst in playlist.plugins
    }

    # Ensure there is a playlist to import into (use Default, create if needed)
    default_playlist = playlist_manager.get_playlist("Default")
    if not default_playlist:
        playlist_manager.add_playlist("Default")
        default_playlist = playlist_manager.get_playlist("Default")

    imported = 0
    skipped: list[str] = []
    renamed: list[str] = []

    for inst in payload["instances"]:
        plugin_id = str(inst.get("plugin_id", "")).strip()
        name = str(inst.get("name", "")).strip() or plugin_id
        settings = inst.get("settings", {})
        if not isinstance(settings, dict):
            settings = {}

        # Security: reject unknown plugin_ids
        if plugin_id not in installed_ids:
            logger.info("plugin_import: skipping unknown plugin_id=%r", plugin_id)
            if plugin_id not in skipped:
                skipped.append(plugin_id)
            continue

        # Name collision: append suffix
        original_name = name
        if name in existing_names:
            candidate = f"{name} (imported)"
            suffix = 1
            while candidate in existing_names:
                suffix += 1
                candidate = f"{name} (imported {suffix})"
            name = candidate
            renamed.append(f"{original_name} → {name}")

        default_playlist.add_plugin(
            {
                "plugin_id": plugin_id,
                "name": name,
                "refresh": {"interval": 3600},
                "plugin_settings": settings,
            }
        )
        existing_names.add(name)
        imported += 1

    if imported > 0:
        device_config.write_config()

    return jsonify(
        {
            "success": True,
            "imported": imported,
            "skipped": skipped,
            "renamed": renamed,
        }
    )
