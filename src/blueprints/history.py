"""``/history`` routes: HTTP glue around :mod:`services.history`."""

import logging
from datetime import UTC, datetime
from typing import Any, cast

from flask import (
    Blueprint,
    Response,
    current_app,
    has_app_context,
    jsonify,
    render_template,
    request,
    send_from_directory,
)
from flask.typing import ResponseReturnValue
from werkzeug.exceptions import BadRequest

from services import history as history_files
from utils.api_responses import (
    JsonResponse,
    json_error,
    json_internal_error,
    json_success,
)
from utils.image_serving import THUMBNAIL_WIDTHS, maybe_serve_webp
from utils.time_utils import now_device_tz

logger = logging.getLogger(__name__)

history_bp = Blueprint("history", __name__)

# Sonar S1192 — duplicate string constants
_CONFIG_KEY = "DEVICE_CONFIG"
_ERR_INVALID_FILENAME = "invalid filename"
_ERR_INVALID_WIDTH = "invalid thumbnail width"
#: Width of the History grid thumbnails. The lightbox and download links
#: still use the full-size image.
_GRID_THUMB_WIDTH = 480
_ERR_FILE_NOT_FOUND = "File not found"
_ERR_INVALID_JSON = "Invalid JSON payload"
_ERR_BODY_NOT_OBJECT = "Request body must be a JSON object"
_ERR_FILENAME_REQUIRED = "filename is required"

# Helper return codes used in place of pre-built error responses so that
# taint-tracking (CodeQL py/reflective-xss) sees only module-level constant
# strings reaching ``json_error`` at call sites, never a value derived from
# the request body.
_ERRCODE_INVALID_JSON = "invalid_json"
_ERRCODE_BODY_NOT_OBJECT = "body_not_object"
_ERRCODE_FILENAME_REQUIRED = "filename_required"
_ERRCODE_INVALID_FILENAME = history_files.ERR_INVALID_FILENAME
_ERRCODE_FILE_NOT_FOUND = history_files.ERR_FILE_NOT_FOUND


def _filename_error_response(code: str) -> JsonResponse:
    """Map helper error codes to standard ``json_error`` responses.

    All messages are module-level constants — no request data is interpolated.
    """
    if code == _ERRCODE_INVALID_JSON:
        return json_error(_ERR_INVALID_JSON, status=400)
    if code == _ERRCODE_BODY_NOT_OBJECT:
        return json_error(_ERR_BODY_NOT_OBJECT, status=400)
    if code == _ERRCODE_FILENAME_REQUIRED:
        return json_error(_ERR_FILENAME_REQUIRED, status=400)
    if code == _ERRCODE_FILE_NOT_FOUND:
        return json_error(_ERR_FILE_NOT_FOUND, status=404)
    return json_error(_ERR_INVALID_FILENAME, status=400)


_DEFAULT_PER_PAGE = 24


def _now_in_device_tz() -> datetime:
    """Return "now" in the device timezone, falling back to UTC.

    Safe to call without an app context (falls back to UTC), which keeps
    it usable from unit tests that call it directly.
    """
    device_config = current_app.config.get(_CONFIG_KEY) if has_app_context() else None
    return now_device_tz(device_config)


def _parse_filename_from_request() -> tuple[str | None, str | None]:
    """Parse and validate a ``filename`` field from a JSON POST body.

    Returns ``(filename, None)`` on success, or ``(None, err_code)`` where
    ``err_code`` is one of the ``_ERRCODE_*`` sentinels.
    """
    try:
        data = request.get_json(force=True)
    except BadRequest:
        return None, _ERRCODE_INVALID_JSON
    if not isinstance(data, dict):
        return None, _ERRCODE_BODY_NOT_OBJECT
    filename = data.get("filename")
    if not isinstance(filename, str) or not filename.strip():
        return None, _ERRCODE_FILENAME_REQUIRED
    return filename, None


def _latest_metrics(device_config: Any) -> dict[str, Any]:
    """Per-stage latencies from the most recent refresh (None when absent)."""
    try:
        ri = device_config.get_refresh_info()
        return {
            "request_ms": getattr(ri, "request_ms", None),
            "generate_ms": getattr(ri, "generate_ms", None),
            "preprocess_ms": getattr(ri, "preprocess_ms", None),
            "display_ms": getattr(ri, "display_ms", None),
        }
    except Exception:
        return {
            "request_ms": None,
            "generate_ms": None,
            "preprocess_ms": None,
            "display_ms": None,
        }


def _panel_thumb_ratio(device_config: Any) -> str | None:
    """CSS aspect-ratio for exact-ratio thumbnails (History v2).

    The design's 5:3 fallback matches 800x480 panels; other resolutions get
    their own ratio via the --history-thumb-ratio custom property.
    """
    try:
        resolution = device_config.get_config("resolution")
        if (
            isinstance(resolution, (list, tuple))
            and len(resolution) == 2
            and all(isinstance(v, int) and v > 0 for v in resolution)
        ):
            return f"{resolution[0]} / {resolution[1]}"
    except Exception:
        return None
    return None


