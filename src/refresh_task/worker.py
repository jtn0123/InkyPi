"""Subprocess worker helpers for plugin execution."""

import glob
import logging
import multiprocessing
import os
import sys
import tempfile
import time
import traceback
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import TYPE_CHECKING, Protocol, TypedDict, cast

from plugins.plugin_registry import get_plugin_instance, load_plugins
from refresh_task.actions import PluginLike, RefreshAction
from refresh_task.context import RefreshContext, SupportsRefreshConfig
from utils.plugin_errors import (
    PermanentPluginError,
    ScreenshotBackendError,
    URLValidationError,
)

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from config import Config


class LegacyConfigLike(Protocol):
    """Legacy pickled config shape accepted by the worker."""

    config_file: str
    current_image_file: str
    processed_image_file: str
    plugin_image_dir: str
    history_image_dir: str


class WorkerSuccessPayload(TypedDict):
    ok: bool
    image_path: str
    plugin_meta: object


class WorkerErrorPayload(TypedDict):
    ok: bool
    error_type: str
    error_message: str
    traceback: str


WorkerPayload = WorkerSuccessPayload | WorkerErrorPayload


class ResultQueueLike(Protocol):
    """Queue interface shared by queue.Queue and multiprocessing.Queue."""

    def put(self, item: WorkerPayload) -> object: ...


_RENDER_TEMPFILE_PREFIX = "inkypi_render_"
_RENDER_TEMPFILE_SUFFIX = ".png"


def sweep_orphan_render_tempfiles(max_age_seconds: int = 3600) -> tuple[int, int]:
    """Delete leftover render tempfiles older than *max_age_seconds*.

    The child writes a PNG tempfile and puts its path on the result queue;
    the parent opens, copies, and unlinks.  If the parent crashes between
    read and unlink — or terminates the child before it can put — the
    tempfile leaks.  On tmpfs-backed ``/tmp`` this is harmless (reboot
    clears it), but disk-backed ``/tmp`` accumulates them indefinitely.

    Called at service startup from :meth:`RefreshTask.start`.  Bounded by
    file age so a currently-running render (child just wrote file, parent
    hasn't read yet) is never touched.

    Returns:
        ``(file_count, total_bytes_freed)``.  Caller typically only uses
        this for logging; failures are swallowed so a slow or unreadable
        ``/tmp`` cannot prevent the service from starting.
    """
    tmpdir = tempfile.gettempdir()
    pattern = os.path.join(
        tmpdir, f"{_RENDER_TEMPFILE_PREFIX}*{_RENDER_TEMPFILE_SUFFIX}"
    )
    now = time.time()
    deleted = 0
    bytes_freed = 0
    for path in glob.iglob(pattern):
        try:
            stat = os.stat(path)
        except OSError:
            # File vanished between glob and stat, or permission denied.
            continue
        if now - stat.st_mtime <= max_age_seconds:
            continue
        try:
            os.unlink(path)
        except OSError:
            continue
        deleted += 1
        bytes_freed += stat.st_size
    return deleted, bytes_freed


def _get_mp_context() -> multiprocessing.context.BaseContext:
    """Return the best available multiprocessing start context for this platform.

    Prefers ``forkserver`` on Linux (lower memory overhead on constrained
    devices such as Pi Zero 2W) then ``fork``, falling back to the Python
    default when neither is available.  ``forkserver`` requires all arguments
    to be picklable, which is satisfied by the worker call site.

    Returns:
        A ``multiprocessing.context.BaseContext`` instance.
    """
    # forkserver spawns children from a lean server process, reducing memory
    # on constrained devices like Pi Zero 2W. It requires picklable arguments,
    # so we only prefer it on Linux where the production target runs.
    prefer = ("forkserver", "fork") if sys.platform == "linux" else ("fork",)
    for method in prefer:
        try:
            return multiprocessing.get_context(method)
        except ValueError:
            continue
    return multiprocessing.get_context()


