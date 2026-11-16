"""Display history files: listing, lookup, deletion, CSV export and disk use.

The history directory holds one PNG per frame the display showed, each with an
optional JSON sidecar of metadata (plugin, instance, refresh time). The
``/history`` routes are HTTP glue around these functions; nothing here needs a
request or app context.

Filenames that arrive in a request are never joined into a path and removed
directly. :func:`find_entry` checks the name, then returns the path of the
matching entry from ``os.listdir`` after a containment check, so every
``os.remove`` gets a path that came from the directory listing.
"""

import csv
import io
import json
import logging
import os
import shutil
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime

from utils.form_utils import sanitize_log_field
from utils.json_types import JsonObject
from utils.security_utils import validate_file_path

logger = logging.getLogger(__name__)

EXT_PNG = ".png"
EXT_JSON = ".json"

# Why :func:`find_entry` refused a filename. Module constants, so a route can
# map them to fixed messages without echoing request data.
ERR_INVALID_FILENAME = "invalid_filename"
ERR_FILE_NOT_FOUND = "file_not_found"
_INVALID_FILENAME_MSG = "invalid filename"

CSV_HEADERS = [
    "timestamp",
    "plugin_id",
    "instance_name",
    "status",
    "duration_ms",
    "error_message",
]


def _timestamp_from_filename(filename: str) -> float:
    """Extract an epoch timestamp from display_YYYYMMDD_HHMMSS-style filenames."""
    stem, _ext = os.path.splitext(filename)
    parts = stem.split("_")
    if len(parts) < 3:
        return 0.0
    try:
        dt = datetime.strptime(f"{parts[-2]}_{parts[-1]}", "%Y%m%d_%H%M%S").replace(
            tzinfo=UTC
        )
    except ValueError:
        return 0.0
    return dt.timestamp()


def format_size(num_bytes: int) -> str:
    size: float = float(num_bytes)
    try:
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if size < 1024.0:
                return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} {unit}"
            size /= 1024.0
        return f"{size:.1f} PB"
    except Exception:
        return "-"


def day_label(dt: datetime, now: datetime) -> str:
    """Human day-group label: Today, Yesterday, or a formatted date."""
    delta_days = (now.date() - dt.date()).days
    if delta_days == 0:
        return "Today"
    if delta_days == 1:
        return "Yesterday"
    return dt.strftime("%b %d, %Y").replace(" 0", " ")


def _safe_mtime(path: str) -> float:
    try:
        return os.path.getmtime(path)
    except Exception:
        return 0.0


def _sorted_pngs(history_dir: str) -> list[str]:
    """Every PNG in *history_dir*, newest first. Raises if it can't be listed."""
    files = [
        f
        for f in os.listdir(history_dir)
        if os.path.isfile(os.path.join(history_dir, f)) and f.lower().endswith(EXT_PNG)
    ]
    files.sort(
        key=lambda f: (
            _safe_mtime(os.path.join(history_dir, f)),
            _timestamp_from_filename(f),
            f,
        ),
        reverse=True,
    )
    return files


def _load_sidecar(history_dir: str, png_name: str) -> JsonObject:
    """The JSON metadata saved next to *png_name*, or {} if missing or bad."""
    try:
        base, _ = os.path.splitext(png_name)
        sidecar_path = os.path.join(history_dir, f"{base}{EXT_JSON}")
        if os.path.exists(sidecar_path):
            with open(sidecar_path, encoding="utf-8") as fh:
                meta = json.load(fh)
            if isinstance(meta, dict):
                return meta
    except Exception:
        # Non-fatal; ignore malformed sidecar
        pass
    return {}


def list_images(
    history_dir: str,
    offset: int = 0,
    limit: int | None = None,
    *,
    now: datetime | None = None,
) -> tuple[list[JsonObject], int]:
    """One page of history entries, newest first, and the total count.

    *now* (in the device timezone) sets the timezone the times are shown in
    and the Today/Yesterday labels; it defaults to UTC.
    """
    # Phase 1: cheap directory listing + sort
    try:
        files = _sorted_pngs(history_dir)
    except Exception:
        logger.exception("Failed to list history directory")
        files = []

    total = len(files)

    # Slice to requested page before doing expensive per-file work
    page_files = files[offset : offset + limit] if limit is not None else files

    # Phase 2: expensive stat + sidecar load only for the page slice
    if now is None:
        now = datetime.now(UTC)
    result: list[JsonObject] = []
    for f in page_files:
        full_path = os.path.join(history_dir, f)
        try:
            mtime = os.path.getmtime(full_path)
            size = os.path.getsize(full_path)
        except Exception:
            # Skip files that were deleted or cannot be accessed
            continue
        meta = _load_sidecar(history_dir, f)
        try:
            # Use device timezone for display
            dt = datetime.fromtimestamp(mtime, tz=now.tzinfo)
        except Exception:
            dt = datetime.fromtimestamp(mtime, tz=UTC)
        result.append(
            {
                "filename": f,
                "mtime": mtime,
                "mtime_str": dt.strftime("%b %d, %Y %I:%M %p")
                .lstrip("0")
                .replace(" 0", " "),
                "size": size,
                "size_str": format_size(size),
                "meta": meta,
                # Day-grouping + source-filter fields (History v2)
                "date_key": dt.strftime("%Y-%m-%d"),
                "day_label": day_label(dt, now),
                "category": (
                    "playlist" if meta.get("refresh_type") == "Playlist" else "manual"
                ),
            }
        )
    return result, total


