"""Plugin instance config history and diff utilities (JTN-479).

Each plugin instance gets a small JSONL log file under:
    <config_dir>/plugin_history/<safe_instance_name>.jsonl

Records are appended on every settings change and capped at MAX_ENTRIES.
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

MAX_ENTRIES = 100
# Strict allowlist regex that CodeQL recognises as a path-injection sanitizer.
_VALID_NAME_RE = re.compile(r"\A[a-zA-Z0-9][a-zA-Z0-9_\-]{0,63}\Z")


def _safe_filename(instance_name: str) -> str:
    """Return *instance_name* if it matches the allowlist; raise otherwise.

    All callers must pass a name they have already validated against
    ``_VALID_NAME_RE``. This function exists as a defense-in-depth boundary
    that taint analyzers (CodeQL py/path-injection) can recognise.
    """
    if not isinstance(instance_name, str) or not _VALID_NAME_RE.match(instance_name):
        raise ValueError("plugin_history: invalid instance name")
    return instance_name


def _history_dir(config_dir: str) -> str:
    return os.path.join(config_dir, "plugin_history")


def _history_file(config_dir: str, instance_name: str) -> str:
    return os.path.join(
        _history_dir(config_dir), f"{_safe_filename(instance_name)}.jsonl"
    )


def record_change(
    config_dir: str, instance_name: str, before: dict, after: dict
) -> None:
    """Append a change record to the instance's JSONL history file.

    Silently logs and continues on any I/O error so that plugin save is never
    blocked by a history write failure.

    The file is truncated to MAX_ENTRIES after each write (oldest entries dropped).
    """
    try:
        hist_dir = _history_dir(config_dir)
        os.makedirs(hist_dir, exist_ok=True)
        path = _history_file(config_dir, instance_name)

        entry = {
            "ts": datetime.now(UTC).isoformat(),
            "instance": instance_name,
            "before": before,
            "after": after,
        }
        line = json.dumps(entry, separators=(",", ":"))

        # Read existing lines, append new one, then truncate to MAX_ENTRIES.
        existing: list[str] = []
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as fh:
                existing = [line.rstrip("\n") for line in fh if line.strip()]

        existing.append(line)
        if len(existing) > MAX_ENTRIES:
            existing = existing[-MAX_ENTRIES:]

        # Atomic write via temp file in same directory.
        dir_path = os.path.dirname(path)
        fd, tmp_path = tempfile.mkstemp(dir=dir_path, prefix=".phist_", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write("\n".join(existing) + "\n")
            os.replace(tmp_path, path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except Exception as exc:
        # Sanitize user-controlled instance_name to prevent log injection (S5145)
        safe_name = str(instance_name).replace("\r", "").replace("\n", "")[:64]
        logger.warning(
            "plugin_history: could not record change for %r: %s", safe_name, exc
        )


def _safe_log_name(instance_name: str) -> str:
    """Strip CR/LF and cap length to prevent log injection (Sonar S5145)."""
    return str(instance_name).replace("\r", "").replace("\n", "")[:64]


def get_history(config_dir: str, instance_name: str, limit: int = 20) -> list[dict]:
    """Return up to *limit* most-recent history entries for *instance_name*.

    Entries are returned newest-first.
    """
    path = _history_file(config_dir, instance_name)
    if not os.path.isfile(path):
        return []

    entries: list[dict] = []
    try:
        with open(path, encoding="utf-8") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    entries.append(json.loads(raw))
                except json.JSONDecodeError:
                    continue
    except Exception as exc:
        logger.warning(
            "plugin_history: could not read history for %r: %s",
            _safe_log_name(instance_name),
            exc,
        )
        return []

    # Newest-first, then cap
    entries.reverse()
    return entries[:limit]


def compute_diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Return a diff dict describing what changed between *before* and *after*.

    Returns a dict with three keys:
      - added:   keys present in *after* but not in *before*
      - removed: keys present in *before* but not in *after*
      - changed: keys whose value changed (dict mapping key -> {before, after})
    """
    before_keys = set(before.keys())
    after_keys = set(after.keys())

    added = {k: after[k] for k in after_keys - before_keys}
    removed = {k: before[k] for k in before_keys - after_keys}
    changed = {
        k: {"before": before[k], "after": after[k]}
        for k in before_keys & after_keys
        if before[k] != after[k]
    }

    return {"added": added, "removed": removed, "changed": changed}
