"""Latest-release check against the GitHub Releases API, with its cache.

``/api/version`` (``blueprints/settings/_updates.py``) reads from here. Tests
patch ``services.version_check.http_get`` to fake GitHub.
"""

import logging
import os
import re
import threading
import time
from typing import TypedDict, cast

from utils.http_transport import http_get

logger = logging.getLogger(__name__)

_GITHUB_REPO = os.getenv("INKYPI_GITHUB_REPO", "jtn0123/InkyPi")


class _VersionCache(TypedDict):
    latest: str | None
    checked_at: float
    release_notes: str | None
    last_error: str | None
    failed_at: float


_VERSION_CACHE: _VersionCache = {
    "latest": None,
    "checked_at": 0.0,
    "release_notes": None,
    # Surface why the last check failed so the UI can distinguish "on latest"
    # from "we never managed to reach GitHub." Cleared on a successful fetch.
    "last_error": None,
    "failed_at": 0.0,
}
_VERSION_CACHE_TTL = 3600  # 1 hour
# Every page load asks for the version (the sidebar update indicator). When
# GitHub is unreachable each attempt can hold a server thread for ~20 s (5 s
# timeout plus transport retries) and the Pi only has a few, so a failed
# check is remembered for this long instead of being retried on every load.
_VERSION_FAILURE_TTL = 600  # 10 minutes
# Only one request at a time talks to GitHub; see _check_latest_version.
_VERSION_CHECK_LOCK = threading.Lock()


def _reset_version_cache() -> None:
    """Forget every cached version-check result. Intended for tests."""
    _VERSION_CACHE["latest"] = None
    _VERSION_CACHE["checked_at"] = 0.0
    _VERSION_CACHE["release_notes"] = None
    _VERSION_CACHE["last_error"] = None
    _VERSION_CACHE["failed_at"] = 0.0


def _semver_gt(a: str, b: str) -> bool:
    """Return True if semver string *a* is strictly greater than *b*."""
    try:
        return tuple(int(x) for x in a.split(".")) > tuple(int(x) for x in b.split("."))
    except (ValueError, AttributeError):
        return False


def _check_latest_version(force_refresh: bool = False) -> str | None:
    """Fetch the latest release tag from the GitHub Releases API.

    Returns the latest version string on success or ``None`` on any failure.
    When the check fails, ``_VERSION_CACHE['last_error']`` is populated with a
    short human-readable reason so the UI can report it to the user instead
    of silently claiming "on latest".

    A success is cached for an hour and a failure for ten minutes. While one
    request is asking GitHub, other non-forced requests answer from the cache
    straight away instead of tying up another server thread on the same call.

    When ``force_refresh`` is True the cache is bypassed — this is what the
    "Check for updates" button needs so a manual click always hits GitHub.
    """
    if force_refresh:
        _VERSION_CHECK_LOCK.acquire()
    else:
        now = time.time()
        cached_latest = _VERSION_CACHE["latest"]
        if (
            cached_latest
            and (now - float(_VERSION_CACHE["checked_at"] or 0)) < _VERSION_CACHE_TTL
        ):
            return cached_latest
        failed_at = float(_VERSION_CACHE["failed_at"] or 0)
        if failed_at and (now - failed_at) < _VERSION_FAILURE_TTL:
            return None
        if not _VERSION_CHECK_LOCK.acquire(blocking=False):
            return cached_latest
    try:
        return _fetch_latest_version(time.time())
    finally:
        _VERSION_CHECK_LOCK.release()


def _fetch_latest_version(now: float) -> str | None:
    """Ask GitHub for the latest release and record the outcome in the cache."""
    try:
        resp = http_get(
            f"https://api.github.com/repos/{_GITHUB_REPO}/releases/latest",
            timeout=5,
            headers={"Accept": "application/vnd.github.v3+json"},
        )
        resp.raise_for_status()
        data = resp.json()
        tag = data.get("tag_name", "")
        if re.match(r"^v?\d+\.\d+\.\d+$", tag):
            latest = cast(str, tag).lstrip("v")
            _VERSION_CACHE["latest"] = latest
            _VERSION_CACHE["checked_at"] = now
            raw_body = data.get("body")
            _VERSION_CACHE["release_notes"] = (
                raw_body if isinstance(raw_body, str) else None
            )
            _VERSION_CACHE["last_error"] = None
            _VERSION_CACHE["failed_at"] = 0.0
            return latest
        # Response decoded but the tag isn't a stable X.Y.Z release (e.g. a
        # pre-release tag like v1.2.3-rc1). That's not a network failure, it
        # just means there's nothing auto-installable. Record a message the
        # client can show verbatim so we don't misreport this as "couldn't
        # reach GitHub".
        logger.warning(
            "Latest GitHub release tag %r is not a stable X.Y.Z release; "
            "auto-update skipped.",
            tag,
        )
        _VERSION_CACHE["last_error"] = (
            f"Latest GitHub release ({tag!r}) is not a stable X.Y.Z tag — "
            "nothing to auto-install yet."
        )
        _VERSION_CACHE["failed_at"] = now
    except Exception as exc:
        # Bubble up a short reason to the client. Log at INFO so it lands in
        # the in-app log panel without spamming errors on every check.
        reason = str(exc) or exc.__class__.__name__
        logger.info("Version check via GitHub API failed: %s", reason)
        _VERSION_CACHE["last_error"] = f"Couldn't reach GitHub: {reason}"
        _VERSION_CACHE["failed_at"] = now
    return None
