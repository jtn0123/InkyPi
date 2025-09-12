import logging
import os
from datetime import datetime

from flask import (
    Blueprint,
    current_app,
    jsonify,
    render_template,
    request,
    send_from_directory,
)

from utils.http_utils import json_error, json_internal_error
from utils.time_utils import now_device_tz, get_timezone

logger = logging.getLogger(__name__)

history_bp = Blueprint("history", __name__)


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


def _list_history_images(history_dir: str) -> list[dict]:
    try:
        files = [
            f
            for f in os.listdir(history_dir)
            if os.path.isfile(os.path.join(history_dir, f))
            and f.lower().endswith(".png")
        ]
    except Exception:
        logger.exception("Failed to list history directory")
        files = []

    # Sort by modification time descending; skip files that disappear or are inaccessible
    def _safe_mtime(path: str) -> float:
        try:
            return os.path.getmtime(path)
        except Exception:
            return 0.0

    files.sort(
        key=lambda f: (_safe_mtime(os.path.join(history_dir, f)), f),
        reverse=True,
    )
    result: list[dict] = []
    for f in files:
        full_path = os.path.join(history_dir, f)
        try:
            mtime = os.path.getmtime(full_path)
            size = os.path.getsize(full_path)
        except Exception:
            # Skip files that were deleted or cannot be accessed
            continue
        # Try to load sidecar metadata (JSON) if present
        meta: dict = {}
        try:
            base, _ = os.path.splitext(f)
            sidecar_path = os.path.join(history_dir, f"{base}.json")
            if os.path.exists(sidecar_path):
                import json
                with open(sidecar_path, "r", encoding="utf-8") as fh:
                    meta = json.load(fh) or {}
        except Exception:
            # Non-fatal; ignore malformed sidecar
            meta = {}
        try:
            # Use device timezone for display
            device_config = current_app.config.get("DEVICE_CONFIG")
            now = now_device_tz(device_config) if device_config else datetime.now(tz=get_timezone("UTC"))
            dt = datetime.fromtimestamp(mtime, tz=now.tzinfo)
        except Exception:
            dt = datetime.fromtimestamp(mtime)
        result.append(
            {
                "filename": f,
                "mtime": mtime,
                "mtime_str": dt.strftime("%b %d, %Y %I:%M %p")
                .lstrip("0")
                .replace(" 0", " "),
                "size": size,
                "size_str": _format_size(size),
                "meta": meta,
            }
        )
    return result


@history_bp.route("/history")
def history_page():
    device_config = current_app.config["DEVICE_CONFIG"]
    history_dir = device_config.history_image_dir
    images = _list_history_images(history_dir)
    # Pull latest timing metrics if available
    try:
        ri = device_config.get_refresh_info()
        metrics = {
            "request_ms": getattr(ri, "request_ms", None),
            "generate_ms": getattr(ri, "generate_ms", None),
            "preprocess_ms": getattr(ri, "preprocess_ms", None),
            "display_ms": getattr(ri, "display_ms", None),
        }
    except Exception:
        metrics = {"request_ms": None, "generate_ms": None, "preprocess_ms": None, "display_ms": None}
    # Compute storage usage for the history directory's filesystem
    free_bytes = None
    total_bytes = None
    used_bytes = None
    pct_free = None
    try:
        import shutil

        usage = shutil.disk_usage(history_dir)
        total_bytes = int(usage.total)
        free_bytes = int(usage.free)
        used_bytes = int(usage.used)
        pct_free = (
            (free_bytes / total_bytes * 100.0)
            if (total_bytes and total_bytes > 0)
            else None
        )
    except Exception:
        logger.exception("Failed to stat filesystem for history directory")

    gb = 1024**3
    storage_ctx = {
        "free_bytes": free_bytes,
        "total_bytes": total_bytes,
        "used_bytes": used_bytes,
        "pct_free": pct_free,
        "free_gb": round(free_bytes / gb, 2) if free_bytes is not None else None,
        "total_gb": round(total_bytes / gb, 2) if total_bytes is not None else None,
        "used_gb": round(used_bytes / gb, 2) if used_bytes is not None else None,
    }

    return render_template("history.html", images=images, storage=storage_ctx, metrics=metrics)


