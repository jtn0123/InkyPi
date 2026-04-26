"""Plugin execution policy for refresh cycles."""

from __future__ import annotations

import logging
import os
import queue
import signal
import threading
from collections.abc import Callable, Mapping
from datetime import datetime
from time import sleep
from typing import Any, Protocol, cast

from PIL import Image

from refresh_task.actions import RefreshAction
from refresh_task.context import RefreshContext
from refresh_task.recorder import RefreshRecorder
from refresh_task.worker import (
    _execute_refresh_attempt_worker,
    _get_mp_context,
    _remote_exception,
)
from utils.plugin_errors import PermanentPluginError

logger = logging.getLogger(__name__)


class ZombieStateOwner(Protocol):
    _zombie_thread_count: int
    _zombie_thread_lock: threading.Lock


GetPluginInstance = Callable[[dict[str, Any]], Any]
TimeoutResolver = Callable[[str], float]
MpContextFactory = Callable[[], Any]
WorkerTarget = Callable[..., None]
RemoteExceptionFactory = Callable[[str, str], BaseException]


class RefreshExecutor:
    """Runs plugin refresh actions with retry, timeout, and isolation policy."""

    def __init__(
        self,
        *,
        device_config: Any,
        refresh_context: RefreshContext,
        recorder: RefreshRecorder,
        plugin_timeout_seconds: TimeoutResolver,
        zombie_owner: ZombieStateOwner,
        get_plugin_instance: GetPluginInstance,
        mp_context_factory: MpContextFactory = _get_mp_context,
        worker_target: WorkerTarget = _execute_refresh_attempt_worker,
        remote_exception_factory: RemoteExceptionFactory = _remote_exception,
    ) -> None:
        self.device_config = device_config
        self.refresh_context = refresh_context
        self.recorder = recorder
        self.plugin_timeout_seconds = plugin_timeout_seconds
        self.zombie_owner = zombie_owner
        self.get_plugin_instance = get_plugin_instance
        self.mp_context_factory = mp_context_factory
        self.worker_target = worker_target
        self.remote_exception_factory = remote_exception_factory

    @staticmethod
    def timeout_msg(plugin_id: str, timeout_s: float) -> str:
        """Return a canonical timeout error message string."""
        return f"Plugin '{plugin_id}' timed out after {int(timeout_s)}s"

    @staticmethod
    def cleanup_subprocess(proc: Any, plugin_id: str) -> None:
        """Terminate a subprocess that is still alive after its timeout."""
        getpgid = getattr(os, "getpgid", None)
        killpg = getattr(os, "killpg", None)
        if callable(getpgid) and callable(killpg):
            try:
                pgid = getpgid(proc.pid)
                if pgid != getpgid(0):
                    killpg(pgid, signal.SIGKILL)  # NOSONAR
            except OSError:
                pass

        proc.terminate()
        proc.join(timeout=2)
        if proc.is_alive():
            proc.kill()
            proc.join(timeout=2)
        if proc.is_alive():
            logger.warning(
                "plugin_lifecycle: zombie_process | plugin_id=%s pid=%s "
                "- process did not exit after kill",
                plugin_id,
                proc.pid,
            )

    def handle_process_result(
        self,
        result_queue: Any,
        proc: Any,
        plugin_id: str,
        attempt: int,
    ) -> tuple[Any, Any]:
        """Read and validate the result queue from a finished subprocess."""
        return self.handle_process_result_payload(
            result_queue,
            proc,
            plugin_id,
            attempt,
            remote_exception_factory=self.remote_exception_factory,
        )

    @staticmethod
    def handle_process_result_payload(
        result_queue: Any,
        proc: Any,
        plugin_id: str,
        attempt: int,
        remote_exception_factory: RemoteExceptionFactory = _remote_exception,
    ) -> tuple[Any, Any]:
        """Read and validate the result queue from a finished subprocess."""
        try:
            payload = result_queue.get_nowait()
        except queue.Empty:
            payload = None
        if payload is None:
            if proc.exitcode == 0:
                raise RuntimeError(
                    f"Plugin '{plugin_id}' exited without returning a result"
                )
            raise RuntimeError(f"Plugin '{plugin_id}' exited with code {proc.exitcode}")
        if payload.get("ok"):
            image_path = payload["image_path"]
            try:
                with Image.open(image_path) as image:
                    result_image = image.copy()
            finally:
                try:
                    os.unlink(image_path)
                except OSError:
                    pass
            logger.info(
                "plugin_lifecycle: attempt_success | plugin_id=%s attempt=%s",
                plugin_id,
                attempt,
            )
            return result_image, payload.get("plugin_meta")
        return None, remote_exception_factory(
            str(payload.get("error_type") or "RuntimeError"),
            str(payload.get("error_message") or "unknown error"),
        )

    def run_subprocess_attempt(
        self,
        refresh_action: RefreshAction,
        plugin_config: Mapping[str, Any],
        current_dt: datetime,
        plugin_id: str,
        timeout_s: float,
        attempt: int,
    ) -> tuple[Any, Any]:
        """Spawn a subprocess for one plugin execution attempt."""
        ctx = self.mp_context_factory()
        result_queue = ctx.Queue(maxsize=1)
        proc = cast(Any, ctx).Process(
            target=self.worker_target,
            args=(
                result_queue,
                plugin_config,
                refresh_action,
                self.refresh_context,
                current_dt,
            ),
            daemon=True,
        )
        try:
            proc.start()
            proc.join(timeout=timeout_s)
            if proc.is_alive():
                self.cleanup_subprocess(proc, plugin_id)
                return None, TimeoutError(self.timeout_msg(plugin_id, timeout_s))
            return self.handle_process_result(result_queue, proc, plugin_id, attempt)
        except TimeoutError:
            return None, TimeoutError(self.timeout_msg(plugin_id, timeout_s))
        except Exception as exc:
            return None, exc
        finally:
            try:
                result_queue.close()
            except OSError:
                pass
            try:
                result_queue.join_thread()
            except OSError:
                pass

    def execute_with_policy(
        self,
        refresh_action: RefreshAction,
        plugin_config: Mapping[str, Any],
        current_dt: datetime,
        request_id: str | None = None,
    ) -> tuple[Any, Any]:
        """Run a plugin with the configured retry and isolation policy."""
        plugin_id = refresh_action.get_plugin_id()
        _retries, backoff_ms, attempts = self.retry_policy()
        timeout_s = self.plugin_timeout_seconds(plugin_id)

        isolation = (os.getenv("INKYPI_PLUGIN_ISOLATION") or "process").strip().lower()
        if isolation == "none":
            return self.execute_inprocess(
                refresh_action,
                plugin_config,
                current_dt,
                request_id=request_id,
            )

        last_exc: BaseException | None = None
        for attempt in range(1, attempts + 1):
            logger.info(
                "plugin_lifecycle: attempt_start | plugin_id=%s attempt=%s attempts=%s timeout_s=%s",
                plugin_id,
                attempt,
                attempts,
                timeout_s,
            )
            image, exc_or_meta = self.run_subprocess_attempt(
                refresh_action, plugin_config, current_dt, plugin_id, timeout_s, attempt
            )
            if image is not None:
                return image, exc_or_meta

            last_exc = self._normalize_timeout(plugin_id, timeout_s, exc_or_meta)
            if self._raise_if_permanent(last_exc, plugin_id, attempt, attempts):
                raise last_exc

            if attempt < attempts:
                logger.warning(
                    "plugin_lifecycle: attempt_retry | plugin_id=%s attempt=%s/%s backoff_ms=%s error=%s",
                    plugin_id,
                    attempt,
                    attempts,
                    backoff_ms,
                    last_exc,
                )
                sleep(max(0.0, backoff_ms / 1000.0))
                self.recorder.publish_step(
                    plugin_id=plugin_id,
                    request_id=request_id,
                    step=f"retry {attempt}/{attempts - 1}",
                )

        if last_exc is not None:
            raise last_exc
        raise RuntimeError(f"Plugin '{plugin_id}' failed with unknown error")

    def make_inprocess_worker(
        self,
        refresh_action: RefreshAction,
        plugin_config: Mapping[str, Any],
        device_config: Any,
        current_dt: datetime,
        plugin_id: str,
    ) -> tuple[Callable[[], None], dict[str, Any], threading.Event]:
        """Return a worker function plus result holder and cancel event."""
        return self.make_inprocess_worker_for(
            refresh_action=refresh_action,
            plugin_config=plugin_config,
            device_config=device_config,
            current_dt=current_dt,
            plugin_id=plugin_id,
            zombie_owner=self.zombie_owner,
            get_plugin_instance=self.get_plugin_instance,
        )

    @staticmethod
    def make_inprocess_worker_for(
        *,
        refresh_action: RefreshAction,
        plugin_config: Mapping[str, Any],
        device_config: Any,
        current_dt: datetime,
        plugin_id: str,
        zombie_owner: ZombieStateOwner,
        get_plugin_instance: GetPluginInstance,
    ) -> tuple[Callable[[], None], dict[str, Any], threading.Event]:
        """Return a worker function plus result holder and cancel event."""
        result_holder: dict[str, Any] = {}
        cancel_event = threading.Event()

        def _worker(
            holder: dict[str, Any] = result_holder,
            _cancel: threading.Event = cancel_event,
        ) -> None:
            try:
                plugin = get_plugin_instance(dict(plugin_config))
                image = refresh_action.execute(plugin, device_config, current_dt)
                meta = None
                if hasattr(plugin, "get_latest_metadata"):
                    meta = plugin.get_latest_metadata()
                holder["image"] = image
                holder["meta"] = meta
            except Exception as exc:
                holder["error"] = exc
            finally:
                if _cancel.is_set():
                    with zombie_owner._zombie_thread_lock:
                        zombie_owner._zombie_thread_count = max(
                            0, zombie_owner._zombie_thread_count - 1
                        )
                    logger.info(
                        "Zombie thread for plugin '%s' has finished. "
                        "Active zombie threads: %d",
                        plugin_id,
                        zombie_owner._zombie_thread_count,
                    )

        return _worker, result_holder, cancel_event

    def handle_thread_timeout(
        self, plugin_id: str, timeout_s: float, cancel_event: threading.Event
    ) -> TimeoutError:
        """Mark a timed-out worker thread as a zombie and return a TimeoutError."""
        return self.handle_thread_timeout_for(
            plugin_id,
            timeout_s,
            cancel_event,
            zombie_owner=self.zombie_owner,
        )

    @staticmethod
    def handle_thread_timeout_for(
        plugin_id: str,
        timeout_s: float,
        cancel_event: threading.Event,
        *,
        zombie_owner: ZombieStateOwner,
    ) -> TimeoutError:
        """Mark a timed-out worker thread as a zombie and return a TimeoutError."""
        cancel_event.set()
        with zombie_owner._zombie_thread_lock:
            zombie_owner._zombie_thread_count += 1
            zombie_count = zombie_owner._zombie_thread_count
        logger.warning(
            "Plugin '%s' timed out after %ds — cancellation event set. "
            "Thread cannot be force-killed; it will run until completion. "
            "Active zombie threads: %d",
            plugin_id,
            int(timeout_s),
            zombie_count,
        )
        return TimeoutError(RefreshExecutor.timeout_msg(plugin_id, timeout_s))

    def execute_inprocess(
        self,
        refresh_action: RefreshAction,
        plugin_config: Mapping[str, Any],
        current_dt: datetime,
        request_id: str | None = None,
    ) -> tuple[Any, Any]:
        """Run a plugin directly in the current process with retries and timeout."""
        plugin_id = refresh_action.get_plugin_id()
        _retries, backoff_ms, attempts = self.retry_policy()
        timeout_s = self.plugin_timeout_seconds(plugin_id)

        last_exc: BaseException | None = None
        for attempt in range(1, attempts + 1):
            _worker, result_holder, cancel_event = self.make_inprocess_worker(
                refresh_action,
                plugin_config,
                self.device_config,
                current_dt,
                plugin_id,
            )

            worker_thread = threading.Thread(target=_worker, daemon=True)
            worker_thread.start()
            worker_thread.join(timeout=timeout_s)

            if worker_thread.is_alive():
                last_exc = self.handle_thread_timeout(
                    plugin_id, timeout_s, cancel_event
                )
            elif "error" in result_holder:
                last_exc = result_holder["error"]
            else:
                return result_holder["image"], result_holder.get("meta")

            if self._raise_if_permanent(last_exc, plugin_id, attempt, attempts):
                raise last_exc

            if attempt < attempts:
                logger.warning(
                    "plugin_lifecycle: attempt_retry | plugin_id=%s attempt=%s/%s backoff_ms=%s error=%s",
                    plugin_id,
                    attempt,
                    attempts,
                    backoff_ms,
                    last_exc,
                )
                sleep(max(0.0, backoff_ms / 1000.0))
                self.recorder.publish_step(
                    plugin_id=plugin_id,
                    request_id=request_id,
                    step=f"retry {attempt}/{attempts - 1}",
                )

        if last_exc is not None:
            raise last_exc
        raise RuntimeError(f"Plugin '{plugin_id}' failed with unknown error")

    @staticmethod
    def retry_policy() -> tuple[int, int, int]:
        retries = int(os.getenv("INKYPI_PLUGIN_RETRY_MAX", "1") or "1")
        backoff_ms = int(os.getenv("INKYPI_PLUGIN_RETRY_BACKOFF_MS", "500") or "500")
        attempts = max(1, retries + 1)
        return retries, backoff_ms, attempts

    @staticmethod
    def _normalize_timeout(
        plugin_id: str, timeout_s: float, exc_or_meta: Any
    ) -> BaseException:
        if isinstance(exc_or_meta, TimeoutError):
            return TimeoutError(RefreshExecutor.timeout_msg(plugin_id, timeout_s))
        if isinstance(exc_or_meta, BaseException):
            return exc_or_meta
        return RuntimeError(str(exc_or_meta))

    @staticmethod
    def _raise_if_permanent(
        exc: BaseException, plugin_id: str, attempt: int, attempts: int
    ) -> bool:
        if not isinstance(exc, PermanentPluginError):
            return False
        logger.info(
            "plugin_lifecycle: attempt_terminal | plugin_id=%s attempt=%s/%s error=%s",
            plugin_id,
            attempt,
            attempts,
            exc,
        )
        return True
