"""Crash forensics that survive a hard kill.

The circuit breaker in :mod:`refresh_task.health` counts *handled* exceptions.
A plugin that gets the whole process OOM-killed or segfaults never raises
anything we can catch, so it never trips the breaker — it just crash-loops, and
every loop costs an SD-card write. Worse, once the process is gone there is no
record of what it was doing, so the next run cannot attribute the death.

This module is the missing evidence. It writes a breadcrumb naming the
operation in flight before each risky phase and clears it afterwards, so a run
that dies mid-operation leaves the breadcrumb behind for the next start to
find. The pattern is taken from ``system/crashlog.h`` in the ESP32-Garage-Fan
firmware, whose author notes it was "the difference between diagnosing the
2026-08-05 crash loop and guessing at it".

Two locations, chosen for their lifetimes:

* the breadcrumb lives under the service's ``RuntimeDirectory`` (``/run/inkypi``,
  a tmpfs) so a clean reboot clears it — a breadcrumb found at startup means
  *this* boot's predecessor died, not one from last week;
* the verdict is persisted under ``/var/lib/inkypi`` so it survives reboots and
  can be surfaced in diagnostics.

Every operation here is best-effort. Forensics must never be the reason a
refresh fails, so all filesystem errors are swallowed and logged at debug.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: tmpfs-backed, cleared by a reboot. Matches ``RuntimeDirectory=inkypi``.
_DEFAULT_RUNTIME_DIR = "/run/inkypi"
#: Survives reboots, shared with the update/rollback state files.
_DEFAULT_STATE_DIR = "/var/lib/inkypi"

_BREADCRUMB_NAME = "breadcrumb.json"
_LAST_DEATH_NAME = "last_death.json"

#: How many prior verdicts to keep. The immediately-previous death is what you
#: normally want; the one before it tells you whether it is a repeating loop.
_DEATH_HISTORY = 2


def _resolved_dir(candidate: str, fallback: str) -> Path:
    """Resolve an environment-supplied directory, falling back if unusable.

    These directories come from the environment, so they are only as trustworthy
    as whatever launched the process. A relative value would also scatter
    breadcrumbs relative to the service's working directory rather than putting
    them where the next boot looks, so requiring an absolute path is both the
    safer and the more correct reading.

    SonarCloud reports S2083 (path built from user-controlled data) against the
    write this feeds. Assessed as a false positive — these variables come from
    the systemd unit, not from a request — and tracked, with the reasoning and
    what was hardened anyway, in
    ``docs/security/sonar-s2083-crash-breadcrumb-tracking.md``.
    """
    try:
        path = Path(candidate).expanduser()
        if path.is_absolute():
            return path.resolve()
        logger.warning(
            "crash breadcrumb: ignoring relative directory %r; using %s",
            candidate,
            fallback,
        )
    except (OSError, ValueError):
        logger.warning(
            "crash breadcrumb: unusable directory %r; using %s",
            candidate,
            fallback,
            exc_info=True,
        )
    return Path(fallback)


def _runtime_dir() -> Path:
    return _resolved_dir(
        os.getenv("INKYPI_RUNTIME_DIR") or _DEFAULT_RUNTIME_DIR, _DEFAULT_RUNTIME_DIR
    )


def _state_dir() -> Path:
    return _resolved_dir(
        os.getenv("INKYPI_LOCKFILE_DIR")
        or os.getenv("INKYPI_STATE_DIR")
        or _DEFAULT_STATE_DIR,
        _DEFAULT_STATE_DIR,
    )


def _in_dir(directory: Path, name: str) -> Path:
    """Join a *constant* filename to *directory*, refusing to escape it.

    ``name`` is a module constant today; the check keeps that a property of the
    code rather than an assumption, so a future caller cannot turn these
    helpers into an arbitrary-write primitive.
    """
    candidate = (directory / name).resolve()
    if candidate.parent != directory:
        raise ValueError(f"{name!r} does not resolve inside {directory}")
    return candidate


def _breadcrumb_path() -> Path:
    return _in_dir(_runtime_dir(), _BREADCRUMB_NAME)


def _last_death_path() -> Path:
    return _in_dir(_state_dir(), _LAST_DEATH_NAME)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write *payload* atomically, swallowing every failure."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        tmp.replace(path)
    except Exception:
        logger.debug("crash breadcrumb: could not write %s", path, exc_info=True)


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.debug("crash breadcrumb: could not read %s", path, exc_info=True)
        return None
    return data if isinstance(data, dict) else None


def drop(operation: str, **details: Any) -> None:
    """Record that *operation* is now in flight."""
    payload: dict[str, Any] = {"operation": operation, "started_at": _now_iso()}
    payload.update({k: v for k, v in details.items() if v is not None})
    _write_json(_breadcrumb_path(), payload)


def clear() -> None:
    """Record that the in-flight operation completed."""
    try:
        _breadcrumb_path().unlink(missing_ok=True)
    except Exception:
        logger.debug("crash breadcrumb: could not clear", exc_info=True)


@contextmanager
def trail(operation: str, **details: Any) -> Iterator[None]:
    """Mark *operation* in flight for the duration of the block.

    The breadcrumb is cleared on the way out whether the block succeeded or
    raised — a raised exception was handled, and handled failures are the
    circuit breaker's job. Only an unhandled death leaves the breadcrumb behind,
    which is exactly the signal we want.
    """
    drop(operation, **details)
    try:
        yield
    finally:
        clear()


def examine_boot() -> dict[str, Any] | None:
    """Consume any breadcrumb left by the previous run and record the verdict.

    Call once during startup, before anything risky runs.

    Returns:
        The breadcrumb the previous run died holding, or ``None`` when it shut
        down cleanly (or this is the first start since a reboot).
    """
    breadcrumb = _read_json(_breadcrumb_path())
    clear()

    if breadcrumb is None:
        return None

    logger.error(
        "Previous run died during operation '%s' (started %s); details: %s",
        breadcrumb.get("operation", "unknown"),
        breadcrumb.get("started_at", "unknown"),
        {k: v for k, v in breadcrumb.items() if k not in ("operation", "started_at")},
    )

    record = _read_json(_last_death_path()) or {}
    history = record.get("history")
    if not isinstance(history, list):
        history = []
    verdict = dict(breadcrumb)
    verdict["recorded_at"] = _now_iso()
    history.insert(0, verdict)
    _write_json(
        _last_death_path(),
        {
            "last_death": verdict,
            "history": history[:_DEATH_HISTORY],
            "deaths": _coerce_death_count(record.get("deaths")) + 1,
        },
    )
    return breadcrumb


def _coerce_death_count(value: Any) -> int:
    """Read a persisted death count, tolerating a corrupt state file.

    The count is only ever advisory. Letting a bad value raise here would abort
    ``examine_boot`` and with it the quarantine step — the one thing that must
    still happen after a crash.
    """
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def last_death() -> dict[str, Any] | None:
    """The operation in flight when the process last died, if any."""
    record = _read_json(_last_death_path())
    if record is None:
        return None
    death = record.get("last_death")
    return death if isinstance(death, dict) else None


def death_count() -> int:
    """How many times a run has died mid-operation on this device."""
    record = _read_json(_last_death_path()) or {}
    return _coerce_death_count(record.get("deaths"))


def clear_last_death() -> None:
    """Forget the recorded deaths — used when a quarantine is lifted."""
    try:
        _last_death_path().unlink(missing_ok=True)
    except Exception:
        logger.debug("crash breadcrumb: could not clear last death", exc_info=True)
