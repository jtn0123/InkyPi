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
            inst = playlist.peek_next_plugin()
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
        inst = playlist.peek_next_plugin()
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
