"""Delete uploaded files that no saved setting refers to any more.

Uploads land in ``static/images/saved/`` and were only ever deleted with the
whole plugin instance, so removing a photo from an instance, or uploading
through "Update Now" (which never saves the path), left the file on the SD
card for good.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Iterable, Mapping

logger = logging.getLogger(__name__)

# An upload is written before the request that saves its path finishes, and
# "Update Now" renders from a file that is never saved. A day's grace keeps
# every in-flight file safe.
UNREFERENCED_GRACE_S = 24 * 60 * 60


def _collect_names(value: object, names: set[str]) -> None:
    """Add the base name of every string found anywhere in *value*."""
    if isinstance(value, str):
        names.add(os.path.basename(value))
    elif isinstance(value, Mapping):
        for item in value.values():
            _collect_names(item, names)
    elif isinstance(value, list | tuple):
        for item in value:
            _collect_names(item, names)


def prune_unreferenced_uploads(
    upload_dir: str,
    settings: Iterable[object],
    *,
    now: float | None = None,
    grace_s: float = UNREFERENCED_GRACE_S,
) -> int:
    """Delete files in *upload_dir* that nothing in *settings* names.

    *settings* are config snapshots (the device config, the playlists). A
    file counts as used when any string in them ends in its name, which errs
    toward keeping files. Files younger than *grace_s* are always kept.
    Returns the number of files deleted.
    """
    referenced: set[str] = set()
    for snapshot in settings:
        _collect_names(snapshot, referenced)
    cutoff = (time.time() if now is None else now) - grace_s
    removed = 0
    try:
        entries = list(os.scandir(upload_dir))
    except FileNotFoundError:
        return 0
    for entry in entries:
        if entry.name in referenced or not entry.is_file(follow_symlinks=False):
            continue
        try:
            if entry.stat(follow_symlinks=False).st_mtime > cutoff:
                continue
            os.remove(entry.path)
        except FileNotFoundError:
            continue
        removed += 1
        logger.info("upload_cleanup: deleted unused upload %s", entry.name)
    return removed
