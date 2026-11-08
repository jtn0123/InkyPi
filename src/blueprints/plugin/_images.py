"""Image serving: plugin static assets, latest-history and instance previews."""

import json
import os
from typing import Any

from flask import abort, current_app, send_from_directory

from plugins.plugin_registry import get_plugin_instance
from utils.chromium_limiter import slot_wait_limit
from utils.form_utils import sanitize_log_field
from utils.http_utils import content_disposition
from utils.security_utils import validate_file_path

from ._common import (
    _CONFIG_KEY,
    _ERR_NOT_FOUND,
    _PLUGIN_ID,
    _cacheable_send_file,
    _plugins_dir,
    logger,
    plugin_bp,
)

#: A preview GET renders in the request thread on a cache miss. When another
#: headless browser already holds the machine-wide Chromium slot, give up fast
#: and serve the history fallback instead of parking a server thread for the
#: limiter's full default wait.
_INSTANCE_IMAGE_RENDER_WAIT_S = 3.0


@plugin_bp.route("/images/<plugin_id>/<path:filename>", methods=["GET"])
def image(plugin_id: str, filename: str) -> Any:
    # Reject null-byte / absolute path inputs up front (defence in depth).
    if (
        not plugin_id
        or "\x00" in plugin_id
        or "\x00" in filename
        or os.path.isabs(filename)
        or os.path.isabs(plugin_id)
        or plugin_id in (".", "..")
    ):
        abort(404)

    # Resolve every path segment by scanning a server-owned directory with
    # os.listdir() and matching against the user-supplied string.  The
    # eventual path passed to send_from_directory is built entirely from
    # os.listdir() output, not from request input, which keeps CodeQL's
    # py/path-injection taint flow from reaching the filesystem call.
    segments = [s for s in filename.replace("\\", "/").split("/") if s]
    if not segments or any(s in (".", "..") for s in segments):
        abort(404)

    def _match_listdir(directory: str, wanted: str) -> str | None:
        try:
            entries = os.listdir(directory)
        except OSError:
            return None
        for entry in entries:
            if entry == wanted:
                return entry  # returned value is from os.listdir, not user input
        return None

    plugins_dir = _plugins_dir()

    # Resolve plugin_id against the current plugin source tree.
    plugin_dirname = _match_listdir(plugins_dir, plugin_id)
    if plugin_dirname is None:
        logger.warning(
            "plugin.image: unknown plugin_id=%s",
            sanitize_log_field(plugin_id),
        )
        abort(404)

    plugin_dirname_str = str(plugin_dirname)
    cursor = os.path.join(plugins_dir, plugin_dirname_str)
    resolved_parts: list[str] = []
    for segment in segments:
        match = _match_listdir(cursor, segment)
        if match is None:
            abort(404)
        match_str = str(match)
        resolved_parts.append(match_str)
        cursor = os.path.join(cursor, match_str)

    # Defence-in-depth: reject any symlink entry that escapes PLUGINS_DIR.
    try:
        validate_file_path(cursor, plugins_dir)
    except ValueError:
        abort(404)

    if not os.path.isfile(cursor):
        abort(404)

    safe_dir = os.path.join(plugins_dir, plugin_dirname_str)
    safe_name = os.path.join(*resolved_parts)
    resp = send_from_directory(safe_dir, safe_name)
    try:
        ttl = int(os.getenv("INKYPI_STATIC_PLUGIN_ASSET_TTL_S", "300") or "300")
    except Exception:
        ttl = 300
    resp.headers["Cache-Control"] = f"public, max-age={max(0, ttl)}"
    resp.headers["Content-Disposition"] = content_disposition(
        "inline", resolved_parts[-1]
    )
    return resp


