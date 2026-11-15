"""A newest-first index of the history sidecars (``display_*.json``).

The plugin page looked up "latest image" and "last refreshed" by listing the
history folder and opening sidecars one by one until one matched. With the
500 entries the Pi keeps, a plugin with no recent image read every file,
about 350 ms per lookup, and one page load made up to three lookups.

:func:`entries` keeps the parsed sidecars in memory. While the folder is
unchanged it returns them as they are. When the folder changes it rescans,
parsing only files that are new or whose size or mtime changed.

A folder's mtime has coarse resolution, so a file added in the same tick as
a scan would not change it. As in git's "racy" check, a snapshot taken less
than :data:`_RACY_WINDOW_NS` after the folder last changed is not trusted:
the next call rescans (cheaply, reusing what was already parsed). That also
covers a sidecar read while it was still being written.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass

_SIDECAR_SUFFIX = ".json"
_RACY_WINDOW_NS = 2_000_000_000
# Tests use many temporary folders; the app uses one.
_MAX_FOLDERS = 4


@dataclass(frozen=True)
class HistoryEntry:
    """What the pages need from one sidecar."""

    name: str
    plugin_id: str | None
    plugin_instance: str | None
    refresh_time: str | None

    @property
    def image_name(self) -> str:
        """The PNG this sidecar describes."""
        return self.name[: -len(_SIDECAR_SUFFIX)] + ".png"


@dataclass(frozen=True)
class _Snapshot:
    folder_mtime_ns: int
    taken_at_ns: int
    entries: tuple[HistoryEntry, ...]
    # name -> (mtime_ns, size, parsed entry or None when unreadable)
    files: dict[str, tuple[int, int, HistoryEntry | None]]

    def still_valid(self, folder_mtime_ns: int) -> bool:
        return (
            folder_mtime_ns == self.folder_mtime_ns
            and self.taken_at_ns - self.folder_mtime_ns >= _RACY_WINDOW_NS
        )


_lock = threading.Lock()
_snapshots: dict[str, _Snapshot] = {}


def entries(history_dir: str) -> tuple[HistoryEntry, ...]:
    """Return the readable sidecars in *history_dir*, newest first.

    Newest first is filename order: names follow ``display_YYYYMMDD_HHMMSS``.
    A missing or unreadable folder gives an empty tuple.
    """
    try:
        folder_mtime_ns = os.stat(history_dir).st_mtime_ns
    except OSError:
        return ()
    with _lock:
        previous = _snapshots.get(history_dir)
    if previous is not None and previous.still_valid(folder_mtime_ns):
        return previous.entries

    snapshot = _scan(history_dir, folder_mtime_ns, previous)
    with _lock:
        _snapshots.pop(history_dir, None)
        while len(_snapshots) >= _MAX_FOLDERS:
            _snapshots.pop(next(iter(_snapshots)))
        _snapshots[history_dir] = snapshot
    return snapshot.entries


def clear() -> None:
    """Forget every snapshot (tests)."""
    with _lock:
        _snapshots.clear()


def _scan(
    history_dir: str, folder_mtime_ns: int, previous: _Snapshot | None
) -> _Snapshot:
    # Taken before listing, so a change during the scan counts as racy.
    taken_at_ns = time.time_ns()
    known = previous.files if previous is not None else {}
    files: dict[str, tuple[int, int, HistoryEntry | None]] = {}
    try:
        with os.scandir(history_dir) as listing:
            for item in listing:
                if not item.name.endswith(_SIDECAR_SUFFIX):
                    continue
                try:
                    stat = item.stat()
                except OSError:
                    continue
                cached = known.get(item.name)
                if cached is not None and cached[:2] == (
                    stat.st_mtime_ns,
                    stat.st_size,
                ):
                    files[item.name] = cached
                else:
                    files[item.name] = (
                        stat.st_mtime_ns,
                        stat.st_size,
                        _parse(item.path, item.name),
                    )
    except OSError:
        files = {}
    ordered = tuple(
        entry
        for _name, (_m, _s, entry) in sorted(files.items(), reverse=True)
        if entry is not None
    )
    return _Snapshot(folder_mtime_ns, taken_at_ns, ordered, files)


def _parse(path: str, name: str) -> HistoryEntry | None:
    try:
        with open(path, encoding="utf-8") as fh:
            meta = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(meta, dict):
        return None
    return HistoryEntry(
        name=name,
        plugin_id=_text(meta.get("plugin_id")),
        plugin_instance=_text(meta.get("plugin_instance")),
        refresh_time=_text(meta.get("refresh_time")),
    )


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
