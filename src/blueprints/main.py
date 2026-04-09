import logging
import math
import os
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from uuid import uuid4

from flask import (
    Blueprint,
    current_app,
    jsonify,
    render_template,
    request,
    send_file,
    send_from_directory,
)

from utils.http_utils import json_error
from utils.image_serving import maybe_serve_webp
from utils.rate_limiter import CooldownLimiter

logger = logging.getLogger(__name__)

try:
    from benchmarks.benchmark_storage import save_refresh_event, save_stage_event
except Exception:  # pragma: no cover

    def save_refresh_event(*args, **kwargs):  # type: ignore
        return None

    def save_stage_event(*args, **kwargs):  # type: ignore
        return None


main_bp = Blueprint("main", __name__)


def _current_dt(device_config):
    try:
        from utils import time_utils

        return time_utils.now_device_tz(device_config)
    except Exception:
        return datetime.now(UTC)


@main_bp.route("/", methods=["GET"])
def main_page():
    device_config = current_app.config["DEVICE_CONFIG"]
    # Compute a non-mutating next-up preview for SSR convenience
    playlist_manager = device_config.get_playlist_manager()
    current_dt = _current_dt(device_config)

    next_up = {}
    try:
        playlist = playlist_manager.determine_active_playlist(current_dt)
        if playlist:
            inst = (
                playlist.peek_next_eligible_plugin(current_dt)
                if hasattr(playlist, "peek_next_eligible_plugin")
                else playlist.peek_next_plugin()
            )
            if inst:
                next_up = {
                    "playlist": playlist.name,
                    "plugin_id": inst.plugin_id,
                    "plugin_instance": inst.name,
                }
    except Exception:
        next_up = {}

    # Determine whether a preview image exists (processed preferred, then current)
    has_preview = os.path.exists(device_config.processed_image_file) or os.path.exists(
        device_config.current_image_file
    )

    return render_template(
        "inky.html",
        config=device_config.get_config(),
        plugins=device_config.get_plugins(),
        refresh_info=device_config.get_refresh_info().to_dict(),
        next_up=next_up,
        has_preview=has_preview,
    )


@main_bp.route("/preview", methods=["GET"])
def preview_image():
    device_config = current_app.config["DEVICE_CONFIG"]
    # Prefer processed image; fall back to current raw image if missing
    path = device_config.processed_image_file
    if not os.path.exists(path):
        path = device_config.current_image_file
    if not os.path.exists(path):
        return ("Preview not available", 404)
    # Both candidate paths come from device_config (trusted JSON).
    abs_path = os.path.abspath(path)
    safe_root = os.path.dirname(abs_path)
    filename = os.path.basename(abs_path)
    return maybe_serve_webp(safe_root, filename, request.headers.get("Accept"))


@main_bp.route("/api/screenshot", methods=["GET"])
def screenshot():
    """Return the current display image as PNG or WebP (JTN-450).

    Prefer the processed image; fall back to current_image_file.  Supports
    content negotiation via the Accept header (WebP when advertised), conditional
    GET via If-Modified-Since / 304, and sets Cache-Control: no-cache so
    monitoring dashboards always poll for fresh content.
    """
    device_config = current_app.config["DEVICE_CONFIG"]
    path = device_config.processed_image_file
    if not os.path.exists(path):
        path = device_config.current_image_file
    if not os.path.exists(path):
        return json_error("No display image available yet", status=404)

    abs_path = os.path.abspath(path)

    # Conditional GET — If-Modified-Since
    file_mtime = int(os.path.getmtime(abs_path))
    last_modified = datetime.fromtimestamp(file_mtime, tz=UTC)
    last_modified_str = last_modified.strftime("%a, %d %b %Y %H:%M:%S GMT")

    if_modified_since = request.headers.get("If-Modified-Since")
    if if_modified_since:
        try:
            client_mtime = parsedate_to_datetime(if_modified_since)
            if int(client_mtime.timestamp()) >= file_mtime:
                return "", 304
        except (ValueError, OSError):
            pass

    safe_root = os.path.dirname(abs_path)
    filename = os.path.basename(abs_path)
    response = maybe_serve_webp(safe_root, filename, request.headers.get("Accept"))
    response.headers["Last-Modified"] = last_modified_str
    response.headers["Cache-Control"] = "no-cache, must-revalidate"
    return response


