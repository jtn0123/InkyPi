import csv
import io
import json
import logging
import os
import shutil
from datetime import UTC, datetime

from flask import (
    Blueprint,
    Response,
    current_app,
    jsonify,
    render_template,
    request,
    send_from_directory,
)
from werkzeug.exceptions import BadRequest

from utils.http_utils import json_error, json_internal_error, json_success
from utils.image_serving import maybe_serve_webp
from utils.security_utils import validate_file_path
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
    """Resolve a requested filename under history_dir and enforce containment.

    Uses :func:`utils.security_utils.validate_file_path`, which resolves both
    the candidate and the allowed directory via ``os.path.realpath`` and
    rejects any path that escapes the allowed directory (including traversal
    attempts using ``..`` or absolute paths, and symlink-based escapes).

    A :class:`ValueError` is raised on rejection.  Callers that also need to
    reject embedded NUL bytes should do so before calling this helper; we
    defensively raise here too since ``os.path`` behaviour on NUL varies.
    """
    if not isinstance(filename, str) or "\x00" in filename:
        raise ValueError(_ERR_INVALID_FILENAME)
    # Reject absolute paths up-front — joining them with ``history_dir``
    # silently drops the base on POSIX, which would mask traversal intent.
    if os.path.isabs(filename):
        raise ValueError(_ERR_INVALID_FILENAME)
    candidate = os.path.join(history_dir, filename)
    try:
        return validate_file_path(candidate, history_dir)
    except ValueError as exc:
        raise ValueError(_ERR_INVALID_FILENAME) from exc


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

    # Clamp upper bound: ?page=99999 should render the last valid page rather
    # than "Page 99999 of N" over an empty grid.  When total == 0 we keep
    # page = 1 so the empty-state template still renders correctly.
    if page > total_pages:
        page = total_pages
        start = (page - 1) * per_page
        if total > 0:
            images, total = _list_history_images(
                history_dir, offset=start, limit=per_page
            )

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

    template_ctx = {
        "images": images,
        "storage": storage_ctx,
        "metrics": metrics,
        "page": page,
        "total_pages": total_pages,
        "total": total,
        "per_page": per_page,
    }

    # HTMX partial: return only the grid fragment when requested via hx-get
    if request.headers.get("HX-Request") == "true":
        return render_template("partials/history_grid.html", **template_ctx)

    return render_template("history.html", **template_ctx)


@history_bp.route("/history/image/<path:filename>", methods=["GET"])
def history_image(filename: str):
    device_config = current_app.config[_CONFIG_KEY]
    history_dir = device_config.history_image_dir
    try:
        _resolve_history_path(history_dir, filename)
    except ValueError:
        return json_error(_ERR_INVALID_FILENAME, status=400)
    if filename.lower().endswith(".png"):
        return maybe_serve_webp(history_dir, filename, request.headers.get("Accept"))
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

        _base, ext = os.path.splitext(safe_path)
        if not ext.lower().endswith((_EXT_PNG, _EXT_JSON)):
            return json_error(
                "unsupported file type",
                status=400,
                details={"hint": "Only .png and .json history files may be deleted."},
            )

        os.remove(safe_path)
        # Remove matching sidecar on png/json deletions.  Re-derive the
        # sidecar filename from the *validated* primary filename (via the
        # containment-checking helper) so CodeQL sees a re-validated path
        # rather than one derived from raw user input.
        primary_stem, _primary_ext = os.path.splitext(os.path.basename(filename))
        sidecar_ext = _EXT_JSON if ext.lower() == _EXT_PNG else _EXT_PNG
        try:
            sidecar_safe = _resolve_history_path(
                history_dir, f"{primary_stem}{sidecar_ext}"
            )
        except ValueError:
            sidecar_safe = None
        if sidecar_safe is not None and os.path.isfile(sidecar_safe):
            os.remove(sidecar_safe)
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


_CSV_HEADERS = [
    "timestamp",
    "plugin_id",
    "instance_name",
    "status",
    "duration_ms",
    "error_message",
]


def _iter_history_csv(history_dir: str):
    """Yield CSV rows (as bytes) for every history entry, newest first.

    Each PNG in *history_dir* produces one row.  The sidecar JSON is read for
    metadata; missing fields default to an empty string.
    """
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(_CSV_HEADERS)
    buf.seek(0)
    yield buf.getvalue().encode("utf-8")

    try:
        files = [
            f
            for f in os.listdir(history_dir)
            if os.path.isfile(os.path.join(history_dir, f))
            and f.lower().endswith(_EXT_PNG)
        ]
    except Exception:
        logger.exception("CSV export: failed to list history directory")
        return

    # Sort newest first (mirrors _list_history_images ordering)
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

    for f in files:
        full_path = os.path.join(history_dir, f)
        try:
            mtime = os.path.getmtime(full_path)
        except Exception:
            continue

        meta: dict = {}
        try:
            base, _ = os.path.splitext(f)
            sidecar_path = os.path.join(history_dir, f"{base}{_EXT_JSON}")
            if os.path.exists(sidecar_path):
                with open(sidecar_path, encoding="utf-8") as fh:
                    meta = json.load(fh) or {}
        except Exception:
            meta = {}

        # Prefer the ISO timestamp stored in the sidecar; fall back to mtime.
        timestamp = (
            meta.get("refresh_time")
            or datetime.fromtimestamp(mtime, tz=UTC).isoformat()
        )

        row = [
            timestamp,
            meta.get("plugin_id", ""),
            meta.get("plugin_instance", ""),
            meta.get("status", ""),
            meta.get("duration_ms", ""),
            meta.get("error_message", ""),
        ]

        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(row)
        buf.seek(0)
        yield buf.getvalue().encode("utf-8")


@history_bp.route("/history/export.csv", methods=["GET"])
def history_export_csv():
    """Return all history entries as a downloadable CSV file.

    Columns: timestamp, plugin_id, instance_name, status, duration_ms,
    error_message.
    """
    device_config = current_app.config[_CONFIG_KEY]
    history_dir = device_config.history_image_dir

    date_str = datetime.now(tz=UTC).strftime("%Y%m%d")
    filename = f"inkypi-history-{date_str}.csv"

    return Response(
        _iter_history_csv(history_dir),
        status=200,
        mimetype="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
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
