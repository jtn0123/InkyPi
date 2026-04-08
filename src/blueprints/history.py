import json
import logging
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path

from flask import (
    Blueprint,
    current_app,
    jsonify,
    render_template,
    request,
    send_from_directory,
)
from werkzeug.exceptions import BadRequest

from utils.http_utils import json_error, json_internal_error, json_success
from utils.image_serving import maybe_serve_webp
from utils.time_utils import get_timezone, now_device_tz

logger = logging.getLogger(__name__)

history_bp = Blueprint("history", __name__)

# Sonar S1192 — duplicate string constants
_CONFIG_KEY = "DEVICE_CONFIG"
_ERR_INVALID_FILENAME = "invalid filename"
_EXT_PNG = ".png"
_EXT_JSON = ".json"


def _timestamp_from_history_filename(filename: str) -> float:
    """Extract an epoch timestamp from display_YYYYMMDD_HHMMSS-style filenames."""
    stem, _ext = os.path.splitext(filename)
    parts = stem.split("_")
    if len(parts) < 3:
        return 0.0
    try:
        dt = datetime.strptime(f"{parts[-2]}_{parts[-1]}", "%Y%m%d_%H%M%S")
    except ValueError:
        return 0.0
    return dt.replace(tzinfo=UTC).timestamp()


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


def _list_history_images(
    history_dir: str, offset: int = 0, limit: int | None = None
) -> tuple[list[dict], int]:
    # Phase 1: cheap directory listing + sort
    try:
        files = [
            f
            for f in os.listdir(history_dir)
            if os.path.isfile(os.path.join(history_dir, f))
            and f.lower().endswith(_EXT_PNG)
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
        key=lambda f: (
            _safe_mtime(os.path.join(history_dir, f)),
            _timestamp_from_history_filename(f),
            f,
        ),
        reverse=True,
    )

    total = len(files)

    # Slice to requested page before doing expensive per-file work
    page_files = files[offset : offset + limit] if limit is not None else files

    # Phase 2: expensive stat + sidecar load only for the page slice
    result: list[dict] = []
    for f in page_files:
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
            sidecar_path = os.path.join(history_dir, f"{base}{_EXT_JSON}")
            if os.path.exists(sidecar_path):
                with open(sidecar_path, encoding="utf-8") as fh:
                    meta = json.load(fh) or {}
        except Exception:
            # Non-fatal; ignore malformed sidecar
            meta = {}
        try:
            # Use device timezone for display
            device_config = current_app.config.get(_CONFIG_KEY)
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
    return result, total


def _resolve_history_path(history_dir: str, filename: str) -> str:
    """Resolve a requested filename under history_dir and enforce containment."""
    base_dir = os.path.abspath(history_dir)
    candidate = os.path.abspath(os.path.join(base_dir, filename))
    if os.path.commonpath([base_dir, candidate]) != base_dir:
        raise ValueError(_ERR_INVALID_FILENAME)
    return candidate


def _validate_and_resolve_history_file(history_dir, filename):
    """Validate and resolve a history filename to a safe absolute path.

    Returns ``(safe_path, None)`` on success, or ``(None, error_response)`` when
    the filename is invalid or the resolved file does not exist.  Callers should
    check the second element before using the first.
    """
    try:
        safe_path = _resolve_history_path(history_dir, filename)
    except ValueError:
        return None, json_error(_ERR_INVALID_FILENAME, status=400)
    if not os.path.isfile(safe_path):
        return None, json_error("File not found", status=404)
    return safe_path, None


def _parse_filename_from_request():
    """Parse and validate a ``filename`` field from a JSON POST body.

    Returns ``(filename, None)`` on success, or ``(None, error_response)``
    when the payload is malformed or the filename is missing/empty.
    """
    try:
        data = request.get_json(force=True)
    except BadRequest:
        return None, json_error("Invalid JSON payload", status=400)
    if not isinstance(data, dict):
        return None, json_error("Request body must be a JSON object", status=400)
    filename = data.get("filename")
    if not isinstance(filename, str) or not filename.strip():
        return None, json_error("filename is required", status=400)
    return filename, None


_DEFAULT_PER_PAGE = 24


@history_bp.route("/history", methods=["GET"])
def history_page():
    device_config = current_app.config[_CONFIG_KEY]
    history_dir = device_config.history_image_dir

    # Parse pagination parameters BEFORE listing so we can push them down
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
    images, total = _list_history_images(history_dir, offset=start, limit=per_page)
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


@history_bp.route("/history/image/<path:filename>", methods=["GET"])
def history_image(filename: str):
    device_config = current_app.config[_CONFIG_KEY]
    history_dir = device_config.history_image_dir
    try:
        resolved = _resolve_history_path(history_dir, filename)
    except ValueError:
        return json_error(_ERR_INVALID_FILENAME, status=400)
    if filename.lower().endswith(".png"):
        return maybe_serve_webp(
            Path(resolved),
            request.headers.get("Accept"),
            safe_root=history_dir,
        )
    return send_from_directory(history_dir, filename)


@history_bp.route("/history/redisplay", methods=["POST"])
def history_redisplay():
    device_config = current_app.config[_CONFIG_KEY]
    display_manager = current_app.config["DISPLAY_MANAGER"]
    history_dir = device_config.history_image_dir

    try:
        filename, err = _parse_filename_from_request()
        if err is not None:
            return err

        safe_path, err = _validate_and_resolve_history_file(history_dir, filename)
        if err is not None:
            return err

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
    device_config = current_app.config[_CONFIG_KEY]
    history_dir = device_config.history_image_dir
    try:
        filename, err = _parse_filename_from_request()
        if err is not None:
            return err

        safe_path, err = _validate_and_resolve_history_file(history_dir, filename)
        if err is not None:
            return err

        base, ext = os.path.splitext(safe_path)
        if not ext.lower().endswith((_EXT_PNG, _EXT_JSON)):
            return json_error(
                "unsupported file type",
                status=400,
                details={"hint": "Only .png and .json history files may be deleted."},
            )

        os.remove(safe_path)
        # Remove matching sidecar on png/json deletions.
        if ext.lower() == _EXT_PNG:
            sidecar = f"{base}{_EXT_JSON}"
            if os.path.exists(sidecar):
                os.remove(sidecar)
        elif ext.lower() == _EXT_JSON:
            sidecar = f"{base}{_EXT_PNG}"
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
    device_config = current_app.config[_CONFIG_KEY]
    history_dir = device_config.history_image_dir
    try:
        count = 0
        for f in os.listdir(history_dir):
            p = os.path.join(history_dir, f)
            if os.path.isfile(p) and f.lower().endswith((_EXT_PNG, _EXT_JSON)):
                os.remove(p)
                count += 1
        return json_success(f"Cleared {count} images")
    except Exception:
        logger.exception("Error clearing history images")
        return json_internal_error(
            "clear history",
            details={"hint": "Check history directory permissions."},
        )


@history_bp.route("/history/storage", methods=["GET"])
def history_storage():
    """Return storage stats for the filesystem containing the history directory.

    Values returned: free_gb, total_gb, used_gb, pct_free
    """
    device_config = current_app.config[_CONFIG_KEY]
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