@main_bp.route("/api/current_image", methods=["GET"])
def get_current_image():
    """Serve current_image.png with conditional request support (If-Modified-Since) for polling."""
    device_config = current_app.config["DEVICE_CONFIG"]
    image_path = device_config.current_image_file

    if not os.path.exists(image_path):
        return json_error("Image not found", status=404)

    # Get the file's last modified time (UTC, truncated to seconds to match HTTP precision)
    file_mtime = int(os.path.getmtime(image_path))
    last_modified = datetime.fromtimestamp(file_mtime, tz=UTC)

    # Check If-Modified-Since header
    if_modified_since = request.headers.get("If-Modified-Since")
    if if_modified_since:
        try:
            # Parse the If-Modified-Since header (always returns timezone-aware datetime)
            client_mtime = parsedate_to_datetime(if_modified_since)
            client_mtime_seconds = int(client_mtime.timestamp())

            # Compare (both now in seconds, no sub-second precision)
            if client_mtime_seconds >= file_mtime:
                # File hasn't been modified since client's cached version
                return "", 304  # Not Modified
        except (ValueError, OSError):
            pass  # If parsing fails, proceed to send the file

    # Send the image with Last-Modified header
    response = send_file(image_path, mimetype="image/png")
    response.headers["Last-Modified"] = last_modified.strftime(
        "%a, %d %b %Y %H:%M:%S GMT"
    )
    response.headers["Cache-Control"] = "no-cache"
    return response


@main_bp.route("/refresh-info", methods=["GET"])
def refresh_info():
    device_config = current_app.config["DEVICE_CONFIG"]
    try:
        info = device_config.get_refresh_info().to_dict()
    except Exception:
        info = {}
    return jsonify(info)


@main_bp.route("/next-up", methods=["GET"])
def next_up():
    device_config = current_app.config["DEVICE_CONFIG"]
    playlist_manager = device_config.get_playlist_manager()
    current_dt = _current_dt(device_config)

    try:
        playlist = playlist_manager.determine_active_playlist(current_dt)
        if not playlist:
            return jsonify({})
        inst = (
            playlist.peek_next_eligible_plugin(current_dt)
            if hasattr(playlist, "peek_next_eligible_plugin")
            else playlist.peek_next_plugin()
        )
        if not inst:
            return jsonify({})
        return jsonify(
            {
                "playlist": playlist.name,
                "plugin_id": inst.plugin_id,
                "plugin_instance": inst.name,
            }
        )
    except Exception:
        return jsonify({})


@main_bp.route("/api/plugin_order", methods=["POST"])
def save_plugin_order():
    """Save custom plugin order from dashboard drag-and-drop."""
    device_config = current_app.config["DEVICE_CONFIG"]
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return json_error("Invalid JSON payload", status=400)
    order = data.get("order", [])
    if not isinstance(order, list):
        return json_error("Order must be a list", status=400)
    if any(not isinstance(item, str) for item in order):
        return json_error("Order entries must be strings", status=400)
    registered_ids = {p["id"] for p in device_config.get_plugins()}
    if len(order) != len(set(order)):
        return json_error("Order must not contain duplicate plugin IDs", status=400)
    invalid_ids = [pid for pid in order if pid not in registered_ids]
    if invalid_ids:
        return json_error(f"Unknown plugin IDs: {', '.join(invalid_ids)}", status=400)
    missing_ids = registered_ids.difference(order)
    if missing_ids:
        return json_error(
            f"Order must include every plugin ID exactly once; missing: {', '.join(sorted(missing_ids))}",
            status=400,
        )
    device_config.set_plugin_order(order)
    return jsonify({"success": True})


@main_bp.route("/sw.js", methods=["GET"])
def service_worker():
    """Serve the service worker from the origin root.

    Service workers must be registered from the origin root to control all
    paths beneath it.  Flask's built-in /static/<filename> route would serve
    the file under /static/sw.js, which would limit its scope to /static/*.
    """
    static_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "static")
    )
    response = send_from_directory(
        static_dir, "sw.js", mimetype="application/javascript"
    )
    response.headers["Service-Worker-Allowed"] = "/"
    return response


# Serve static assets from src/static for test and dev environments
@main_bp.route("/static/<path:filename>", methods=["GET"])
def static_files(filename: str):
    try:
        static_dir = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "static")
        )
        return send_from_directory(static_dir, filename)
    except Exception:
        return ("Not found", 404)


@main_bp.record
def _configure_app_static(state):
    """Ensure Flask's built-in static route serves from src/static for tests/dev."""
    try:
        app = state.app
        static_dir = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "static")
        )
        # Only adjust if directory exists
        if os.path.isdir(static_dir):
            app.static_folder = static_dir
            app.static_url_path = "/static"
    except Exception:
        # Best-effort; test client will fall back to blueprint route
        pass


_display_next_limiter = CooldownLimiter(10)


def _reset_display_next_cooldown():
    """Reset the display-next rate limiter. Exposed for testing."""
    _display_next_limiter.reset()