def _restore_child_config(
    device_config: RefreshContext | LegacyConfigLike,
) -> "Config | SupportsRefreshConfig":
    """Re-initialise the Config singleton inside a subprocess from a serialised snapshot.

    Accepts either a :class:`RefreshContext` dataclass (preferred) or a
    legacy pickled ``Config`` object.  When a ``RefreshContext`` is provided
    its :meth:`restore_child_config` method is used directly; otherwise the
    legacy path-attribute dance is performed for backwards compatibility.

    Args:
        device_config: A :class:`RefreshContext` snapshot **or** a legacy
            serialised ``Config`` object carrying the file paths needed to
            rebuild the singleton in the child process.

    Returns:
        A new :class:`Config` instance initialised from the snapshot paths.
    """
    if isinstance(device_config, RefreshContext):
        return device_config.restore_child_config()

    # Legacy fallback: raw Config object was pickled across the boundary.
    from config import Config

    Config.config_file = device_config.config_file
    Config.current_image_file = device_config.current_image_file
    Config.processed_image_file = device_config.processed_image_file
    Config.plugin_image_dir = device_config.plugin_image_dir
    Config.history_image_dir = device_config.history_image_dir
    return Config()


def _remote_exception(error_type: str, error_message: str) -> BaseException:
    """Reconstruct an exception from its serialised type name and message.

    Used to re-raise exceptions that were caught in a subprocess and
    transported across the process boundary via a result queue.  Only a
    fixed allow-list of exception types is supported; any unknown type
    falls back to ``RuntimeError``.

    Args:
        error_type: The ``__class__.__name__`` of the original exception.
        error_message: The string representation of the original exception.

    Returns:
        An instance of the matched (or fallback) exception class.
    """
    exc_types: dict[str, type[BaseException]] = {
        "RuntimeError": RuntimeError,
        "ValueError": ValueError,
        "TimeoutError": TimeoutError,
        "KeyError": KeyError,
        "TypeError": TypeError,
        "FileNotFoundError": FileNotFoundError,
        # JTN-778: preserve the PermanentPluginError type across the
        # subprocess boundary so the retry loop in the parent process can
        # distinguish it from transient RuntimeErrors and skip retries.
        "PermanentPluginError": PermanentPluginError,
        # JTN-776: URLValidationError is a PermanentPluginError subclass that
        # the plugin blueprint maps to HTTP 422 validation_error. Preserving
        # the exact type across the subprocess boundary keeps both the
        # retry-skip and 4xx-response behaviours working for manual updates
        # that are dispatched through the refresh-task subprocess path.
        "URLValidationError": URLValidationError,
        # JTN-789: ScreenshotBackendError is raised by utils.image_utils when
        # the chromium subprocess fails transiently on both the initial
        # attempt and the retry.  Preserving the exact type across the
        # subprocess boundary is what lets the plugin blueprint map it to
        # HTTP 503 ``backend_unavailable`` for manual updates dispatched via
        # the refresh-task subprocess path — without this entry the parent
        # would reconstruct it as a plain RuntimeError and fall through to
        # the generic 500 ``internal_error`` handler.
        "ScreenshotBackendError": ScreenshotBackendError,
    }
    exc_cls = exc_types.get(error_type, RuntimeError)
    return exc_cls(error_message)


