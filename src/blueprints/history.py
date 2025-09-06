import os
import logging
from typing import List, Dict
from datetime import datetime

from flask import Blueprint, current_app, render_template, jsonify, request, send_from_directory

logger = logging.getLogger(__name__)

history_bp = Blueprint('history', __name__)


def _format_size(num_bytes: int) -> str:
    size: float = float(num_bytes)
    try:
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if size < 1024.0:
                return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} {unit}"
            size /= 1024.0
        return f"{size:.1f} PB"
    except Exception:
        return "-"


def _list_history_images(history_dir: str) -> List[Dict]:
    try:
        files = [
            f for f in os.listdir(history_dir)
            if os.path.isfile(os.path.join(history_dir, f)) and f.lower().endswith('.png')
        ]
    except Exception:
        logger.exception("Failed to list history directory")
        files = []

    files.sort(key=lambda f: os.path.getmtime(os.path.join(history_dir, f)), reverse=True)
    result: List[Dict] = []
    for f in files:
        full_path = os.path.join(history_dir, f)
        mtime = os.path.getmtime(full_path)
        size = os.path.getsize(full_path)
        dt = datetime.fromtimestamp(mtime)
        result.append({
            "filename": f,
            "mtime": mtime,
            "mtime_str": dt.strftime("%b %d, %Y %I:%M %p").lstrip('0').replace(' 0', ' '),
            "size": size,
            "size_str": _format_size(size),
        })
    return result


@history_bp.route('/history')
def history_page():
    device_config = current_app.config['DEVICE_CONFIG']
    history_dir = device_config.history_image_dir
    images = _list_history_images(history_dir)
    return render_template('history.html', images=images)


@history_bp.route('/history/image/<path:filename>')
def history_image(filename: str):
    device_config = current_app.config['DEVICE_CONFIG']
    history_dir = device_config.history_image_dir
    return send_from_directory(history_dir, filename)


@history_bp.route('/history/redisplay', methods=['POST'])
def history_redisplay():
    device_config = current_app.config['DEVICE_CONFIG']
    display_manager = current_app.config['DISPLAY_MANAGER']
    history_dir = device_config.history_image_dir

    try:
        data = request.get_json(force=True)
        filename = (data or {}).get('filename')
        if not filename:
            return jsonify({"error": "filename is required"}), 400

        # Prevent path traversal; only allow files within the history dir
        safe_path = os.path.normpath(os.path.join(history_dir, filename))
        if not safe_path.startswith(os.path.abspath(history_dir)):
            return jsonify({"error": "invalid filename"}), 400
        if not os.path.exists(safe_path):
            return jsonify({"error": "file not found"}), 404

        display_manager.display_preprocessed_image(safe_path)
        return jsonify({"success": True, "message": "Display updated"}), 200
    except Exception as e:
        logger.exception("Error redisplaying history image")
        return jsonify({"error": f"An error occurred: {str(e)}"}), 500


@history_bp.route('/history/delete', methods=['POST'])
def history_delete():
    device_config = current_app.config['DEVICE_CONFIG']
    history_dir = device_config.history_image_dir
    try:
        data = request.get_json(force=True) or {}
        filename = data.get('filename')
        if not filename:
            return jsonify({"error": "filename is required"}), 400
        safe_path = os.path.normpath(os.path.join(history_dir, filename))
        if not safe_path.startswith(os.path.abspath(history_dir)):
            return jsonify({"error": "invalid filename"}), 400
        if os.path.exists(safe_path):
            os.remove(safe_path)
        return jsonify({"success": True, "message": "Deleted"}), 200
    except Exception as e:
        logger.exception("Error deleting history image")
        return jsonify({"error": f"An error occurred: {str(e)}"}), 500


@history_bp.route('/history/clear', methods=['POST'])
def history_clear():
    device_config = current_app.config['DEVICE_CONFIG']
    history_dir = device_config.history_image_dir
    try:
        count = 0
        for f in os.listdir(history_dir):
            p = os.path.join(history_dir, f)
            if os.path.isfile(p) and f.lower().endswith('.png'):
                os.remove(p)
                count += 1
        return jsonify({"success": True, "message": f"Cleared {count} images"}), 200
    except Exception as e:
        logger.exception("Error clearing history images")
        return jsonify({"error": f"An error occurred: {str(e)}"}), 500


