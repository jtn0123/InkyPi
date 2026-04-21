"""Subprocess worker helpers for plugin execution."""

import io
import logging
import multiprocessing
import sys
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
    image_bytes: bytes
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
    action, serialises the resulting image to PNG bytes, and pushes a result
    dict onto *result_queue*.  Any exception is caught and pushed as a
    failure payload so the parent process can reconstruct it.

    Args:
        result_queue: A ``multiprocessing.Queue`` used to return exactly one
            result dict to the parent process.
        plugin_config: The raw plugin configuration dict from device.json.
        refresh_action: The :class:`RefreshAction` describing what to run.
        refresh_context: A :class:`RefreshContext` snapshot (or legacy
            ``Config`` object) used to restore the child Config singleton.
        current_dt: The current device-timezone datetime passed to the plugin.
    """
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
        image_bytes = io.BytesIO()
        image.save(image_bytes, format="PNG")
        result_queue.put(
            {
                "ok": True,
                "image_bytes": image_bytes.getvalue(),
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