def _execute_refresh_attempt_worker(
    result_queue: ResultQueueLike,
    plugin_config: Mapping[str, object],
    refresh_action: RefreshAction,
    refresh_context: RefreshContext | LegacyConfigLike,
    current_dt: datetime,
) -> None:
    """Entry point for a plugin execution subprocess.

    Intended to be the ``target`` of a ``multiprocessing.Process``.
    Restores the config singleton in the child process, executes the refresh
    action, writes the resulting image to a tempfile, and pushes a result
    dict carrying the **path** (not the bytes) onto *result_queue*.  Any
    exception is caught and pushed as a failure payload so the parent
    process can reconstruct it.

    Why a tempfile instead of raw bytes on the queue: ``Queue.put`` hands
    large payloads to a background feeder thread whose write to the pipe
    blocks at ~64 KB (Linux default pipe buffer).  The parent is usually
    waiting in ``proc.join()``, which cannot return until the child exits,
    which cannot happen until the feeder drains the pipe, which the parent
    only reads after ``proc.join()`` returns — classic deadlock.  A path
    round-trip keeps the queue payload under 1 KB and avoids the deadlock.

    Args:
        result_queue: A ``multiprocessing.Queue`` used to return exactly one
            result dict to the parent process.
        plugin_config: The raw plugin configuration dict from device.json.
        refresh_action: The :class:`RefreshAction` describing what to run.
        refresh_context: A :class:`RefreshContext` snapshot (or legacy
            ``Config`` object) used to restore the child Config singleton.
        current_dt: The current device-timezone datetime passed to the plugin.
    """
    # JTN-S2: become a session leader so any chromium subprocess spawned
    # below shares the worker's session/process group.  When the parent
    # times the worker out and calls ``_cleanup_subprocess``, that
    # cleanup ``killpg``-s the whole session — collecting chromium plus
    # its zygote/renderer/utility descendants in one syscall.  Without
    # this, chromium descendants get reparented to PID 1 and leak.
    # Best-effort — ``setsid`` fails harmlessly if the worker is already
    # a session leader (rare but possible under some test mocks), so we
    # swallow the error rather than abort the whole render.
    #
    # Two guards: ``os.setsid`` is POSIX-only (absent on Windows), and
    # several unit tests invoke this entry point in-process where an
    # unconditional ``setsid`` would detach the test runner's session.
    # Only call it when we're actually running as a multiprocessing child.
    setsid = getattr(os, "setsid", None)
    if callable(setsid) and multiprocessing.parent_process() is not None:
        try:
            setsid()
        except OSError:
            pass

    try:
        child_config = _restore_child_config(refresh_context)
        # JTN-783: spawned / forkserver children start with an empty plugin
        # registry because module-level dicts in `plugins.plugin_registry`
        # don't cross the process boundary. Re-register plugins from the
        # restored Config so `get_plugin_instance` can resolve plugin_id.
        # `load_plugins` is idempotent (overwrites under a lock), so this is
        # safe to call every attempt. If the restored config somehow lacks
        # a `get_plugins` method (legacy pickled payload), skip and let
        # `get_plugin_instance` raise a clear ValueError below.
        get_plugins = getattr(child_config, "get_plugins", None)
        if callable(get_plugins):
            load_plugins(get_plugins())
        plugin_loader = cast(
            Callable[[Mapping[str, object]], PluginLike],
            get_plugin_instance,
        )
        plugin = plugin_loader(plugin_config)
        image = refresh_action.execute(plugin, child_config, current_dt)
        plugin_meta = None
        if hasattr(plugin, "get_latest_metadata"):
            metadata_getter = cast(Callable[[], object], plugin.get_latest_metadata)
            plugin_meta = metadata_getter()
        if image is None:
            raise RuntimeError("Plugin returned None image")
        # Write PNG to a tempfile and hand off the path via the queue instead
        # of the raw bytes.  multiprocessing.Queue.put spawns a feeder thread
        # that writes the pickled payload to a pipe whose default buffer is
        # 65,536 bytes on Linux.  Any payload bigger than that blocks the
        # feeder on the second write until the reader drains the pipe — but
        # the parent is inside ``proc.join()`` waiting for the child to exit,
        # and the child can't exit until the feeder finishes.  Classic
        # deadlock.  Every real plugin's PNG is larger than 64 KB (e.g.
        # clock at 800x480 is ~89 KB), so this manifested on every single
        # render.  Passing a filesystem path keeps the queue payload < 1 KB
        # and sidesteps the pipe buffer entirely.  Parent deletes the file
        # after reading in task.py::_handle_process_result.
        with tempfile.NamedTemporaryFile(
            suffix=_RENDER_TEMPFILE_SUFFIX,
            prefix=_RENDER_TEMPFILE_PREFIX,
            delete=False,
        ) as png_file:
            image.save(png_file, format="PNG")
            image_path = png_file.name
        result_queue.put(
            {
                "ok": True,
                "image_path": image_path,
                "plugin_meta": plugin_meta,
            }
        )
    except Exception as exc:
        result_queue.put(
            {
                "ok": False,
                "error_type": exc.__class__.__name__,
                "error_message": str(exc),
                "traceback": traceback.format_exc(),
            }
        )