@plugin_bp.route(
    "/plugin_latest_image/<string:plugin_id>",
    endpoint="plugin_latest_image",
    methods=["GET"],
)
def latest_plugin_image(plugin_id: str) -> Any:
    """Serve the most recent history image for a given plugin_id.

    Searches the history directory for the latest PNG matching the plugin_id,
    regardless of instance name. Used by the plugin page to show "Latest from this plugin".

    JSON files are sorted by filename descending (newest first) so the first
    match is the most recent, giving O(1) reads in the common case.
    """
    device_config = current_app.config[_CONFIG_KEY]
    try:
        history_dir = str(device_config.history_image_dir)
        if not os.path.isdir(history_dir):
            return (_ERR_NOT_FOUND, 404)

        # Pre-filter to .json files and sort newest-first by filename
        json_files = sorted(
            (n for n in os.listdir(history_dir) if n.endswith(".json")),
            reverse=True,
        )

        for name in json_files:
            json_path = os.path.join(history_dir, name)
            try:
                with open(json_path, encoding="utf-8") as fh:
                    meta = json.load(fh)
                if meta.get(_PLUGIN_ID) == plugin_id:
                    png_path = os.path.join(history_dir, name.replace(".json", ".png"))
                    if os.path.exists(png_path):
                        return _cacheable_send_file(png_path)
            except Exception:
                continue

        return (_ERR_NOT_FOUND, 404)

    except Exception:
        return (_ERR_NOT_FOUND, 404)


def _find_history_image(
    device_config: Any, plugin_id: str, instance_name: str
) -> str | None:
    """Return path to a history PNG that matches plugin and instance, if any.

    Pre-filters directory listing to only .json filenames and sorts newest-first
    so the first match wins.
    """
    try:
        history_dir: str = str(device_config.history_image_dir)
        if not os.path.isdir(history_dir):
            return None
        json_files = sorted(
            (n for n in os.listdir(history_dir) if n.endswith(".json")),
            reverse=True,
        )
        for name in json_files:
            json_path = os.path.join(history_dir, name)
            try:
                with open(json_path, encoding="utf-8") as fh:
                    meta = json.load(fh)
                if (
                    meta.get(_PLUGIN_ID) == plugin_id
                    and meta.get("plugin_instance") == instance_name
                ):
                    png_path: str = os.path.join(
                        history_dir, name.replace(".json", ".png")
                    )
                    if os.path.exists(png_path):
                        return png_path
            except Exception:
                continue
    except Exception:
        return None
    return None


def _find_latest_plugin_refresh_time(device_config: Any, plugin_id: str) -> str | None:
    """Return the most recent refresh time for any instance of this plugin.

    Filenames follow the display_YYYYMMDD_HHMMSS pattern, so sorting by
    filename descending mirrors refresh_time ordering.  We iterate
    newest-first and return the refresh_time from the first match.
    """
    try:
        history_dir = str(device_config.history_image_dir)
        if not os.path.isdir(history_dir):
            return None

        json_files = sorted(
            (n for n in os.listdir(history_dir) if n.endswith(".json")),
            reverse=True,
        )

        for name in json_files:
            json_path = os.path.join(history_dir, name)
            try:
                with open(json_path, encoding="utf-8") as fh:
                    meta = json.load(fh)
                if meta.get(_PLUGIN_ID) == plugin_id:
                    refresh_time = meta.get("refresh_time")
                    if isinstance(refresh_time, str) and refresh_time:
                        return refresh_time
            except Exception:
                continue

        return None
    except Exception:
        return None


@plugin_bp.route(
    "/instance_image/<string:plugin_id>/<string:instance_name>",
    endpoint="plugin_instance_image",
    methods=["GET"],
)
def instance_image(plugin_id: str, instance_name: str) -> Any:
    device_config = current_app.config[_CONFIG_KEY]
    playlist_manager = device_config.get_playlist_manager()

    # Resolve expected image path
    try:
        path = device_config.get_plugin_image_path(plugin_id, instance_name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
    except Exception:
        return (_ERR_NOT_FOUND, 404)

    # Serve if already exists
    if os.path.exists(path):
        return _cacheable_send_file(path)

    # Try to generate and persist
    try:
        plugin_inst = playlist_manager.find_plugin(plugin_id, instance_name)
        if not plugin_inst:
            return (_ERR_NOT_FOUND, 404)
        plugin_config = device_config.get_plugin(plugin_id)
        if not plugin_config:
            return (_ERR_NOT_FOUND, 404)
        plugin = get_plugin_instance(plugin_config)
        with slot_wait_limit(_INSTANCE_IMAGE_RENDER_WAIT_S):
            image = plugin.generate_image(plugin_inst.settings, device_config)
        image.save(path)
        return _cacheable_send_file(path)
    except Exception:
        # Fallback to most recent matching history image
        hist = _find_history_image(device_config, plugin_id, instance_name)
        if hist and os.path.exists(hist):
            return _cacheable_send_file(hist)
        return (_ERR_NOT_FOUND, 404)
