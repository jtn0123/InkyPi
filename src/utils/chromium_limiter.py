"""Cross-process cap on concurrently running headless Chromium instances.

Each headless Chromium costs 150-250 MB of RSS. On a Pi Zero 2 W (512 MB) two
of them at once is enough to trip the OOM killer, and the app has several
independent places that can launch one: the refresh-task worker subprocess,
the job-queue thread pool, and request threads that render previews. A
``threading.Lock`` cannot see across the ``multiprocessing`` boundary, so the
slot is an exclusive ``flock`` on a well-known lock file instead.

``flock`` locks belong to the open file description, so:

* two threads that each ``open()`` the file contend exactly like two
  processes do;
* the kernel drops the lock when the descriptor is closed or the holder dies
  (SIGKILL, OOM kill, segfault), so a crashed render can never wedge the slot.

Chromium children are launched with ``close_fds=True`` (the ``subprocess``
default), so they never inherit the lock descriptor and cannot outlive it.
"""

from __future__ import annotations

import fcntl
import logging
import os
import tempfile
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager

from utils.plugin_errors import ScreenshotBackendError

logger = logging.getLogger(__name__)

_LOCK_FILENAME = "inkypi-chromium.lock"
#: Matches ``RuntimeDirectory=inkypi`` in install/inkypi.service.
_DEFAULT_RUNTIME_DIR = "/run/inkypi"
#: Stays below the 60s generic plugin timeout so a starved render fails with a
#: specific "renderer busy" error rather than an anonymous plugin timeout.
_DEFAULT_WAIT_TIMEOUT_S = 45.0
_POLL_INTERVAL_S = 0.1

_local = threading.local()
# Descriptors currently holding the slot in this process. A plain ``fork``
# copies them into the child, where they would keep the slot pinned for as
# long as the child lives; ``_close_inherited_fds`` drops those copies.
_held_fds: set[int] = set()
_held_fds_lock = threading.Lock()


def _close_inherited_fds() -> None:
    # Closing the child's duplicate does not release the parent's lock: an
    # flock is only dropped once every descriptor sharing it is closed.
    for fd in tuple(_held_fds):
        try:
            os.close(fd)
        except OSError:
            pass
    _held_fds.clear()
    _local.__dict__.clear()


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_close_inherited_fds)


def lock_file_path() -> str:
    """Return the path of the shared Chromium slot lock file."""
    override = (os.getenv("INKYPI_CHROMIUM_LOCK_DIR") or "").strip()
    candidates = [
        override,
        (os.getenv("INKYPI_RUNTIME_DIR") or "").strip(),
        _DEFAULT_RUNTIME_DIR,
    ]
    for directory in candidates:
        if directory and os.path.isdir(directory) and os.access(directory, os.W_OK):
            return os.path.join(directory, _LOCK_FILENAME)
    return os.path.join(tempfile.gettempdir(), _LOCK_FILENAME)


def _wait_timeout_s() -> float:
    raw = (os.getenv("INKYPI_CHROMIUM_LOCK_TIMEOUT_S") or "").strip()
    if not raw:
        return _DEFAULT_WAIT_TIMEOUT_S
    try:
        return max(0.0, float(raw))
    except ValueError:
        return _DEFAULT_WAIT_TIMEOUT_S


def _open_lock_file(path: str) -> int | None:
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_CLOEXEC", 0)
    try:
        return os.open(path, flags, 0o600)
    except OSError as exc:
        # Fail open: an unusable lock file must not take rendering down with
        # it. The cap is a memory safeguard, not a correctness requirement.
        logger.warning(
            "Chromium limiter: cannot open lock file %s (%s); rendering "
            "without a concurrency cap",
            path,
            exc,
        )
        return None


@contextmanager
def slot_wait_limit(timeout_s: float) -> Iterator[None]:
    """Cap how long :func:`chromium_slot` may wait on the current thread.

    For callers that must not sit on a busy renderer for the full default
    wait, e.g. a web request thread that has a cheaper fallback to serve.
    """
    previous = getattr(_local, "wait_limit", None)
    _local.wait_limit = max(0.0, timeout_s)
    try:
        yield
    finally:
        _local.wait_limit = previous


def _acquire_lock(fd: int, path: str, purpose: str, wait_s: float) -> None:
    """Poll for the exclusive flock on *fd*, raising once *wait_s* elapses."""
    started = time.monotonic()
    deadline = started + wait_s
    logged_wait = False
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except BlockingIOError:
            if not logged_wait:
                logger.info(
                    "Chromium limiter: %s waiting for another browser "
                    "instance to finish (lock=%s, timeout=%.0fs)",
                    purpose,
                    path,
                    wait_s,
                )
                logged_wait = True
            if time.monotonic() >= deadline:
                logger.error(
                    "Chromium limiter: %s gave up after %.1fs; another "
                    "headless browser still holds %s",
                    purpose,
                    time.monotonic() - started,
                    path,
                )
                raise ScreenshotBackendError(
                    "Renderer busy: another headless browser is still "
                    f"running after {wait_s:.0f}s. Try again shortly."
                ) from None
            time.sleep(_POLL_INTERVAL_S)
    if logged_wait:
        logger.info(
            "Chromium limiter: %s acquired slot after %.1fs",
            purpose,
            time.monotonic() - started,
        )


@contextmanager
def chromium_slot(
    purpose: str = "render", timeout_s: float | None = None
) -> Iterator[None]:
    """Hold the single machine-wide Chromium slot for the duration of the block.

    Re-entrant within one thread, so a helper that already holds the slot can
    call another helper that also asks for it without deadlocking itself.

    Raises:
        ScreenshotBackendError: when the slot is still busy after the wait
            timeout (``INKYPI_CHROMIUM_LOCK_TIMEOUT_S``, default 45s). The
            refresh worker and plugin blueprint already map this type to a
            retryable 503 ``backend_unavailable``.
    """
    depth = getattr(_local, "depth", 0)
    if depth:
        _local.depth = depth + 1
        try:
            yield
        finally:
            _local.depth = depth
        return

    path = lock_file_path()
    fd = _open_lock_file(path)
    if fd is None:
        yield
        return

    if timeout_s is None:
        wait_limit = getattr(_local, "wait_limit", None)
        wait_s = _wait_timeout_s() if wait_limit is None else wait_limit
    else:
        wait_s = max(0.0, timeout_s)
    try:
        _acquire_lock(fd, path, purpose, wait_s)
        with _held_fds_lock:
            _held_fds.add(fd)
        _local.depth = 1
        try:
            yield
        finally:
            _local.depth = 0
            with _held_fds_lock:
                _held_fds.discard(fd)
    finally:
        # Closing the descriptor releases the flock (if held).
        os.close(fd)
