import logging
import math
import os
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any
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

from utils.display_names import (
    friendly_instance_label,
    instance_suffix_label,
    is_auto_instance_name,
)
from utils.http_utils import json_error, json_success
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


def _device_cycle_minutes(device_config: Any) -> int:
    try:
        cycle_seconds = int(
            device_config.get_config("plugin_cycle_interval_seconds", default=3600)
        )
        # Mirror the playlist override clamp: avoid a zero-minute cycle (which
        # would schedule the next refresh in the past and surface "Due now"
        # immediately) for any configured interval below 60 seconds.
        return max(1, cycle_seconds // 60)
    except Exception:
        return 60


def _playlist_cycle_minutes(device_config: Any, playlist_name: Any) -> int:
    cycle_minutes = _device_cycle_minutes(device_config)
    if not playlist_name:
        return cycle_minutes

    try:
        playlist_manager = device_config.get_playlist_manager()
        playlist = playlist_manager.get_playlist(playlist_name)
        cycle_seconds = getattr(playlist, "cycle_interval_seconds", None)
        if cycle_seconds:
            return max(1, int(cycle_seconds) // 60)
    except Exception:
        pass

    return cycle_minutes


def _parse_refresh_datetime(iso_value: Any) -> datetime | None:
    if not iso_value:
        return None
    try:
        dt = datetime.fromisoformat(iso_value)
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def _format_next_refresh_relative(next_dt: datetime, now_dt: datetime) -> str:
    diff_seconds = max(0, int(math.ceil((next_dt - now_dt).total_seconds())))
    if diff_seconds <= 30:
        return "Due now"
    if diff_seconds < 60:
        return f"in {diff_seconds}s"

    diff_minutes = math.ceil(diff_seconds / 60)
    if diff_minutes < 60:
        return f"in {diff_minutes}m"

    hours, minutes = divmod(diff_minutes, 60)
    if hours < 24:
        if minutes:
            return f"in {hours}h {minutes}m"
        return f"in {hours}h"

    local_dt = next_dt.astimezone(now_dt.tzinfo)
    return "at " + local_dt.strftime("%I:%M %p").lstrip("0")


def _build_next_refresh_meta(
    next_dt: datetime | None, cycle_minutes: int, now_dt: datetime
) -> str:
    parts: list[str] = []
    if next_dt:
        local_dt = next_dt.astimezone(now_dt.tzinfo)
        parts.append(f"ETA {local_dt.strftime('%I:%M %p').lstrip('0')}")
    if cycle_minutes:
        parts.append(f"Every {cycle_minutes} min")
    parts.append("auto")
    return " · ".join(parts)


def _annotate_refresh_schedule(payload: Any, device_config: Any) -> Any:
    """Attach next-refresh timing metadata for dashboard rendering."""
    if not isinstance(payload, dict):
        return payload

    now_dt = _current_dt(device_config)
    cycle_minutes = _playlist_cycle_minutes(device_config, payload.get("playlist"))
    payload["cycle_minutes"] = cycle_minutes

    refresh_dt = _parse_refresh_datetime(payload.get("refresh_time"))
    if not refresh_dt:
        payload["next_refresh_time"] = None
        payload["next_refresh_relative"] = None
        payload["next_refresh_meta"] = _build_next_refresh_meta(
            None, cycle_minutes, now_dt
        )
        return payload

    next_dt = refresh_dt.astimezone(now_dt.tzinfo) + timedelta(minutes=cycle_minutes)
    payload["next_refresh_time"] = next_dt.isoformat()
    payload["next_refresh_relative"] = _format_next_refresh_relative(next_dt, now_dt)
    payload["next_refresh_meta"] = _build_next_refresh_meta(
        next_dt, cycle_minutes, now_dt
    )
    return payload


def _is_dev_mode() -> bool:
    env = (os.getenv("INKYPI_ENV") or os.getenv("FLASK_ENV") or "").strip().lower()
    return env in {"dev", "development"}


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

    device_cycle_minutes = _device_cycle_minutes(device_config)
    # Mirror /refresh-info's degrade-to-{} behaviour so a broken or missing
    # refresh info file cannot 500 the dashboard shell. The template guards
    # against empty refresh_info with `| default({})` helpers, so an empty
    # mapping is a safe render-time fallback.
    try:
        refresh_info = device_config.get_refresh_info().to_dict()
    except Exception:
        logger.exception("Failed to load refresh info for dashboard")
        refresh_info = {}
    else:
        _annotate_instance_labels(refresh_info)
        _annotate_refresh_schedule(refresh_info, device_config)

    return render_template(
        "inky.html",
        config=device_config.get_config(),
        plugins=device_config.get_plugins(),
        refresh_info=refresh_info,
        next_up=next_up,
        has_preview=has_preview,
        playlists=playlist_manager.playlists,
        active_playlist_name=playlist_manager.active_playlist,
        device_cycle_minutes=device_cycle_minutes,
        active_nav="dashboard",
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


@main_bp.route("/dev/mock-frame", methods=["GET"])
def dev_mock_frame():
    """Serve the latest simulated mock-display frame in dev mode only."""
    if not _is_dev_mode():
        return ("Not found", 404)

    display_manager = current_app.config.get("DISPLAY_MANAGER")
    display = getattr(display_manager, "display", None)
    frame_path = getattr(display, "mock_frame_path", None)
    if not frame_path:
        return ("Mock frame not available", 404)

    abs_path = os.path.abspath(frame_path)
    if not os.path.exists(abs_path):
        return ("Mock frame not available", 404)

    safe_root = os.path.dirname(abs_path)
    filename = os.path.basename(abs_path)
    return send_from_directory(
        safe_root, filename, mimetype="image/png", as_attachment=False
    )


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
    response.headers["Content-Disposition"] = (
        f'inline; filename="{os.path.basename(image_path)}"'
    )
    return response


def _plugin_display_name_map():
    """Return a {plugin_id: display_name} mapping for the current device config."""
    try:
        device_config = current_app.config["DEVICE_CONFIG"]
        return {
            p["id"]: p.get("display_name") or p["id"]
            for p in device_config.get_plugins()
        }
    except Exception:
        return {}


def _annotate_instance_labels(payload):
    """Attach friendly plugin/instance labels to a refresh-info-like dict.

    Adds ``plugin_display_name``, ``plugin_instance_label``, and
    ``plugin_instance_is_auto`` so the dashboard JS can render a friendly
    label without leaking the raw ``{plugin_id}_saved_settings`` key.
    """
    if not isinstance(payload, dict):
        return payload
    plugin_id = payload.get("plugin_id")
    instance_name = payload.get("plugin_instance")
    if plugin_id:
        display_map = _plugin_display_name_map()
        display_name = display_map.get(plugin_id) or plugin_id
        payload["plugin_display_name"] = display_name
        payload["plugin_instance_label"] = friendly_instance_label(
            instance_name, plugin_id, display_name
        )
        payload["plugin_instance_is_auto"] = is_auto_instance_name(
            instance_name, plugin_id
        )
    return payload


@main_bp.route("/refresh-info", methods=["GET"])
def refresh_info():
    device_config = current_app.config["DEVICE_CONFIG"]
    try:
        info = device_config.get_refresh_info().to_dict()
    except Exception:
        # Return an empty payload on failure — callers (dashboard JS and
        # unit tests in test_blueprint_coverage / test_startup_recovery) expect
        # `{}` rather than partial schedule metadata when refresh_info is
        # broken or missing.
        return jsonify({})
    _annotate_instance_labels(info)
    _annotate_refresh_schedule(info, device_config)
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
        payload = {
            "playlist": playlist.name,
            "plugin_id": inst.plugin_id,
            "plugin_instance": inst.name,
        }
        _annotate_instance_labels(payload)
        return jsonify(payload)
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
        return json_error("Order contains unknown plugin IDs", status=400)
    missing_ids = registered_ids.difference(order)
    if missing_ids:
        return json_error(
            "Order must include every plugin ID exactly once",
            status=400,
        )
    device_config.set_plugin_order(order)
    return json_success()


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


def _display_next_direct(
    device_config, display_manager, plugin_instance, playlist, current_dt, benchmark_id
):
    """Execute a direct display update (dev path, no background task).

    Returns ``(generate_ms, error_response)``.  When *error_response* is not
    ``None`` it should be returned to the client immediately.
    """
    from time import perf_counter

    from plugins.plugin_registry import get_plugin_instance
    from utils.image_utils import compute_image_hash

    plugin_config = device_config.get_plugin(plugin_instance.plugin_id)
    if not plugin_config:
        return None, json_error("Plugin config not found", status=404)

    plugin = get_plugin_instance(plugin_config)
    _t_gen_start = perf_counter()
    try:
        image = plugin.generate_image(plugin_instance.settings, device_config)
    except RuntimeError:
        logger.exception("generate_image failed in display_next")
        return None, json_error("Plugin image generation failed", status=400)
    generate_ms = int((perf_counter() - _t_gen_start) * 1000)

    try:
        save_stage_event(device_config, benchmark_id, "generate_image", generate_ms)
    except Exception:
        pass

    # Display
    image_settings = plugin_config.get("image_settings", [])
    try:
        display_manager.display_image(
            image,
            image_settings=image_settings,
            history_meta={
                "refresh_type": "Playlist",
                "plugin_id": plugin_instance.plugin_id,
                "playlist": playlist.name,
                "plugin_instance": plugin_instance.name,
            },
        )
    except TypeError:
        display_manager.display_image(image, image_settings=image_settings)

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

    return generate_ms, None


def _gather_display_metrics(device_config, generate_ms):
    """Read timing metrics from refresh_info, filling in any gaps.

    Returns ``(request_ms, display_ms, generate_ms, preprocess_ms)``.
    """
    request_ms = display_ms = preprocess_ms = None
    try:
        ri = device_config.get_refresh_info()
        request_ms = getattr(ri, "request_ms", None)
        display_ms = getattr(ri, "display_ms", None)
        generate_ms = generate_ms or getattr(ri, "generate_ms", None)
        preprocess_ms = getattr(ri, "preprocess_ms", None)
    except Exception:
        pass
    return request_ms, display_ms, generate_ms, preprocess_ms


def _persist_dev_refresh_event(
    device_config, benchmark_id, plugin_instance, playlist, metrics
):
    """Persist a refresh event for the dev (direct) path."""
    request_ms, display_ms, generate_ms, preprocess_ms = metrics
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

    generate_ms = None
    benchmark_id = str(uuid4())
    try:
        if getattr(refresh_task, "running", False):
            from refresh_task import PlaylistRefresh

            try:
                refresh_task.manual_update(
                    PlaylistRefresh(playlist, plugin_instance, force=True)
                )
            except RuntimeError:
                logger.exception("manual_update failed")
                return json_error("Plugin update failed", status=400)
        else:
            generate_ms, err = _display_next_direct(
                device_config,
                display_manager,
                plugin_instance,
                playlist,
                current_dt,
                benchmark_id,
            )
            if err:
                return err
    except Exception:
        logger.exception("display_next failed")
        return json_error("An internal error occurred", status=500)

    _display_next_limiter.record()

    metrics = _gather_display_metrics(device_config, generate_ms)
    _persist_dev_refresh_event(
        device_config, benchmark_id, plugin_instance, playlist, metrics
    )
    request_ms, display_ms, generate_ms, preprocess_ms = metrics

    return json_success(
        message="Display updated",
        metrics={
            "request_ms": request_ms,
            "generate_ms": generate_ms,
            "preprocess_ms": preprocess_ms,
            "display_ms": display_ms,
        },
    )


@main_bp.route("/refresh", methods=["POST"])
def refresh_alias():
    """Backward-compatible alias for manual display advance."""
    return display_next()


# ---------------------------------------------------------------------------
# Jinja template filters for friendly plugin-instance display names.
# ---------------------------------------------------------------------------


@main_bp.app_template_filter("friendly_instance_label")
def _jinja_friendly_instance_label(instance_name, plugin_id=None):
    """Jinja filter: return a friendly label for a plugin instance.

    Usage: ``{{ inst.name | friendly_instance_label(inst.plugin_id) }}``.
    Falls back to the plugin's ``display_name`` when the instance name is
    auto-generated.
    """
    display_name = _plugin_display_name_map().get(plugin_id) if plugin_id else None
    return friendly_instance_label(instance_name, plugin_id, display_name)


@main_bp.app_template_filter("instance_suffix_label")
def _jinja_instance_suffix_label(instance_name, plugin_id=None):
    """Jinja filter: return a parenthesised-suffix label, or empty string."""
    label = instance_suffix_label(instance_name, plugin_id)
    return label or ""


@main_bp.app_template_filter("is_auto_instance_name")
def _jinja_is_auto_instance_name(instance_name, plugin_id=None):
    """Jinja filter: True when the instance name is the auto-generated key."""
    return is_auto_instance_name(instance_name, plugin_id)