def group_by_day(images: list[JsonObject]) -> list[JsonObject]:
    """Group a newest-first image list into consecutive same-day buckets.

    Images arrive sorted by mtime descending, so consecutive grouping keeps
    that order while producing one section per calendar day.
    """
    groups: list[JsonObject] = []
    for img in images:
        if not groups or groups[-1]["date_key"] != img["date_key"]:
            groups.append(
                {
                    "date_key": img["date_key"],
                    "label": img["day_label"],
                    "entries": [],
                }
            )
        groups[-1]["entries"].append(img)
    return groups


def resolve_entry_path(history_dir: str, expected_name: str) -> str | None:
    """Return the real path for *expected_name* if it exists in *history_dir*.

    The lookup only considers entries that come from ``os.listdir`` and then
    performs a containment check against the resolved history directory.  That
    keeps downstream filesystem operations from reconstructing paths directly
    from request data.
    """
    try:
        entries = os.listdir(history_dir)
    except OSError:
        return None

    real_history_dir = os.path.realpath(history_dir)
    for entry in entries:
        if entry != expected_name:
            continue
        full = os.path.join(history_dir, entry)
        try:
            real_full = os.path.realpath(full)
        except OSError:
            return None
        try:
            common = os.path.commonpath([real_history_dir, real_full])
        except ValueError:
            return None
        if common != real_history_dir:
            return None
        if os.path.isfile(real_full):
            return real_full
        return None
    return None


def remove_entry_by_name(history_dir: str, expected_name: str) -> None:
    """Delete a history entry by basename after resolving it safely."""
    real_full = resolve_entry_path(history_dir, expected_name)
    if real_full is None:
        return
    os.remove(real_full)


def resolve_requested_path(history_dir: str, filename: str) -> str:
    """Resolve a requested filename under history_dir and enforce containment.

    Uses :func:`utils.security_utils.validate_file_path`, which resolves both
    the candidate and the allowed directory via ``os.path.realpath`` and
    rejects any path that escapes the allowed directory (including traversal
    attempts using ``..`` or absolute paths, and symlink-based escapes).

    A :class:`ValueError` is raised on rejection, including for embedded NUL
    bytes, since ``os.path`` behaviour on NUL varies.
    """
    if "\x00" in filename:
        raise ValueError(_INVALID_FILENAME_MSG)
    # Reject absolute paths up-front — joining them with ``history_dir``
    # silently drops the base on POSIX, which would mask traversal intent.
    if os.path.isabs(filename):
        raise ValueError(_INVALID_FILENAME_MSG)
    # Accept only plain filenames (no directory components).
    if os.path.basename(filename) != filename:
        raise ValueError(_INVALID_FILENAME_MSG)
    if filename in {".", ".."}:
        raise ValueError(_INVALID_FILENAME_MSG)
    candidate = os.path.join(history_dir, filename)
    try:
        return validate_file_path(candidate, history_dir)
    except ValueError as exc:
        raise ValueError(_INVALID_FILENAME_MSG) from exc


def find_entry(history_dir: str, filename: str) -> tuple[str | None, str | None]:
    """Validate and resolve a requested history filename to a safe path.

    Returns ``(safe_path, None)`` on success, or ``(None, err_code)`` where
    ``err_code`` is :data:`ERR_INVALID_FILENAME` or :data:`ERR_FILE_NOT_FOUND`.
    """
    try:
        resolve_requested_path(history_dir, filename)
    except ValueError:
        logger.warning(
            "history: invalid filename rejected filename=%s",
            sanitize_log_field(filename),
        )
        return None, ERR_INVALID_FILENAME
    safe_path = resolve_entry_path(history_dir, filename)
    if safe_path is None:
        logger.warning(
            "history: file not found filename=%s",
            sanitize_log_field(filename),
        )
        return None, ERR_FILE_NOT_FOUND
    return safe_path, None


