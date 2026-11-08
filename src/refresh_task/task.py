"""RefreshTask — main coordinator for display refresh operations.

``RefreshTask`` owns the thread lifecycle, the refresh loop and the plugin
execution/isolation wrappers. The rest of its behaviour lives in mixins:

* :mod:`refresh_task.loop_scheduling` — trigger waits, next-plugin selection,
  the watchdog stall gate, history cleanup and system stats.
* :mod:`refresh_task.command_queue` — manual updates and display commands.
* :mod:`refresh_task.refresh_cycle` — one refresh, generate through record.
* :mod:`refresh_task.health_hooks` — plugin health and circuit breaker.
"""

import logging
import threading
from collections import deque
from collections.abc import Callable, Mapping
from datetime import datetime
from time import monotonic
from typing import Any, ClassVar, cast

from refresh_task import plugin_lookup, recorder as refresh_recorder
from refresh_task.actions import ManualUpdateRequest, RefreshAction
from refresh_task.command_queue import CommandQueueMixin
from refresh_task.context import RefreshContext
from refresh_task.display_pipeline import DisplayPipeline
from refresh_task.executor import RefreshExecutor
from refresh_task.health import PluginHealthTracker
from refresh_task.health_hooks import PluginHealthMixin
from refresh_task.housekeeping import RefreshHousekeeper
from refresh_task.loop_scheduling import _DEFAULT_REFRESH_STALL_TIMEOUT, SchedulingMixin
from refresh_task.refresh_cycle import RefreshCycleMixin
from refresh_task.scheduler import RefreshScheduler
from refresh_task.worker import (
    _get_mp_context,
    sweep_orphan_render_tempfiles,
)
from utils import blackout, crash_breadcrumb

# ``_DEFAULT_REFRESH_STALL_TIMEOUT`` is kept as a module attribute for callers
# that still reach it through this module.
__all__ = ["RefreshTask", "_DEFAULT_REFRESH_STALL_TIMEOUT"]

_sd_notify: Callable[[str], None] | None
try:
    from cysystemd.daemon import (
        Notification as _sd_Notification,
        notify as _sd_notify_raw,
    )

    def _sd_notify(_kind: str) -> None:
        # Adapter for the legacy string-based interface used elsewhere in this file.
        if _kind == "WATCHDOG=1":
            _sd_notify_raw(_sd_Notification.WATCHDOG)
        elif _kind == "READY=1":
            _sd_notify_raw(_sd_Notification.READY)

except Exception:
    _sd_notify = None

logger = logging.getLogger(__name__)