@history_bp.route("/history/image/<path:filename>")
def history_image(filename: str):
    device_config = current_app.config["DEVICE_CONFIG"]
    history_dir = device_config.history_image_dir
    return send_from_directory(history_dir, filename)


@history_bp.route("/history/redisplay", methods=["POST"])
def history_redisplay():
    device_config = current_app.config["DEVICE_CONFIG"]
    display_manager = current_app.config["DISPLAY_MANAGER"]
    history_dir = device_config.history_image_dir

    try:
        data = request.get_json(force=True)
        filename = (data or {}).get("filename")
        if not filename:
            return json_error("filename is required", status=400)

        # Prevent path traversal; only allow files within the history dir
        safe_path = os.path.normpath(os.path.join(history_dir, filename))
        if not safe_path.startswith(os.path.abspath(history_dir)):
            return json_error("invalid filename", status=400)
        if not os.path.exists(safe_path):
            return json_error("file not found", status=404)

        display_manager.display_preprocessed_image(safe_path)
        return jsonify({"success": True, "message": "Display updated"}), 200
    except Exception:
        logger.exception("Error redisplaying history image")
        return json_internal_error(
            "redisplay history image",
            details={"hint": "Verify filename exists in history and is readable."},
        )


@history_bp.route("/history/delete", methods=["POST"])
def history_delete():
    device_config = current_app.config["DEVICE_CONFIG"]
    history_dir = device_config.history_image_dir
    try:
        data = request.get_json(force=True) or {}
        filename = data.get("filename")
        if not filename:
            return json_error("filename is required", status=400)
        safe_path = os.path.normpath(os.path.join(history_dir, filename))
        if not safe_path.startswith(os.path.abspath(history_dir)):
            return json_error("invalid filename", status=400)
        if os.path.exists(safe_path):
            os.remove(safe_path)
        return jsonify({"success": True, "message": "Deleted"}), 200
    except Exception:
        logger.exception("Error deleting history image")
        return json_internal_error(
            "delete history image",
            details={
                "hint": "Confirm filename is within history directory and file permissions allow deletion.",
            },
        )


@history_bp.route("/history/clear", methods=["POST"])
def history_clear():
    device_config = current_app.config["DEVICE_CONFIG"]
    history_dir = device_config.history_image_dir
    try:
        count = 0
        for f in os.listdir(history_dir):
            p = os.path.join(history_dir, f)
            if os.path.isfile(p) and f.lower().endswith(".png"):
                os.remove(p)
                count += 1
        return jsonify({"success": True, "message": f"Cleared {count} images"}), 200
    except Exception:
        logger.exception("Error clearing history images")
        return json_error("An error occurred", status=500)


@history_bp.route("/history/storage")
def history_storage():
    """Return storage stats for the filesystem containing the history directory.

    Values returned: free_gb, total_gb, used_gb, pct_free
    """
    device_config = current_app.config["DEVICE_CONFIG"]
    history_dir = device_config.history_image_dir
    try:
        import shutil

        usage = shutil.disk_usage(history_dir)
        total_bytes = int(usage.total)
        free_bytes = int(usage.free)
        used_bytes = int(usage.used)
        pct_free = (
            (free_bytes / total_bytes * 100.0)
            if (total_bytes and total_bytes > 0)
            else None
        )

        gb = 1024**3
        return (
            jsonify(
                {
                    "free_gb": round(free_bytes / gb, 2),
                    "total_gb": round(total_bytes / gb, 2),
                    "used_gb": round(used_bytes / gb, 2),
                    "pct_free": round(pct_free, 2) if pct_free is not None else None,
                }
            ),
            200,
        )
    except Exception:
        logger.exception("Failed to stat filesystem for history directory")
        return json_error("failed to get storage info", status=500)
