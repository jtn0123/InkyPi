import json
import logging
import os
import shutil
from datetime import datetime

from flask import (
    Blueprint,
    current_app,
    jsonify,
    render_template,
    request,
    send_from_directory,
)

from utils.http_utils import json_error, json_internal_error, json_success
from utils.time_utils import get_timezone, now_device_tz

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
                with open(sidecar_path, encoding="utf-8") as fh:
                    meta = json.load(fh) or {}
        except Exception:
            # Non-fatal; ignore malformed sidecar
            meta = {}
        try:
            # Use device timezone for display
            device_config = current_app.config.get("DEVICE_CONFIG")
            now = (
                now_device_tz(device_config)
                if device_config
                else datetime.now(tz=get_timezone("UTC"))
            )
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


def _resolve_history_path(history_dir: str, filename: str) -> str:
    """Resolve a requested filename under history_dir and enforce containment."""
    base_dir = os.path.abspath(history_dir)
    candidate = os.path.abspath(os.path.join(base_dir, filename))
    if os.path.commonpath([base_dir, candidate]) != base_dir:
        raise ValueError("invalid filename")
    return candidate


_DEFAULT_PER_PAGE = 24


@history_bp.route("/history")
def history_page():
    device_config = current_app.config["DEVICE_CONFIG"]
    history_dir = device_config.history_image_dir
    all_images = _list_history_images(history_dir)
    total = len(all_images)

    # Pagination
    try:
        page = max(1, int(request.args.get("page", 1)))
    except (ValueError, TypeError):
        page = 1
    try:
        per_page = max(
            1, min(120, int(request.args.get("per_page", _DEFAULT_PER_PAGE)))
        )
    except (ValueError, TypeError):
        per_page = _DEFAULT_PER_PAGE

    start = (page - 1) * per_page
    images = all_images[start : start + per_page]
    total_pages = max(1, (total + per_page - 1) // per_page)

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
        metrics = {
            "request_ms": None,
            "generate_ms": None,
            "preprocess_ms": None,
            "display_ms": None,
        }
    # Compute storage usage for the history directory's filesystem
    free_bytes = None
    total_bytes = None
    used_bytes = None
    pct_free = None
    try:
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

    return render_template(
        "history.html",
        images=images,
        storage=storage_ctx,
        metrics=metrics,
        page=page,
        total_pages=total_pages,
        total=total,
        per_page=per_page,
    )


@history_bp.route("/history/image/<path:filename>")
def history_image(filename: str):
    device_config = current_app.config["DEVICE_CONFIG"]
    history_dir = device_config.history_image_dir
    try:
        _resolve_history_path(history_dir, filename)
    except ValueError:
        return json_error("invalid filename", status=400)
    return send_from_directory(history_dir, filename)


@history_bp.route("/history/redisplay", methods=["POST"])
def history_redisplay():
    device_config = current_app.config["DEVICE_CONFIG"]
    display_manager = current_app.config["DISPLAY_MANAGER"]
    history_dir = device_config.history_image_dir

    try:
        data = request.get_json(force=True)
        if not isinstance(data, dict):
            return json_error("Request body must be a JSON object", status=400)
        filename = data.get("filename")
        if not isinstance(filename, str) or not filename.strip():
            return json_error("filename is required", status=400)

        # Prevent path traversal; only allow files within the history dir
        try:
            safe_path = _resolve_history_path(history_dir, filename)
        except ValueError:
            return json_error("invalid filename", status=400)
        if not os.path.exists(safe_path):
            return json_error("file not found", status=404)

        display_manager.display_preprocessed_image(safe_path)
        return json_success("Display updated")
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
        data = request.get_json(force=True)
        if not isinstance(data, dict):
            return json_error("Request body must be a JSON object", status=400)
        filename = data.get("filename")
        if not isinstance(filename, str) or not filename.strip():
            return json_error("filename is required", status=400)
        try:
            safe_path = _resolve_history_path(history_dir, filename)
        except ValueError:
            return json_error("invalid filename", status=400)
        if os.path.exists(safe_path):
            os.remove(safe_path)
            # Remove matching sidecar on png/json deletions.
            base, ext = os.path.splitext(safe_path)
            if ext.lower() == ".png":
                sidecar = f"{base}.json"
                if os.path.exists(sidecar):
                    os.remove(sidecar)
            elif ext.lower() == ".json":
                sidecar = f"{base}.png"
                if os.path.exists(sidecar):
                    os.remove(sidecar)
        return json_success("Deleted")
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
            if os.path.isfile(p) and f.lower().endswith((".png", ".json")):
                os.remove(p)
                count += 1
        return json_success(f"Cleared {count} images")
    except Exception:
        logger.exception("Error clearing history images")
        return json_internal_error(
            "clear history",
            details={"hint": "Check history directory permissions."},
        )


@history_bp.route("/history/storage")
def history_storage():
    """Return storage stats for the filesystem containing the history directory.

    Values returned: free_gb, total_gb, used_gb, pct_free
    """
    device_config = current_app.config["DEVICE_CONFIG"]
    history_dir = device_config.history_image_dir
    try:
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
