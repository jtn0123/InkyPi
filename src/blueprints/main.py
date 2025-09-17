import os
from datetime import datetime

from flask import Blueprint, current_app, jsonify, render_template, send_file, send_from_directory
from uuid import uuid4

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
        from utils.time_utils import now_device_tz

        return now_device_tz(device_config)
    except Exception:
        return datetime.utcnow()


@main_bp.route("/")
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

    return render_template(
        "inky.html",
        config=device_config.get_config(),
        plugins=device_config.get_plugins(),
        refresh_info=device_config.get_refresh_info().to_dict(),
        next_up=next_up,
    )


@main_bp.route("/preview")
def preview_image():
    device_config = current_app.config["DEVICE_CONFIG"]
    # Prefer processed image; fall back to current raw image if missing
    path = device_config.processed_image_file
    if not os.path.exists(path):
        path = device_config.current_image_file
    if not os.path.exists(path):
        return ("Preview not available", 404)
    return send_file(path, mimetype="image/png", conditional=True)


@main_bp.route("/refresh-info")
def refresh_info():
    device_config = current_app.config["DEVICE_CONFIG"]
    try:
        info = device_config.get_refresh_info().to_dict()
    except Exception:
        info = {}
    return jsonify(info)


@main_bp.route("/next-up")
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


# Serve static assets from src/static for test and dev environments
@main_bp.route("/static/<path:filename>")
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


@main_bp.route("/display-next", methods=["POST"])
def display_next():
    device_config = current_app.config["DEVICE_CONFIG"]
    refresh_task = current_app.config["REFRESH_TASK"]
    display_manager = current_app.config["DISPLAY_MANAGER"]
    playlist_manager = device_config.get_playlist_manager()

    # Determine current time
    current_dt = _current_dt(device_config)

    # Pick next eligible and commit index change
    playlist = playlist_manager.determine_active_playlist(current_dt)
    if not playlist:
        return jsonify({"success": False, "error": "No active playlist"}), 400

    plugin_instance = playlist.get_next_eligible_plugin(current_dt)
    if not plugin_instance:
        return (
            jsonify({"success": False, "error": "No eligible plugin to display"}),
            400,
        )

    # Execute via background task if running; else do a direct update (dev path)
    request_ms = display_ms = generate_ms = preprocess_ms = None
    benchmark_id = str(uuid4())
    try:
        if getattr(refresh_task, "running", False):
            from refresh_task import PlaylistRefresh

            refresh_task.manual_update(
                PlaylistRefresh(playlist, plugin_instance, force=True)
            )
        else:
            # Direct path similar to update_now
            from time import perf_counter

            from plugins.plugin_registry import get_plugin_instance
            from utils.image_utils import compute_image_hash

            plugin_config = device_config.get_plugin(plugin_instance.plugin_id)
            if not plugin_config:
                return (
                    jsonify({"success": False, "error": "Plugin config not found"}),
                    404,
                )
            plugin = get_plugin_instance(plugin_config)
            _t_gen_start = perf_counter()
            image = plugin.generate_image(plugin_instance.settings, device_config)
            generate_ms = int((perf_counter() - _t_gen_start) * 1000)
            try:
                save_stage_event(device_config, benchmark_id, "generate_image", generate_ms)
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
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

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

    # Persist a refresh event for the dev path if request_ms is still None, compute it now
    try:
        if request_ms is None:
            from time import perf_counter as _pc

            request_ms = int((_pc() - _t_gen_start) * 1000)
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