@history_bp.route("/history", methods=["GET"])
def history_page() -> Response | str:
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
    now = _now_in_device_tz()
    images, total = history_files.list_images(
        history_dir, offset=start, limit=per_page, now=now
    )
    total_pages = max(1, (total + per_page - 1) // per_page)

    # Clamp upper bound: ?page=99999 should render the last valid page rather
    # than "Page 99999 of N" over an empty grid.  When total == 0 we keep
    # page = 1 so the empty-state template still renders correctly.
    if page > total_pages:
        page = total_pages
        start = (page - 1) * per_page
        if total > 0:
            images, total = history_files.list_images(
                history_dir, offset=start, limit=per_page, now=now
            )

    template_ctx = {
        "images": images,
        "groups": history_files.group_by_day(images),
        "thumb_ratio": _panel_thumb_ratio(device_config),
        "thumb_width": _GRID_THUMB_WIDTH,
        "storage": history_files.storage_context(history_dir),
        "metrics": _latest_metrics(device_config),
        "page": page,
        "total_pages": total_pages,
        "total": total,
        "per_page": per_page,
        "active_nav": "history",
    }

    # HTMX partial: return only the grid fragment when requested via hx-get
    if request.headers.get("HX-Request") == "true":
        return render_template("partials/history_grid.html", **template_ctx)

    return render_template("history.html", **template_ctx)


@history_bp.route("/history/image/<path:filename>", methods=["GET"])
def history_image(filename: str) -> Response | JsonResponse:
    device_config = current_app.config[_CONFIG_KEY]
    history_dir = device_config.history_image_dir
    try:
        history_files.resolve_requested_path(history_dir, filename)
    except ValueError:
        return json_error(_ERR_INVALID_FILENAME, status=400)
    width: int | None = None
    raw_width = request.args.get("w")
    if raw_width is not None:
        if not raw_width.isdigit() or int(raw_width) not in THUMBNAIL_WIDTHS:
            return json_error(_ERR_INVALID_WIDTH, status=400)
        width = int(raw_width)
    if filename.lower().endswith(".png"):
        return maybe_serve_webp(
            history_dir, filename, request.headers.get("Accept"), width=width
        )
    return send_from_directory(history_dir, filename)


@history_bp.route("/history/redisplay", methods=["POST"])
def history_redisplay() -> ResponseReturnValue:
    device_config = current_app.config[_CONFIG_KEY]
    display_manager = current_app.config["DISPLAY_MANAGER"]
    refresh_task = current_app.config.get("REFRESH_TASK")
    history_dir = device_config.history_image_dir

    try:
        filename, err_code = _parse_filename_from_request()
        if err_code is not None:
            return _filename_error_response(err_code)

        if filename is None:
            return _filename_error_response(_ERRCODE_FILENAME_REQUIRED)
        _safe_path, err_code = history_files.find_entry(history_dir, filename)
        if err_code is not None:
            return _filename_error_response(err_code)

        safe_path = cast(str, _safe_path)
        if refresh_task is not None:
            # Serialise through the refresh loop so this panel write cannot
            # overlap a refresh the loop is already pushing to the display.
            refresh_task.run_display_command(
                "history_redisplay",
                lambda dm: dm.display_preprocessed_image(safe_path),
            )
        else:
            display_manager.display_preprocessed_image(safe_path)
        return json_success("Display updated")
    except Exception:
        logger.exception("Error redisplaying history image")
        return json_internal_error(
            "redisplay history image",
            details={"hint": "Verify filename exists in history and is readable."},
        )


@history_bp.route("/history/delete", methods=["POST"])
def history_delete() -> ResponseReturnValue:
    device_config = current_app.config[_CONFIG_KEY]
    history_dir = device_config.history_image_dir
    try:
        filename, err_code = _parse_filename_from_request()
        if err_code is not None:
            return _filename_error_response(err_code)

        if filename is None:
            return _filename_error_response(_ERRCODE_FILENAME_REQUIRED)
        safe_path, err_code = history_files.find_entry(history_dir, filename)
        if err_code is not None:
            return _filename_error_response(err_code)

        safe_path = cast(str, safe_path)
        if not history_files.is_deletable(safe_path):
            return json_error(
                "unsupported file type",
                status=400,
                details={"hint": "Only .png and .json history files may be deleted."},
            )
        history_files.delete_entry(history_dir, safe_path)
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
def history_clear() -> ResponseReturnValue:
    device_config = current_app.config[_CONFIG_KEY]
    history_dir = device_config.history_image_dir
    try:
        count = history_files.clear(history_dir)
        return json_success(f"Cleared {count} images")
    except Exception:
        logger.exception("Error clearing history images")
        return json_internal_error(
            "clear history",
            details={"hint": "Check history directory permissions."},
        )


@history_bp.route("/history/export.csv", methods=["GET"])
def history_export_csv() -> Response:
    """Return all history entries as a downloadable CSV file.

    Columns: timestamp, plugin_id, instance_name, status, duration_ms,
    error_message.
    """
    device_config = current_app.config[_CONFIG_KEY]
    history_dir = device_config.history_image_dir

    date_str = datetime.now(tz=UTC).strftime("%Y%m%d")
    filename = f"inkypi-history-{date_str}.csv"

    return Response(
        history_files.iter_csv(history_dir),
        status=200,
        mimetype="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


@history_bp.route("/history/storage", methods=["GET"])
def history_storage() -> ResponseReturnValue:
    """Return storage stats for the filesystem containing the history directory.

    Values returned: free_gb, total_gb, used_gb, pct_free
    """
    device_config = current_app.config[_CONFIG_KEY]
    history_dir = device_config.history_image_dir
    try:
        return jsonify(history_files.storage_summary(history_dir)), 200
    except Exception:
        logger.exception("Failed to stat filesystem for history directory")
        return cast(
            tuple[Any, int], json_error("failed to get storage info", status=500)
        )