def is_deletable(safe_path: str) -> bool:
    """Only the history's own PNG and JSON files may be deleted."""
    _base, ext = os.path.splitext(safe_path)
    return ext.lower().endswith((EXT_PNG, EXT_JSON))


def delete_entry(history_dir: str, safe_path: str) -> None:
    """Delete *safe_path* (from :func:`find_entry`) and its partner file.

    Deleting a PNG removes its JSON sidecar and the other way round. The
    partner is found by enumerating the directory rather than building a path
    from the requested name, so the value passed to ``os.remove`` comes from
    ``os.listdir`` (which is not user-controlled) and CodeQL cannot
    taint-track it back to the request body.
    """
    os.remove(safe_path)
    stem, ext = os.path.splitext(os.path.basename(safe_path))
    partner_ext = EXT_JSON if ext.lower() == EXT_PNG else EXT_PNG
    remove_entry_by_name(history_dir, stem + partner_ext)


def clear(history_dir: str) -> int:
    """Delete every history PNG and JSON file; return how many were removed."""
    count = 0
    for f in os.listdir(history_dir):
        p = os.path.join(history_dir, f)
        if os.path.isfile(p) and f.lower().endswith((EXT_PNG, EXT_JSON)):
            os.remove(p)
            count += 1
    return count


def _csv_line(row: Sequence[object]) -> bytes:
    buf = io.StringIO()
    csv.writer(buf).writerow(row)
    return buf.getvalue().encode("utf-8")


def iter_csv(history_dir: str) -> Iterator[bytes]:
    """Yield CSV rows (as bytes) for every history entry, newest first.

    Each PNG in *history_dir* produces one row.  The sidecar JSON is read for
    metadata; missing fields default to an empty string.
    """
    yield _csv_line(CSV_HEADERS)

    try:
        files = _sorted_pngs(history_dir)
    except Exception:
        logger.exception("CSV export: failed to list history directory")
        return

    for f in files:
        try:
            mtime = os.path.getmtime(os.path.join(history_dir, f))
        except Exception:
            continue

        meta = _load_sidecar(history_dir, f)
        # Prefer the ISO timestamp stored in the sidecar; fall back to mtime.
        timestamp = (
            meta.get("refresh_time")
            or datetime.fromtimestamp(mtime, tz=UTC).isoformat()
        )
        yield _csv_line(
            [
                timestamp,
                meta.get("plugin_id", ""),
                meta.get("plugin_instance", ""),
                meta.get("status", ""),
                meta.get("duration_ms", ""),
                meta.get("error_message", ""),
            ]
        )


_GB = 1024**3


def _disk_usage(history_dir: str) -> tuple[int, int, int, float | None]:
    """``(total, free, used, percent free)`` for the filesystem; raises OSError."""
    usage = shutil.disk_usage(history_dir)
    total_bytes = int(usage.total)
    free_bytes = int(usage.free)
    pct_free = (free_bytes / total_bytes * 100.0) if total_bytes > 0 else None
    return total_bytes, free_bytes, int(usage.used), pct_free


def storage_context(history_dir: str) -> JsonObject:
    """Storage figures for the History page; None for any it can't read."""
    free_bytes = None
    total_bytes = None
    used_bytes = None
    pct_free = None
    try:
        total_bytes, free_bytes, used_bytes, pct_free = _disk_usage(history_dir)
    except Exception:
        logger.exception("Failed to stat filesystem for history directory")

    return {
        "free_bytes": free_bytes,
        "total_bytes": total_bytes,
        "used_bytes": used_bytes,
        "pct_free": pct_free,
        "free_gb": round(free_bytes / _GB, 2) if free_bytes is not None else None,
        "total_gb": round(total_bytes / _GB, 2) if total_bytes is not None else None,
        "used_gb": round(used_bytes / _GB, 2) if used_bytes is not None else None,
    }


def storage_summary(history_dir: str) -> dict[str, float | None]:
    """Storage figures for ``/history/storage``; raises if it can't read them."""
    total_bytes, free_bytes, used_bytes, pct_free = _disk_usage(history_dir)
    return {
        "free_gb": round(free_bytes / _GB, 2),
        "total_gb": round(total_bytes / _GB, 2),
        "used_gb": round(used_bytes / _GB, 2),
        "pct_free": round(pct_free, 2) if pct_free is not None else None,
    }
