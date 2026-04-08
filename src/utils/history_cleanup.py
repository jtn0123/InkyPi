"""history_cleanup — automatic retention-policy cleanup for history images.

Walks the history directory, deletes files that exceed the configured
retention thresholds, and returns a summary of what was removed.

Safety guarantees
-----------------
- Only operates on regular files directly inside *history_dir* (no recursion).
- Never follows symbolic links.
- All paths are validated to lie within the resolved *history_dir*.
- Paired JSON sidecar files are deleted alongside their PNG counterpart.
"""

from __future__ import annotations

import logging
import os
import shutil
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Extensions treated as primary history files (others are sidecars / unknown).
_PRIMARY_EXT = ".png"
_SIDECAR_EXT = ".json"


@dataclass
class CleanupResult:
    """Summary of a single cleanup run."""

    deleted_count: int = 0
    freed_bytes: int = 0
    remaining_count: int = 0
    skipped_symlinks: int = 0
    errors: list[str] = field(default_factory=list)


def _resolve_safe(base_dir: str, filename: str) -> str | None:
    """Return the absolute path of *filename* under *base_dir*, or None if unsafe."""
    candidate = os.path.realpath(os.path.join(base_dir, filename))
    real_base = os.path.realpath(base_dir)
    if os.path.commonpath([real_base, candidate]) != real_base:
        return None
    return candidate


def _safe_remove(path: str, result: CleanupResult) -> int:
    """Delete *path* and return the number of bytes freed (0 on error)."""
    try:
        freed = os.path.getsize(path)
        os.remove(path)
        return freed
    except OSError as exc:
        logger.warning("history_cleanup: could not remove %s: %s", path, exc)
        result.errors.append(f"remove {path}: {exc}")
        return 0


def _remove_pair(base_dir: str, png_path: str, result: CleanupResult) -> None:
    """Delete a PNG history file and its sidecar JSON (if present)."""
    freed = _safe_remove(png_path, result)
    if freed:
        result.deleted_count += 1
        result.freed_bytes += freed

    stem = os.path.splitext(os.path.basename(png_path))[0]
    sidecar = os.path.join(base_dir, stem + _SIDECAR_EXT)
    if os.path.isfile(sidecar) and not os.path.islink(sidecar):
        sidecar_freed = _safe_remove(sidecar, result)
        result.freed_bytes += sidecar_freed


def _collect_png_files(
    history_dir: str, result: CleanupResult
) -> list[tuple[float, str]]:
    """Return a list of ``(mtime, abs_path)`` for every non-symlink PNG in *history_dir*.

    Symlinks are skipped and counted in *result.skipped_symlinks*.
    """
    entries: list[tuple[float, str]] = []
    try:
        names = os.listdir(history_dir)
    except OSError as exc:
        logger.error("history_cleanup: cannot list %s: %s", history_dir, exc)
        result.errors.append(f"listdir {history_dir}: {exc}")
        return entries

    for name in names:
        if not name.lower().endswith(_PRIMARY_EXT):
            continue
        full_path = os.path.join(history_dir, name)

        # Skip symlinks for security
        if os.path.islink(full_path):
            logger.debug("history_cleanup: skipping symlink %s", full_path)
            result.skipped_symlinks += 1
            continue

        # Containment check (extra defence against path-traversal in filenames)
        if _resolve_safe(history_dir, name) is None:
            logger.warning("history_cleanup: skipping out-of-dir path %s", name)
            continue

        try:
            mtime = os.path.getmtime(full_path)
        except OSError:
            mtime = 0.0

        entries.append((mtime, full_path))

    return entries


def cleanup_history(
    history_dir: str,
    max_age_days: int = 30,
    max_count: int = 500,
    min_free_bytes: int = 500_000_000,
) -> CleanupResult:
    """Delete old history images according to a retention policy.

    Parameters
    ----------
    history_dir:
        Absolute path to the directory that holds history PNG files.
    max_age_days:
        Delete files whose mtime is older than this many days.  ``0`` disables
        the age check.
    max_count:
        Keep at most this many PNG files (newest first).  ``0`` disables the
        count cap.
    min_free_bytes:
        If free disk space on the *history_dir* filesystem falls below this
        threshold, delete oldest files until the threshold is met.  ``0``
        disables the free-space check.

    Returns
    -------
    CleanupResult
        Summary of what was deleted.
    """
    result = CleanupResult()

    if not os.path.isdir(history_dir):
        logger.debug("history_cleanup: directory does not exist: %s", history_dir)
        return result

    entries = _collect_png_files(history_dir, result)

    if not entries:
        logger.debug("history_cleanup: nothing to clean in %s", history_dir)
        return result

    # Sort ascending by mtime so oldest entries are first.
    entries.sort(key=lambda t: t[0])

    # --- Pass 1: age-based deletion ---
    if max_age_days > 0:
        cutoff = time.time() - max_age_days * 86400
        survivors: list[tuple[float, str]] = []
        for mtime, path in entries:
            if mtime < cutoff:
                logger.debug("history_cleanup: age evict %s (mtime=%s)", path, mtime)
                _remove_pair(history_dir, path, result)
            else:
                survivors.append((mtime, path))
        entries = survivors

    # --- Pass 2: count-based deletion (keep newest max_count) ---
    if max_count > 0 and len(entries) > max_count:
        overflow = len(entries) - max_count
        to_delete, to_keep = entries[:overflow], entries[overflow:]
        for _mtime, path in to_delete:
            logger.debug("history_cleanup: count evict %s", path)
            _remove_pair(history_dir, path, result)
        entries = to_keep

    # --- Pass 3: free-space-based deletion (oldest first until threshold met) ---
    if min_free_bytes > 0 and entries:
        try:
            usage = shutil.disk_usage(history_dir)
            free = usage.free
        except OSError as exc:
            logger.warning("history_cleanup: disk_usage failed: %s", exc)
            free = min_free_bytes  # Assume OK if we can't check

        survivors = list(entries)
        while free < min_free_bytes and survivors:
            _mtime, path = survivors.pop(0)  # oldest first
            logger.debug(
                "history_cleanup: disk evict %s (free=%d < min=%d)",
                path,
                free,
                min_free_bytes,
            )
            before_freed = result.freed_bytes
            _remove_pair(history_dir, path, result)
            delta = result.freed_bytes - before_freed
            free += delta

        entries = survivors

    result.remaining_count = len(entries)
    if result.deleted_count:
        logger.info(
            "history_cleanup: deleted %d file(s), freed %.1f KB, %d remaining",
            result.deleted_count,
            result.freed_bytes / 1024,
            result.remaining_count,
        )
    return result
