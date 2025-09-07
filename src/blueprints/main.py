import os

from flask import Blueprint, current_app, jsonify, render_template, send_file
from datetime import datetime

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def main_page():
    device_config = current_app.config["DEVICE_CONFIG"]
    # Compute a non-mutating next-up preview for SSR convenience
    playlist_manager = device_config.get_playlist_manager()
    latest_refresh = device_config.get_refresh_info()
    try:
        from utils.time_utils import now_device_tz

        current_dt = now_device_tz(device_config)
    except Exception:
        current_dt = datetime.utcnow()

    next_up = {}
    try:
        playlist = playlist_manager.determine_active_playlist(current_dt)
        if playlist:
            inst = playlist.peek_next_eligible_plugin(current_dt) if hasattr(playlist, 'peek_next_eligible_plugin') else playlist.peek_next_plugin()
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
    try:
        from utils.time_utils import now_device_tz

        current_dt = now_device_tz(device_config)
    except Exception:
        current_dt = datetime.utcnow()

    try:
        playlist = playlist_manager.determine_active_playlist(current_dt)
        if not playlist:
            return jsonify({})
        inst = playlist.peek_next_eligible_plugin(current_dt) if hasattr(playlist, 'peek_next_eligible_plugin') else playlist.peek_next_plugin()
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


@main_bp.route("/display-next", methods=["POST"])
def display_next():
    device_config = current_app.config["DEVICE_CONFIG"]
    refresh_task = current_app.config["REFRESH_TASK"]
    display_manager = current_app.config["DISPLAY_MANAGER"]
    playlist_manager = device_config.get_playlist_manager()

    # Determine current time
    try:
        from utils.time_utils import now_device_tz

        current_dt = now_device_tz(device_config)
    except Exception:
        current_dt = datetime.utcnow()

    # Pick next eligible and commit index change
    playlist = playlist_manager.determine_active_playlist(current_dt)
    if not playlist:
        return jsonify({"success": False, "error": "No active playlist"}), 400

    plugin_instance = playlist.get_next_eligible_plugin(current_dt)
    if not plugin_instance:
        return jsonify({"success": False, "error": "No eligible plugin to display"}), 400

    # Execute via background task if running; else do a direct update (dev path)
    request_ms = display_ms = generate_ms = preprocess_ms = None
    try:
        if getattr(refresh_task, "running", False):
            from refresh_task import PlaylistRefresh

            refresh_task.manual_update(PlaylistRefresh(playlist, plugin_instance, force=True))
        else:
            # Direct path similar to update_now
            from time import perf_counter
            from plugins.plugin_registry import get_plugin_instance
            from utils.image_utils import compute_image_hash

            plugin_config = device_config.get_plugin(plugin_instance.plugin_id)
            if not plugin_config:
                return jsonify({"success": False, "error": "Plugin config not found"}), 404
            plugin = get_plugin_instance(plugin_config)
            _t_gen_start = perf_counter()
            image = plugin.generate_image(plugin_instance.settings, device_config)
            generate_ms = int((perf_counter() - _t_gen_start) * 1000)
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

    return jsonify({
        "success": True,
        "message": "Display updated",
        "metrics": {
            "request_ms": request_ms,
            "generate_ms": generate_ms,
            "preprocess_ms": preprocess_ms,
            "display_ms": display_ms,
        }
    }), 200
