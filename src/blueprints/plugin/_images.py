"""Image serving: plugin static assets, latest-history and instance previews."""

import os
from typing import Any

from flask import abort, current_app, send_from_directory

from utils import history_index
from utils.form_utils import sanitize_log_field
from utils.http_utils import content_disposition
from utils.security_utils import validate_file_path

from ._common import (
    _CONFIG_KEY,
    _ERR_NOT_FOUND,
    _cacheable_send_file,
    _plugins_dir,
    logger,
    plugin_bp,
)


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

    Any instance of the plugin counts. Used by the plugin page to show
    "Latest from this plugin".
    """
    device_config = current_app.config[_CONFIG_KEY]
    history_dir = str(device_config.history_image_dir)
    for entry in history_index.entries(history_dir):
        if entry.plugin_id == plugin_id:
            png_path = os.path.join(history_dir, entry.image_name)
            if os.path.exists(png_path):
                return _cacheable_send_file(png_path)
    return (_ERR_NOT_FOUND, 404)


def _find_history_image(
    device_config: Any, plugin_id: str, instance_name: str
) -> str | None:
    """Return path to the newest history PNG of this plugin instance, if any."""
    history_dir = str(device_config.history_image_dir)
    for entry in history_index.entries(history_dir):
        if entry.plugin_id == plugin_id and entry.plugin_instance == instance_name:
            png_path = os.path.join(history_dir, entry.image_name)
            if os.path.exists(png_path):
                return png_path
    return None


def _find_latest_plugin_refresh_time(device_config: Any, plugin_id: str) -> str | None:
    """Return the most recent refresh time for any instance of this plugin."""
    history_dir = str(device_config.history_image_dir)
    for entry in history_index.entries(history_dir):
        if entry.plugin_id == plugin_id and entry.refresh_time:
            return entry.refresh_time
    return None


@plugin_bp.route(
    "/instance_image/<string:plugin_id>/<string:instance_name>",
    endpoint="plugin_instance_image",
    methods=["GET"],
)
def instance_image(plugin_id: str, instance_name: str) -> Any:
    """Serve the latest image of one playlist instance, without rendering.

    A page view must never run plugin code in a web thread: there it has no
    process isolation, no plugin timeout and no health tracking, it can spend
    a paid API call (AI image/text), and a playlist page of thumbnails could
    tie up the server's few request threads. The refresh loop writes this
    file atomically whenever the instance is displayed. Until then, serve the
    instance's newest history image, else 404, which the pages handle (the
    playlist hides the tile; the plugin page falls back to the plugin's
    latest image).
    """
    device_config = current_app.config[_CONFIG_KEY]

    try:
        path = device_config.get_plugin_image_path(plugin_id, instance_name)
    except Exception:
        return (_ERR_NOT_FOUND, 404)
    if os.path.exists(path):
        return _cacheable_send_file(path)

    try:
        playlist_manager = device_config.get_playlist_manager()
        if not playlist_manager.find_plugin(plugin_id, instance_name):
            return (_ERR_NOT_FOUND, 404)
    except Exception:
        return (_ERR_NOT_FOUND, 404)
    hist = _find_history_image(device_config, plugin_id, instance_name)
    if hist and os.path.exists(hist):
        return _cacheable_send_file(hist)
    return (_ERR_NOT_FOUND, 404)
