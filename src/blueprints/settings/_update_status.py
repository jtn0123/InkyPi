"""Helpers for surfacing update-failure metadata written by ``install/update.sh``.

JTN-704 installed an EXIT trap in ``install/update.sh`` that writes a JSON
record to ``/var/lib/inkypi/.last-update-failure`` whenever the update exits
with a non-zero status.  JTN-710 wires that file through the Flask update
status endpoint so the Settings -> Updates page can surface *why* the last
update failed instead of making the user SSH in and read the journal.

The contract written by the shell trap is:

    {
      "timestamp": "2026-04-14T23:00:00Z",
      "exit_code": 97,
      "last_command": "apt_install",
      "recent_journal_lines": "...multi-line journal tail..."
    }

This helper reads that file defensively:

* Missing file -> ``None``.
* Malformed JSON or unreadable file -> ``{"parse_error": True}`` so the UI
  can still show a "last update failed but we can't read the record" hint
  without crashing the status endpoint.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: Default on-disk location written by ``install/update.sh`` (JTN-704).
_DEFAULT_LOCKFILE_DIR = "/var/lib/inkypi"
_FAILURE_FILENAME = ".last-update-failure"

# Cap how much of the failure record we ever return to a browser so a runaway
# journal capture can't blow up the response body (the shell trap captures the
# last 20 journal lines, but belt-and-suspenders is cheap).
_MAX_FAILURE_BYTES = 64 * 1024


def _failure_file_path() -> Path:
    """Resolve the failure-file path, honoring ``INKYPI_LOCKFILE_DIR``.

    The shell script already honors ``INKYPI_LOCKFILE_DIR`` (see
    ``install/update.sh``) so tests can redirect writes to a tempdir; mirror
    that contract in Python so unit tests can point us at a fixture without
    monkey-patching the module.
    """

    base = os.environ.get("INKYPI_LOCKFILE_DIR") or _DEFAULT_LOCKFILE_DIR
    return Path(base) / _FAILURE_FILENAME


def read_last_update_failure() -> dict[str, Any] | None:
    """Return the parsed ``.last-update-failure`` record, or ``None``.

    Return values:

    * ``None`` -> no failure file on disk (happy path, or file already
      cleared by a subsequent successful update).
    * ``dict`` -> parsed JSON record.  Keys are whatever the shell trap
      wrote; we do not validate individual fields here because the UI is
      happy to render partial records.
    * ``{"parse_error": True}`` -> the file exists but could not be read
      or parsed as JSON.  The UI still gets a truthy value so it can show
      a generic "last update failed" banner, and the ``parse_error`` key
      tells callers not to trust the other fields.
    """

    path = _failure_file_path()
    try:
        if not path.is_file():
            return None
    except OSError:
        # e.g. permission denied on the parent dir; treat as "no file" so we
        # do not spam the UI with an error banner when the real issue is that
        # we cannot read /var/lib/inkypi at all.
        logger.debug("Could not stat %s", path, exc_info=True)
        return None

    try:
        raw = path.read_bytes()
    except OSError:
        logger.warning("Failed to read %s", path, exc_info=True)
        return {"parse_error": True}

    if len(raw) > _MAX_FAILURE_BYTES:
        # Truncate to the cap so the response stays small; we still try to
        # parse in case the prefix is valid JSON (it normally will not be,
        # but return parse_error either way so the UI does not show a
        # half-truncated journal).
        raw = raw[:_MAX_FAILURE_BYTES]

    try:
        data = json.loads(raw.decode("utf-8", errors="replace"))
    except ValueError:
        # json.JSONDecodeError is a ValueError subclass; errors="replace"
        # above means the decode step cannot raise.
        logger.warning("Malformed JSON in %s", path)
        return {"parse_error": True}

    if not isinstance(data, dict):
        logger.warning("Unexpected JSON shape in %s: %r", path, type(data).__name__)
        return {"parse_error": True}

    return data