@main_bp.route("/display-next", methods=["POST"])
def display_next():
    allowed, retry_after = _display_next_limiter.check()
    if not allowed:
        remaining = math.ceil(retry_after)
        return json_error(
            f"Please wait {remaining}s before refreshing again.",
            status=429,
        )

    device_config = current_app.config["DEVICE_CONFIG"]
    refresh_task = current_app.config["REFRESH_TASK"]
    display_manager = current_app.config["DISPLAY_MANAGER"]
    playlist_manager = device_config.get_playlist_manager()

    # Determine current time
    current_dt = _current_dt(device_config)

    # Pick next eligible and commit index change
    playlist = playlist_manager.determine_active_playlist(current_dt)
    if not playlist:
        return json_error("No active playlist", status=400)

    plugin_instance = playlist.get_next_eligible_plugin(current_dt)
    if not plugin_instance:
        return json_error("No eligible plugin to display", status=400)

    # Execute via background task if running; else do a direct update (dev path)
    request_ms = display_ms = generate_ms = preprocess_ms = None
    benchmark_id = str(uuid4())
    try:
        if getattr(refresh_task, "running", False):
            from refresh_task import PlaylistRefresh

            try:
                refresh_task.manual_update(
                    PlaylistRefresh(playlist, plugin_instance, force=True)
                )
            except Exception as exc:
                logger.exception("manual_update failed")
                return json_error(f"Plugin update failed: {exc}", status=400)
        else:
            # Direct path similar to update_now
            from time import perf_counter

            from plugins.plugin_registry import get_plugin_instance
            from utils.image_utils import compute_image_hash

            plugin_config = device_config.get_plugin(plugin_instance.plugin_id)
            if not plugin_config:
                return json_error("Plugin config not found", status=404)
            plugin = get_plugin_instance(plugin_config)
            _t_gen_start = perf_counter()
            try:
                image = plugin.generate_image(plugin_instance.settings, device_config)
            except RuntimeError as exc:
                return json_error(str(exc), status=400)
            generate_ms = int((perf_counter() - _t_gen_start) * 1000)
            try:
                save_stage_event(
                    device_config, benchmark_id, "generate_image", generate_ms
                )
            except Exception:
                pass
            # Display
            try:
                display_manager.display_image(
                    image,
                    image_settings=plugin_config.get("image_settings", []),
                    history_meta={
                        "refresh_type": "Playlist",
                        "plugin_id": plugin_instance.plugin_id,
                        "playlist": playlist.name,
                        "plugin_instance": plugin_instance.name,
                    },
                )
            except TypeError:
                display_manager.display_image(
                    image,
                    image_settings=plugin_config.get("image_settings", []),
                )

            # Persist playlist state so index is not lost on next refresh
            device_config.write_config()

            # Update refresh_info
            try:
                from model import RefreshInfo

                device_config.refresh_info = RefreshInfo(
                    refresh_type="Playlist",
                    plugin_id=plugin_instance.plugin_id,
                    playlist=playlist.name,
                    plugin_instance=plugin_instance.name,
                    refresh_time=current_dt.isoformat(),
                    image_hash=compute_image_hash(image),
                    request_ms=None,
                    display_ms=None,
                    generate_ms=generate_ms,
                    preprocess_ms=None,
                    used_cached=False,
                    benchmark_id=benchmark_id,
                )
                device_config.write_config()
            except Exception:
                pass
    except Exception:
        logger.exception("display_next failed")
        return json_error("An internal error occurred", status=500)

    _display_next_limiter.record()

    # Gather metrics from refresh_info if available
    try:
        ri = device_config.get_refresh_info()
        if request_ms is None:
            request_ms = getattr(ri, "request_ms", None)
        if display_ms is None:
            display_ms = getattr(ri, "display_ms", None)
        if generate_ms is None:
            generate_ms = getattr(ri, "generate_ms", None)
        if preprocess_ms is None:
            preprocess_ms = getattr(ri, "preprocess_ms", None)
    except Exception:
        pass

    # Persist a refresh event for the dev path
    try:
        ri = device_config.get_refresh_info()
        cpu_percent = memory_percent = None
        try:
            import psutil  # type: ignore

            cpu_percent = psutil.cpu_percent(interval=None)
            memory_percent = psutil.virtual_memory().percent
        except Exception:
            pass
        save_refresh_event(
            device_config,
            {
                "refresh_id": getattr(ri, "benchmark_id", benchmark_id),
                "ts": None,
                "plugin_id": plugin_instance.plugin_id,
                "instance": plugin_instance.name,
                "playlist": playlist.name,
                "used_cached": False,
                "request_ms": request_ms,
                "generate_ms": generate_ms,
                "preprocess_ms": getattr(ri, "preprocess_ms", None),
                "display_ms": getattr(ri, "display_ms", None),
                "cpu_percent": cpu_percent,
                "memory_percent": memory_percent,
                "notes": "display_next_dev",
            },
        )
    except Exception:
        pass

    return (
        jsonify(
            {
                "success": True,
                "message": "Display updated",
                "metrics": {
                    "request_ms": request_ms,
                    "generate_ms": generate_ms,
                    "preprocess_ms": preprocess_ms,
                    "display_ms": display_ms,
                },
            }
        ),
        200,
    )


@main_bp.route("/refresh", methods=["POST"])
def refresh_alias():
    """Backward-compatible alias for manual display advance."""
    return display_next()