class RefreshTask(
    SchedulingMixin, CommandQueueMixin, RefreshCycleMixin, PluginHealthMixin
):
    """Handles the logic for refreshing the display using a background thread."""

    def __init__(self, device_config: Any, display_manager: Any) -> None:
        self.device_config = device_config
        self.display_manager = display_manager
        self.refresh_context = RefreshContext.from_config(device_config)

        self.thread: threading.Thread | None = None
        self.lock = threading.Lock()
        self.condition = threading.Condition(self.lock)
        self.running = False
        self.manual_update_requests: deque[ManualUpdateRequest] = deque(maxlen=50)
        self.recorder = refresh_recorder.RefreshRecorder(self.device_config)
        self.progress_bus = self.recorder.progress_bus
        self.event_bus = self.recorder.event_bus
        self.plugin_health: dict[str, dict[str, Any]] = {}
        self.scheduler = RefreshScheduler(
            device_config=self.device_config,
            condition=self.condition,
            manual_update_requests=self.manual_update_requests,
            get_current_datetime=self._get_current_datetime,
        )
        self.housekeeper = RefreshHousekeeper(
            device_config=self.device_config,
            display_manager=self.display_manager,
        )
        self.health_tracker = PluginHealthTracker(
            device_config=self.device_config,
            plugin_health=self.plugin_health,
        )
        self.display_pipeline = DisplayPipeline(
            display_manager=self.display_manager,
            housekeeper=self.housekeeper,
            recorder=self.recorder,
            update_plugin_health=self._update_plugin_health_positional,
        )
        self.executor = RefreshExecutor(
            device_config=self.device_config,
            refresh_context=self.refresh_context,
            recorder=self.recorder,
            plugin_timeout_seconds=self._plugin_timeout_seconds,
            zombie_owner=type(self),
            get_plugin_instance=lambda cfg: plugin_lookup.get_plugin_instance(cfg),
            mp_context_factory=lambda: _get_mp_context(),
        )
        self._executor_run_subprocess_attempt = self.executor.run_subprocess_attempt
        self._tick_count: int = 0
        self.watchdog_thread: threading.Thread | None = None
        # Monotonic timestamp of the moment the current refresh started, or
        # None while the loop is idle waiting for its next trigger.  Read by
        # the watchdog heartbeat to tell "working" from "wedged"; see
        # _watchdog_should_notify.  Plain attribute assignment is sufficient
        # synchronisation here — single writer, single reader, no read-modify.
        self._work_started_at: float | None = None
        self._watchdog_stall_logged: bool = False

    def _examine_previous_boot(self) -> None:
        """Attribute an unclean shutdown and quarantine whatever caused it.

        A breadcrumb still on disk means the previous run was killed mid-refresh
        rather than shutting down cleanly. Errors are swallowed: forensics must
        never be the reason the service fails to start.
        """
        try:
            breadcrumb = crash_breadcrumb.examine_boot()
        except Exception:  # noqa: BLE001  defensive — startup must not fail
            logger.warning("Could not examine previous boot", exc_info=True)
            return
        if breadcrumb is None:
            return
        try:
            self.health_tracker.quarantine_after_crash(breadcrumb)
        except Exception:  # noqa: BLE001  defensive — startup must not fail
            logger.warning("Could not quarantine after crash", exc_info=True)

    def start(self) -> None:
        """Starts the background thread for refreshing the display."""
        if not self.thread or not self.thread.is_alive():
            logger.info("Starting refresh task")
            # Clean up any render tempfiles left behind by a prior crash.
            # Harmless on tmpfs-backed /tmp (reboot already cleared them)
            # but keeps disk-backed /tmp installs from accumulating orphans
            # indefinitely.  Swallows all errors so a slow/unreadable tmpdir
            # can never block service startup.
            try:
                deleted, bytes_freed = sweep_orphan_render_tempfiles()
                if deleted:
                    logger.info(
                        "Swept %d orphan render tempfile(s), freed %d bytes",
                        deleted,
                        bytes_freed,
                    )
            except Exception as exc:  # noqa: BLE001  defensive — startup must not fail
                logger.warning("Orphan render tempfile sweep failed: %s", exc)
            self._examine_previous_boot()
            self.thread = threading.Thread(
                target=self._run, daemon=True, name="RefreshTask"
            )
            self.running = True
            self.thread.start()
            # JTN-596: separate thread keeps systemd watchdog fed independent of cycle.
            if _sd_notify is not None:
                self.watchdog_thread = threading.Thread(
                    target=self._watchdog_heartbeat_loop,
                    daemon=True,
                    name="WatchdogHeartbeat",
                )
                self.watchdog_thread.start()

    def stop(self) -> None:
        """Stops the refresh task by notifying the background thread to exit."""
        with self.condition:
            self.running = False
            while self.manual_update_requests:
                request = self.manual_update_requests.popleft()
                request.exception = RuntimeError(
                    "Refresh task stopped before request completed"
                )
                request.done.set()
            self.condition.notify_all()  # Wake the thread to let it exit
        if self.thread:
            logger.info("Stopping refresh task")
            self.thread.join(timeout=5)
            if self.thread.is_alive():
                logger.warning("Refresh task thread did not stop within timeout")

    @staticmethod
    def _notify_watchdog() -> None:
        """Send a WATCHDOG=1 keepalive notification to systemd, if available.

        The ``cysystemd`` import is optional; when the library is absent or the
        process is not running under systemd, this method is a no-op.  Errors
        from the notification call are caught and logged rather than propagated,
        so a watchdog hiccup never aborts the refresh loop.
        """
        RefreshScheduler.notify_watchdog(_sd_notify)

    def _run(self) -> None:
        """Background thread loop coordinating refresh operations."""
        while True:
            result = None
            try:
                self._notify_watchdog()
                result = self._wait_for_trigger()
                if result is None:
                    break

                playlist_manager, latest_refresh, current_dt, manual_request = result
                if self._handle_special_request(manual_request):
                    continue
                if manual_request is None and blackout.is_active(self.device_config):
                    logger.info("Blackout active; skipping scheduled refresh")
                    continue
                refresh_action, request_id = self._select_refresh_action(
                    playlist_manager, latest_refresh, current_dt, manual_request
                )

                if refresh_action:
                    # Mark work in flight so the watchdog heartbeat can tell a
                    # long-but-healthy refresh from a wedged one.  Cleared in
                    # `finally` so an exception mid-refresh returns the loop to
                    # the idle state rather than looking permanently stalled.
                    self._work_started_at = monotonic()
                    # Name the plugin in flight so a hard kill — OOM, segfault —
                    # can be attributed on the next start. Handled exceptions
                    # clear the breadcrumb on the way out; only an unhandled
                    # death leaves it behind, which is the signal we want.
                    try:
                        with crash_breadcrumb.trail(
                            "refresh",
                            plugin_id=refresh_action.get_plugin_id(),
                            instance=refresh_action.get_refresh_info().get(
                                "plugin_instance"
                            ),
                        ):
                            refresh_info, used_cached, metrics = self._perform_refresh(
                                refresh_action,
                                latest_refresh,
                                current_dt,
                                request_id=request_id,
                                manual_request=manual_request,
                            )
                    finally:
                        self._work_started_at = None
                        self._watchdog_stall_logged = False
                    if refresh_info is not None:
                        self._update_refresh_info(refresh_info, metrics, used_cached)
                    self._complete_manual_request(manual_request, metrics=metrics)

                self._tick_count += 1
                self._maybe_run_history_cleanup()

            except Exception as e:
                logger.exception("Exception during refresh")
                if result is not None:
                    self._complete_manual_request(result[-1], exception=e)

    @staticmethod
    def _timeout_msg(plugin_id: str, timeout_s: float) -> str:
        """Return a canonical timeout error message string."""
        return RefreshExecutor.timeout_msg(plugin_id, timeout_s)

    @staticmethod
    def _cleanup_subprocess(proc: Any, plugin_id: str) -> None:
        """Terminate a subprocess that is still alive after its timeout."""
        RefreshExecutor.cleanup_subprocess(proc, plugin_id)

    @staticmethod
    def _handle_process_result(
        result_queue: Any,
        proc: Any,
        plugin_id: str,
        attempt: int,
    ) -> tuple[Any, Any]:
        """Read and validate the result queue from a finished subprocess."""
        return RefreshExecutor.handle_process_result_payload(
            result_queue,
            proc,
            plugin_id,
            attempt,
        )

    def _run_subprocess_attempt(
        self,
        refresh_action: RefreshAction,
        plugin_config: Mapping[str, Any],
        current_dt: datetime,
        plugin_id: str,
        timeout_s: float,
        attempt: int,
    ) -> tuple[Any, Any]:
        """Spawn a subprocess for one plugin execution attempt."""
        return self._executor_run_subprocess_attempt(
            refresh_action,
            plugin_config,
            current_dt,
            plugin_id,
            timeout_s,
            attempt,
        )

    def _execute_with_policy(
        self,
        refresh_action: RefreshAction,
        plugin_config: Mapping[str, Any],
        current_dt: datetime,
        request_id: str | None = None,
    ) -> tuple[Any, Any]:
        """Run a plugin with the configured retry and isolation policy."""
        original_runner = self.executor.run_subprocess_attempt
        cast(Any, self.executor).run_subprocess_attempt = self._run_subprocess_attempt
        try:
            return self.executor.execute_with_policy(
                refresh_action,
                plugin_config,
                current_dt,
                request_id=request_id,
            )
        finally:
            cast(Any, self.executor).run_subprocess_attempt = original_runner

    # Class-level counter tracking threads that timed out but could not be stopped.
    # Python threads cannot be force-killed; the cancel event is internal
    # lifecycle bookkeeping that lets the worker decrement this count on exit.
    _zombie_thread_count: ClassVar[int] = 0
    _zombie_thread_lock: ClassVar[threading.Lock] = threading.Lock()

    @staticmethod
    def _make_inprocess_worker(
        refresh_action: RefreshAction,
        plugin_config: Mapping[str, Any],
        device_config: Any,
        current_dt: datetime,
        plugin_id: str,
    ) -> tuple[Callable[[], None], dict[str, Any], threading.Event]:
        """Return a ``(worker_fn, result_holder, cancel_event)`` tuple."""
        return RefreshExecutor.make_inprocess_worker_for(
            refresh_action=refresh_action,
            plugin_config=plugin_config,
            device_config=device_config,
            current_dt=current_dt,
            plugin_id=plugin_id,
            zombie_owner=RefreshTask,
            get_plugin_instance=lambda cfg: plugin_lookup.get_plugin_instance(cfg),
        )

    @staticmethod
    def _handle_thread_timeout(
        plugin_id: str, timeout_s: float, cancel_event: threading.Event
    ) -> TimeoutError:
        """Mark a timed-out worker thread as a zombie and return a TimeoutError."""
        return RefreshExecutor.handle_thread_timeout_for(
            plugin_id,
            timeout_s,
            cancel_event,
            zombie_owner=RefreshTask,
        )

    def _execute_inprocess(
        self,
        refresh_action: RefreshAction,
        plugin_config: Mapping[str, Any],
        current_dt: datetime,
    ) -> tuple[Any, Any]:
        """Run a plugin directly in the current process."""
        return self.executor.execute_inprocess(
            refresh_action, plugin_config, current_dt
        )
