"""Plugin instance config history and diff API endpoints (JTN-479).

GET /api/plugins/instance/<name>/history?limit=N
    Returns a JSON list of recent settings changes for the named plugin instance,
    newest-first.  404 if the instance doesn't exist; 400 on bad input.

GET /api/plugins/instance/<name>/diff
    Returns the diff between the two most-recent history entries.
    404 if the instance doesn't exist or fewer than two history entries exist.
"""

from __future__ import annotations

import logging
import re

from flask import Blueprint, current_app, jsonify, request

from utils.http_utils import json_error
from utils.plugin_history import compute_diff, get_history

logger = logging.getLogger(__name__)

plugin_history_bp = Blueprint("plugin_history", __name__)

_CONFIG_KEY = "DEVICE_CONFIG"
# Only allow instance names that are safe filesystem identifiers.
# Strict allowlist regex makes this an explicit barrier for taint analyzers.
# Aligned with _INSTANCE_NAME_RE in playlist.py to accept user-entered names
# that include spaces (JTN-451).
_VALID_NAME_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9 _\-]{0,63}\Z")


def _safe_instance_name(name: str) -> str | None:
    """Return *name* if it matches the strict allowlist, else None.

    This is the single point of validation for any user-controlled instance
    name before it is used to build a filesystem path. CodeQL recognises
    regex full-match as a sanitizer barrier (py/path-injection).
    """
    if not name or len(name) > 64:
        return None
    if not _VALID_NAME_RE.match(name):
        return None
    return name


_MAX_LIMIT = 100


def _config_dir(device_config) -> str:
    import os

    return os.path.dirname(device_config.config_file)


def _instance_exists(device_config, instance_name: str) -> bool:
    """Return True if the named plugin instance exists in any playlist."""
    playlist_manager = device_config.get_playlist_manager()
    for pname in playlist_manager.get_playlist_names():
        playlist = playlist_manager.get_playlist(pname)
        if playlist is None:
            continue
        for plugin_entry in getattr(playlist, "plugins", []):
            if getattr(plugin_entry, "name", None) == instance_name:
                return True
    return False


@plugin_history_bp.route(
    "/api/plugins/instance/<string:instance_name>/history", methods=["GET"]
)
def plugin_instance_history(instance_name: str):
    """Return recent config-change history for a plugin instance."""
    safe_name = _safe_instance_name(instance_name)
    if safe_name is None:
        return json_error("Invalid instance name", status=400)

    device_config = current_app.config[_CONFIG_KEY]

    if not _instance_exists(device_config, safe_name):
        return json_error("Plugin instance not found", status=404)

    try:
        limit_raw = request.args.get("limit", "20")
        limit = int(limit_raw)
        limit = max(1, min(limit, _MAX_LIMIT))
    except ValueError:
        return json_error("'limit' must be an integer", status=400)

    history = get_history(_config_dir(device_config), safe_name, limit=limit)
    return jsonify({"instance": safe_name, "history": history})


@plugin_history_bp.route(
    "/api/plugins/instance/<string:instance_name>/diff", methods=["GET"]
)
def plugin_instance_diff(instance_name: str):
    """Return the diff between the two most-recent history entries."""
    safe_name = _safe_instance_name(instance_name)
    if safe_name is None:
        return json_error("Invalid instance name", status=400)

    device_config = current_app.config[_CONFIG_KEY]

    if not _instance_exists(device_config, safe_name):
        return json_error("Plugin instance not found", status=404)

    history = get_history(_config_dir(device_config), safe_name, limit=2)
    if len(history) < 2:
        return json_error(
            "Not enough history to compute a diff (need at least 2 entries)",
            status=404,
        )

    # history is newest-first: index 0 = latest, index 1 = previous
    latest = history[0]
    previous = history[1]
    diff = compute_diff(previous.get("after", {}), latest.get("after", {}))
    return jsonify(
        {
            "instance": safe_name,
            "from_ts": previous.get("ts"),
            "to_ts": latest.get("ts"),
            "diff": diff,
        }
    )
