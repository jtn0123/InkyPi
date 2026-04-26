"""RefreshTask — main coordinator for display refresh operations."""

import logging
import os
import queue
import threading
from collections import deque
from collections.abc import Callable, Mapping
from datetime import datetime
from time import perf_counter, sleep
from typing import Any, NoReturn, cast
from uuid import uuid4

from model import PlaylistManager, RefreshInfo
from plugins.plugin_registry import get_plugin_instance
from refresh_task import recorder as refresh_recorder
from refresh_task.actions import ManualUpdateRequest, PlaylistRefresh, RefreshAction
from refresh_task.context import RefreshContext
from refresh_task.display_pipeline import DisplayPipeline
from refresh_task.health import PluginHealthTracker
from refresh_task.housekeeping import RefreshHousekeeper
from refresh_task.scheduler import RefreshScheduler
from refresh_task.worker import (
    _execute_refresh_attempt_worker,
    _get_mp_context,
    _remote_exception,
    sweep_orphan_render_tempfiles,
)
from utils.image_utils import compute_image_hash
from utils.output_validator import OutputDimensionMismatch, validate_image_dimensions
from utils.plugin_errors import PermanentPluginError
from utils.progress import ProgressTracker, track_progress
from utils.time_utils import now_device_tz
from utils.webhooks import send_failure_webhook

_sd_notify: Callable[[str], None] | None
save_refresh_event = refresh_recorder.save_refresh_event
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

_PLUGIN_TIMEOUT_DEFAULTS_S = {
    # OpenAI/Google image generation routinely takes longer than the generic
    # 60s guard, especially when a prompt remix runs first.
    "ai_image": 180.0,
}
_MANUAL_WAIT_DEFAULTS_S = {
    # Wait for the generated image to be saved, not the slow e-paper write.
    # Keep this slightly above the plugin timeout so the caller sees the
    # plugin's real result instead of a queue wait timeout.
    "ai_image": 210.0,
}


class RefreshTask:
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
        self._tick_count: int = 0
        self.watchdog_thread: threading.Thread | None = None

    @staticmethod
    def _get_circuit_breaker_threshold() -> int:
        """Return the consecutive-failure threshold before a plugin is paused.

        Reads ``PLUGIN_FAILURE_THRESHOLD`` from the environment (default 5).
        """
        return int(PluginHealthTracker.circuit_breaker_threshold())

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
    def _watchdog_interval_seconds() -> float:
        """Half of WATCHDOG_USEC (set by systemd when WatchdogSec= is in the unit file).

        Defaults to 30s if WATCHDOG_USEC is unset (e.g. running outside systemd).
        """
        return float(RefreshScheduler.watchdog_interval_seconds())

    def _watchdog_heartbeat_loop(self) -> None:
        """Background loop that feeds the systemd watchdog at WatchdogSec/2 cadence.

        Decoupled from the refresh cycle so a long plugin_cycle_interval_seconds
        cannot stall the heartbeat (JTN-596).
        """
        self.scheduler.watchdog_heartbeat_loop(
            is_running=lambda: self.running,
            notify_watchdog=self._notify_watchdog,
            interval_seconds=self._watchdog_interval_seconds(),
        )

    @staticmethod
    def _notify_watchdog() -> None:
        """Send a WATCHDOG=1 keepalive notification to systemd, if available.

        The ``cysystemd`` import is optional; when the library is absent or the
        process is not running under systemd, this method is a no-op.  Errors
        from the notification call are caught and logged rather than propagated,
        so a watchdog hiccup never aborts the refresh loop.
        """
        RefreshScheduler.notify_watchdog(_sd_notify)

    def _complete_manual_request(
        self,
        manual_request: ManualUpdateRequest | None,
        metrics: dict[str, Any] | None = None,
        exception: BaseException | None = None,
    ) -> None:
        """Signal the waiting caller that a manual update request has finished.

        Sets both the ``done`` and ``image_saved`` events on *manual_request*
        so that any thread blocked in :meth:`manual_update` — whether it is
        waiting for the early "image on disk" signal (JTN-786) or for full
        completion — unblocks and inspects the outcome.

        Args:
            manual_request: A :class:`ManualUpdateRequest` to complete, or
                ``None`` (in which case this is a no-op).
            metrics: Optional timing/steps dict to attach to the request.
            exception: If set, the exception will be stored on the request so
                the waiting caller can re-raise it.
        """
        if manual_request is None:
            return
        if exception is not None:
            manual_request.exception = exception
        if metrics is not None:
            manual_request.metrics = metrics
        manual_request.done.set()
        # Also unblock anyone still waiting on image_saved — e.g. if the
        # refresh failed before the image could be persisted (generate error,
        # dimension mismatch) the API caller needs to see the exception
        # instead of timing out waiting for a signal that will never come.
        manual_request.image_saved.set()

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
                refresh_action, request_id = self._select_refresh_action(
                    playlist_manager, latest_refresh, current_dt, manual_request
                )

                if refresh_action:
                    refresh_info, used_cached, metrics = self._perform_refresh(
                        refresh_action,
                        latest_refresh,
                        current_dt,
                        request_id=request_id,
                        manual_request=manual_request,
                    )
                    if refresh_info is not None:
                        self._update_refresh_info(refresh_info, metrics, used_cached)
                    self._complete_manual_request(manual_request, metrics=metrics)

                self._tick_count += 1
                self._maybe_run_history_cleanup()

            except Exception as e:
                logger.exception("Exception during refresh")
                if result is not None:
                    self._complete_manual_request(result[-1], exception=e)

    # ------------------------------------------------------------------
    # History cleanup
    # ------------------------------------------------------------------

    _CLEANUP_INTERVAL_TICKS = 10

    def _maybe_run_history_cleanup(self) -> None:
        """Run history cleanup every N ticks (non-blocking; errors are logged only)."""
        self.housekeeper.maybe_run_history_cleanup(
            tick_count=self._tick_count,
            cleanup_interval_ticks=self._CLEANUP_INTERVAL_TICKS,
        )

    def _wait_for_trigger(
        self,
    ) -> tuple[Any, Any, datetime, ManualUpdateRequest | None] | None:
        """Wait for the next refresh trigger while holding the condition lock.

        The method blocks for ``plugin_cycle_interval_seconds`` or until notified
        of a manual update. It returns the contextual objects required for the
        refresh cycle or ``None`` if the task was stopped.

        Threading:
            Acquires ``self.condition`` and releases it before returning.
        """
        return cast(
            tuple[Any, Any, datetime, ManualUpdateRequest | None] | None,
            self.scheduler.wait_for_trigger(is_running=lambda: self.running),
        )

    def _select_refresh_action(
        self,
        playlist_manager: Any,
        latest_refresh: Any,
        current_dt: datetime,
        manual_request: ManualUpdateRequest | None,
    ) -> tuple[RefreshAction | None, str | None]:
        """Determine which refresh action to perform.

        If ``manual_action`` is provided it is returned immediately. Otherwise,
        the next eligible plugin is selected based on playlists.

        Threading:
            No locks are held during execution.
        """
        refresh_action = None
        request_id = None
        if manual_request is not None:
            logger.info("Manual update requested")
            refresh_action = manual_request.refresh_action
            request_id = manual_request.request_id
        else:
            if self.device_config.get_config("log_system_stats"):
                self.log_system_stats()
            logger.info(
                f"Running interval refresh check. | current_time: {current_dt.strftime('%Y-%m-%d %H:%M:%S')}"
            )
            playlist, plugin_instance = self._determine_next_plugin(
                playlist_manager, latest_refresh, current_dt
            )
            if playlist is not None and plugin_instance:
                refresh_action = PlaylistRefresh(playlist, plugin_instance)
        return refresh_action, request_id

    def _perform_refresh(
        self,
        refresh_action: RefreshAction,
        latest_refresh: Any,
        current_dt: datetime,
        request_id: str | None = None,
        manual_request: ManualUpdateRequest | None = None,
    ) -> tuple[dict[str, Any] | None, bool, dict[str, Any]]:
        """Execute the refresh action and update the display if needed.

        Returns a tuple ``(refresh_info, used_cached, metrics)`` where
        ``refresh_info`` is a dictionary with metadata, ``used_cached`` indicates
        whether the image was unchanged, and ``metrics`` contains timing data.

        Threading:
            Must be called without holding ``self.condition``.
        """
        plugin_config = self.device_config.get_plugin(refresh_action.get_plugin_id())
        if plugin_config is None:
            logger.error(
                f"Plugin config not found for '{refresh_action.get_plugin_id()}'."
            )
            return None, False, {}

        isolated_plugins = self.device_config.get_config("isolated_plugins", default=[])
        if (
            isinstance(isolated_plugins, list)
            and refresh_action.get_plugin_id() in isolated_plugins
        ):
            raise RuntimeError(
                f"Plugin '{refresh_action.get_plugin_id()}' is currently isolated/disabled."
            )

        _t_req_start = perf_counter()
        # Correlate this refresh with a benchmark id so parallel stage events can attach
        benchmark_id = self.recorder.refresh_id(request_id)
        plugin_id = refresh_action.get_plugin_id()
        instance_name = refresh_action.get_refresh_info().get("plugin_instance")

        # Plugin lifecycle: generate_start
        logger.info(
            "plugin_lifecycle: generate_start",
            extra={
                "stage": "generate_start",
                "plugin_id": plugin_id,
                "instance": instance_name,
                "refresh_id": benchmark_id,
                "request_id": request_id,
            },
        )
        _t_gen_start = perf_counter()
        tracker: ProgressTracker
        with track_progress() as tracker:
            stage_t0 = perf_counter()
            self.recorder.publish_running(
                plugin_id=plugin_id,
                instance=instance_name,
                refresh_id=benchmark_id,
                request_id=request_id,
            )
            try:
                image, plugin_meta = self._execute_with_policy(
                    refresh_action,
                    plugin_config,
                    current_dt,
                    request_id=request_id,
                )
            except Exception as exc:
                retain_path = self._stale_display_path()
                # JTN-779: log the full exception class + message so operators
                # can diagnose.  The user-visible fallback image is sanitised
                # via utils.fallback_image.sanitize_error_message.
                logger.error(
                    "plugin_lifecycle: failure | plugin_id=%s instance=%s retained_display=%s error_class=%s error=%s",
                    plugin_id,
                    instance_name,
                    bool(retain_path),
                    type(exc).__name__,
                    exc,
                )
                self._update_plugin_health(
                    plugin_id=plugin_id,
                    instance=instance_name,
                    ok=False,
                    metrics={"retained_display": bool(retain_path)},
                    error=str(exc),
                )
                self.recorder.publish_error(
                    plugin_id=plugin_id,
                    instance=instance_name,
                    refresh_id=benchmark_id,
                    request_id=request_id,
                    error=str(exc),
                    retained_display=bool(retain_path),
                    plugin_failed=True,
                )
                self._push_fallback_image(
                    plugin_id=plugin_id,
                    instance_name=instance_name,
                    exc=exc,
                    plugin_config=plugin_config,
                    refresh_action=refresh_action,
                )
                raise
            self.recorder.save_stage(
                benchmark_id,
                "generate_image",
                int((perf_counter() - stage_t0) * 1000),
            )
        generate_ms = int((perf_counter() - _t_gen_start) * 1000)
        # Plugin lifecycle: generate_complete
        logger.info(
            "plugin_lifecycle: generate_complete",
            extra={
                "stage": "generate_complete",
                "plugin_id": plugin_id,
                "instance": instance_name,
                "duration_ms": generate_ms,
                "refresh_id": benchmark_id,
                "request_id": request_id,
            },
        )
        if image is None:
            raise RuntimeError("Plugin returned None image; cannot refresh display.")

        # Validate dimensions before doing anything expensive (hash / display push).
        expected_w, expected_h = self.device_config.get_resolution()
        try:
            image = validate_image_dimensions(
                image,
                expected_w,
                expected_h,
                plugin_id=plugin_id,
            )
        except OutputDimensionMismatch as exc:
            logger.error(
                "plugin_lifecycle: dimension_mismatch | plugin_id=%s instance=%s "
                "expected=%dx%d actual=%dx%d — skipping display push",
                plugin_id,
                instance_name,
                exc.expected[0],
                exc.expected[1],
                exc.actual[0],
                exc.actual[1],
            )
            self._update_plugin_health(
                plugin_id=plugin_id,
                instance=instance_name,
                ok=False,
                metrics={"retained_display": bool(self._stale_display_path())},
                error=str(exc),
            )
            self.recorder.publish_error(
                plugin_id=plugin_id,
                instance=instance_name,
                refresh_id=benchmark_id,
                request_id=request_id,
                error=str(exc),
                retained_display=bool(self._stale_display_path()),
                plugin_failed=True,
            )
            return None, False, {}

        image_hash = compute_image_hash(image)

        refresh_info = refresh_action.get_refresh_info()
        if plugin_meta:
            refresh_info.update({"plugin_meta": plugin_meta})

        refresh_info.update(
            {"refresh_time": current_dt.isoformat(), "image_hash": image_hash}
        )
        used_cached = image_hash == latest_refresh.image_hash
        display_duration_ms, preprocess_ms = self._push_or_skip_display(
            used_cached=used_cached,
            image=image,
            plugin_config=plugin_config,
            refresh_action=refresh_action,
            refresh_info=cast(Any, refresh_info),
            benchmark_id=benchmark_id,
            plugin_id=plugin_id,
            instance_name=instance_name,
            request_id=request_id,
            manual_request=manual_request,
        )

        request_ms = int((perf_counter() - _t_req_start) * 1000)
        metrics = {
            "request_ms": request_ms,
            "display_ms": display_duration_ms,
            "generate_ms": generate_ms,
            "preprocess_ms": preprocess_ms,
            "steps": tracker.get_steps(),
        }
        self._save_benchmark(benchmark_id, refresh_info, used_cached, metrics)
        self._update_plugin_health(
            plugin_id=plugin_id,
            instance=instance_name,
            ok=True,
            metrics=metrics,
            error=None,
        )
        self.recorder.publish_done(
            plugin_id=plugin_id,
            instance=instance_name,
            refresh_id=benchmark_id,
            request_id=request_id,
            metrics=metrics,
            duration_ms=request_ms,
        )
        return refresh_info | {"benchmark_id": benchmark_id}, used_cached, metrics

    def _push_or_skip_display(
        self,
        *,
        used_cached: bool,
        image: Any,
        plugin_config: dict[str, Any],
        refresh_action: Any,
        refresh_info: Mapping[str, Any],
        benchmark_id: str | None,
        plugin_id: str,
        instance_name: str | None,
        request_id: str | None,
        manual_request: ManualUpdateRequest | None,
    ) -> tuple[int | None, int | None]:
        """Push the image to the display, or skip when the cache is warm.

        Returns ``(display_duration_ms, preprocess_ms)``.  Also unblocks the
        manual-update waiter on the cached path since the image-on-disk
        invariant still holds (JTN-786).
        """
        if not used_cached:
            return self._push_to_display(
                image=image,
                plugin_config=plugin_config,
                refresh_action=refresh_action,
                refresh_info=refresh_info,
                benchmark_id=benchmark_id,
                plugin_id=plugin_id,
                instance_name=instance_name,
                request_id=request_id,
                manual_request=manual_request,
            )
        return self.display_pipeline.push_or_skip_display(
            used_cached=used_cached,
            image=image,
            plugin_config=plugin_config,
            refresh_action=refresh_action,
            refresh_info=refresh_info,
            benchmark_id=benchmark_id,
            plugin_id=plugin_id,
            instance_name=instance_name,
            request_id=request_id,
            manual_request=manual_request,
        )

    def _push_to_display(
        self,
        image: Any,
        plugin_config: Mapping[str, Any],
        refresh_action: Any,
        refresh_info: Mapping[str, Any],
        benchmark_id: str | None,
        plugin_id: str,
        instance_name: str | None,
        request_id: str | None,
        manual_request: ManualUpdateRequest | None = None,
    ) -> tuple[int | None, int | None]:
        """Push image to the display hardware and record benchmark stages."""
        return self.display_pipeline.push_to_display(
            image=image,
            plugin_config=plugin_config,
            refresh_action=refresh_action,
            refresh_info=refresh_info,
            benchmark_id=benchmark_id,
            plugin_id=plugin_id,
            instance_name=instance_name,
            request_id=request_id,
            manual_request=manual_request,
        )

    def _save_benchmark(
        self,
        benchmark_id: str,
        refresh_info: Mapping[str, Any],
        used_cached: bool,
        metrics: Mapping[str, Any],
    ) -> None:
        """Persist a refresh_event row best-effort."""
        self.recorder.save_refresh(
            refresh_id=benchmark_id,
            refresh_info=refresh_info,
            used_cached=used_cached,
            metrics=metrics,
        )

    def _stale_display_path(self) -> str | None:
        """Return the path to an existing display image file, or ``None``.

        Checks ``processed_image_file`` first, then ``current_image_file``.
        Used to detect whether the display currently shows stale content that
        can be retained when a plugin refresh fails.

        Returns:
            An absolute path string if an image file exists, otherwise ``None``.
        """
        return self.housekeeper.stale_display_path()

    def _push_fallback_image(
        self,
        plugin_id: str,
        instance_name: str | None,
        exc: BaseException,
        plugin_config: Mapping[str, Any],
        refresh_action: Any,
    ) -> None:
        """Render and push an error-card fallback image to the display.

        Called when ``generate_image()`` raises so the user sees *something*
        changed rather than stale content.  Best-effort: any error here is
        logged but never re-raised.
        """
        self.display_pipeline.push_fallback_image(
            plugin_id=plugin_id,
            instance_name=instance_name,
            exc=exc,
            plugin_config=plugin_config,
            refresh_action=refresh_action,
        )

    def _update_refresh_info(
        self,
        refresh_info: Mapping[str, Any],
        metrics: Mapping[str, Any],
        used_cached: bool,
    ) -> None:
        """Persist the latest refresh information to the device config.

        Threading:
            Should be invoked without holding ``self.condition``.
        """
        self.device_config.refresh_info = RefreshInfo(
            **refresh_info,
            request_ms=metrics.get("request_ms"),
            display_ms=metrics.get("display_ms"),
            generate_ms=metrics.get("generate_ms"),
            preprocess_ms=metrics.get("preprocess_ms"),
            used_cached=used_cached,
        )
        self.device_config.write_config()

    def _update_plugin_health_positional(
        self,
        plugin_id: str,
        instance: str | None,
        ok: bool,
        metrics: Mapping[str, Any] | None,
        error: str | None,
    ) -> None:
        """Positional adapter for collaborators that update plugin health."""
        self._update_plugin_health(
            plugin_id=plugin_id,
            instance=instance,
            ok=ok,
            metrics=dict(metrics) if metrics is not None else None,
            error=error,
        )

    def _enqueue_manual_request(self, refresh_action: Any) -> ManualUpdateRequest:
        """Create and queue a ManualUpdateRequest; wake the background thread."""
        request = ManualUpdateRequest(str(uuid4()), refresh_action)
        with self.condition:
            if (
                self.manual_update_requests.maxlen is not None
                and len(self.manual_update_requests)
                >= self.manual_update_requests.maxlen
            ):
                raise RuntimeError(
                    "Manual update queue is full. Please wait for pending requests to complete."
                )
            self.recorder.publish_queued(
                plugin_id=refresh_action.get_plugin_id(),
                request_id=request.request_id,
            )
            self.manual_update_requests.append(request)
            self.condition.notify_all()
        return request

    def _handle_manual_update_timeout(
        self,
        request: ManualUpdateRequest,
        refresh_action: Any,
        wait_s: float,
    ) -> NoReturn:
        """Remove the request from the queue and raise a canonical TimeoutError."""
        with self.condition:
            try:
                self.manual_update_requests.remove(request)
            except ValueError:
                pass
        timeout_exc = TimeoutError(f"Manual update timed out after {int(wait_s)}s")
        self._update_plugin_health(
            plugin_id=refresh_action.get_plugin_id(),
            instance=refresh_action.get_refresh_info().get("plugin_instance"),
            ok=False,
            metrics=None,
            error=str(timeout_exc),
        )
        self.recorder.publish_error(
            plugin_id=refresh_action.get_plugin_id(),
            request_id=request.request_id,
            error=str(timeout_exc),
        )
        raise timeout_exc

    def _resolve_completed_request(
        self, request: ManualUpdateRequest, refresh_action: Any
    ) -> dict[str, Any] | None:
        """Return metrics or raise the stored exception for a finished request."""
        exc = request.exception
        if exc is None:
            return cast(dict[str, Any], request.metrics)
        self.recorder.publish_error(
            plugin_id=refresh_action.get_plugin_id(),
            request_id=request.request_id,
            error=str(exc),
        )
        if isinstance(exc, BaseException):
            raise exc
        raise RuntimeError(str(exc))

    @staticmethod
    def _plugin_env_suffix(plugin_id: str) -> str:
        return "".join(ch if ch.isalnum() else "_" for ch in plugin_id).upper()

    @classmethod
    def _env_seconds_with_precedence(
        cls,
        plugin_id: str,
        env_key: str,
        defaults: Mapping[str, float],
    ) -> float:
        suffix = cls._plugin_env_suffix(plugin_id)
        specific_key = f"{env_key}_{suffix}"
        if specific_key in os.environ:
            return float(os.getenv(specific_key) or "60")
        if env_key in os.environ:
            return float(os.getenv(env_key) or "60")
        return defaults.get(plugin_id, 60.0)

    @classmethod
    def _plugin_timeout_seconds(cls, plugin_id: str) -> float:
        return cls._env_seconds_with_precedence(
            plugin_id,
            "INKYPI_PLUGIN_TIMEOUT_S",
            _PLUGIN_TIMEOUT_DEFAULTS_S,
        )

    @classmethod
    def _manual_update_wait_seconds(cls, plugin_id: str) -> float:
        return cls._env_seconds_with_precedence(
            plugin_id,
            "INKYPI_MANUAL_UPDATE_WAIT_S",
            _MANUAL_WAIT_DEFAULTS_S,
        )

    def manual_update(self, refresh_action: RefreshAction) -> dict[str, Any] | None:
        """Manually triggers an update for the specified plugin id and plugin settings by notifying the background process."""
        if not self.running:
            logger.warning(
                "Background refresh task is not running, unable to do a manual update"
            )
            return None

        request = self._enqueue_manual_request(refresh_action)

        wait_s = self._manual_update_wait_seconds(refresh_action.get_plugin_id())
        # JTN-786: wait for the image to hit disk rather than for the full
        # refresh (including the slow e-paper SPI write) to finish.
        # ``image_saved`` is also set by ``_complete_manual_request`` on any
        # terminal outcome, so this wait unblocks on error/cached paths too —
        # the post-wait branches below distinguish them.
        signalled = request.image_saved.wait(timeout=max(0.0, wait_s))
        if not signalled:
            self._handle_manual_update_timeout(request, refresh_action, wait_s)

        # Small grace period: if the display hardware is fast (mock display,
        # cached image, unit tests) ``done`` will fire almost immediately
        # after ``image_saved``.  Prefer the richer full-refresh metrics when
        # they're readily available so well-behaved callers still see
        # ``request_ms`` etc. without a second round-trip to ``/refresh-info``.
        grace_s = float(
            os.getenv("INKYPI_MANUAL_UPDATE_DONE_GRACE_S", "0.25") or "0.25"
        )
        if grace_s > 0:
            request.done.wait(timeout=grace_s)

        if request.done.is_set():
            return self._resolve_completed_request(request, refresh_action)

        # Image is on disk but the hardware write is still in progress —
        # return early so the caller is not blocked on slow SPI writes.
        # ``/refresh-info`` will reflect the full metrics once the background
        # thread finishes.
        logger.info(
            "manual_update: returning after image_saved; "
            "display hardware write continues asynchronously | plugin_id=%s request_id=%s",
            refresh_action.get_plugin_id(),
            request.request_id,
        )
        return request.image_saved_metrics or {"stage": "image_saved"}

    @staticmethod
    def _timeout_msg(plugin_id: str, timeout_s: float) -> str:
        """Return a canonical timeout error message string."""
        return f"Plugin '{plugin_id}' timed out after {int(timeout_s)}s"

    @staticmethod
    def _cleanup_subprocess(proc: Any, plugin_id: str) -> None:
        """Terminate a subprocess that is still alive after its timeout.

        JTN-S2: ``killpg(SIGKILL)`` the worker's process group up front,
        before any terminate/join dance.  The worker calls ``os.setsid()``
        at startup, so it is a session leader and its pgid equals its
        pid; the chromium screenshot subprocess plus chromium's zygote /
        renderer / utility descendants all inherit that same pgid.  Doing
        the killpg BEFORE checking ``proc.is_alive()`` is critical — if
        we only killpg "when the worker survives terminate", a worker
        that exits gracefully on SIGTERM would skip the killpg entirely
        and leave its chromium descendants reparented to PID 1.  That
        was the on-device leak: 9 chromium processes survived per
        timeout because the worker's own SIGTERM handler returned cleanly.

        ``getpgid(0) != pgid`` guards against signaling our own group in
        the (impossible-in-production) case where the worker never made
        it past setsid.
        """
        import signal as _signal

        # 1. Take down the whole worker session up front — catches the
        #    chromium tree before any of it can be reparented.
        #    ``getpgid``/``killpg`` are POSIX-only; ``getattr`` guards the
        #    Windows case so we silently fall through to the
        #    terminate()/kill() fallback instead of raising AttributeError
        #    (which the except below would not catch).
        getpgid = getattr(os, "getpgid", None)
        killpg = getattr(os, "killpg", None)
        if callable(getpgid) and callable(killpg):
            try:
                pgid = getpgid(proc.pid)
                # Signal is scoped to the worker's own session (the worker
                # called ``setsid`` at startup) and guarded against our
                # own pgid, so the only processes affected are the ones
                # this refresh task spawned.  SonarCloud python:S4828.
                if pgid != getpgid(0):
                    killpg(pgid, _signal.SIGKILL)  # NOSONAR
            except OSError:
                # ProcessLookupError / PermissionError are OSError subclasses.
                pass

        # 2. Standard terminate/kill dance to reap the worker entry.
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

    @staticmethod
    def _handle_process_result(
        result_queue: Any,
        proc: Any,
        plugin_id: str,
        attempt: int,
    ) -> tuple[Any, Any]:
        """Read and validate the result queue from a finished subprocess.

        Returns ``(image, metadata)`` on success, or ``(None, exception)``
        on failure.  Raises ``RuntimeError`` directly for unrecoverable exit
        conditions.
        """
        try:
            payload = result_queue.get_nowait()
        except queue.Empty:
            payload = None
        if not payload:
            if proc.exitcode == 0:
                raise RuntimeError(
                    f"Plugin '{plugin_id}' exited without returning a result"
                )
            raise RuntimeError(f"Plugin '{plugin_id}' exited with code {proc.exitcode}")
        if payload.get("ok"):
            from PIL import Image

            # Worker writes PNG to a tempfile and passes the path via the
            # queue (see worker.py for the pipe-buffer-deadlock rationale).
            # Load into memory with image.copy() so we can unlink the
            # underlying file immediately; the in-memory PIL.Image does
            # not retain a reference to it.
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
        return None, _remote_exception(
            str(payload.get("error_type") or "RuntimeError"),
            str(payload.get("error_message") or "unknown error"),
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
        """Spawn a subprocess for one plugin execution attempt.

        Returns ``(image, exc_or_meta)`` on success, or raises/returns an exception
        as the second element when the attempt fails.
        """
        ctx = _get_mp_context()
        result_queue = ctx.Queue(maxsize=1)
        proc = cast(Any, ctx).Process(
            target=_execute_refresh_attempt_worker,
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
                self._cleanup_subprocess(proc, plugin_id)
                return None, TimeoutError(self._timeout_msg(plugin_id, timeout_s))
            return self._handle_process_result(result_queue, proc, plugin_id, attempt)
        except TimeoutError:
            return None, TimeoutError(self._timeout_msg(plugin_id, timeout_s))
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

    def _execute_with_policy(
        self,
        refresh_action: RefreshAction,
        plugin_config: Mapping[str, Any],
        current_dt: datetime,
        request_id: str | None = None,
    ) -> tuple[Any, Any]:
        """Run a plugin with the configured retry and isolation policy.

        Reads environment variables to determine the execution strategy:
        - ``INKYPI_PLUGIN_ISOLATION``: ``"process"`` (default) spawns a
          subprocess per attempt; ``"none"`` runs in-process via a worker thread.
        - ``INKYPI_PLUGIN_RETRY_MAX``: Maximum number of retries (default 1).
        - ``INKYPI_PLUGIN_RETRY_BACKOFF_MS``: Sleep between retries (default 500 ms).
        - ``INKYPI_PLUGIN_TIMEOUT_S``: Per-attempt timeout in seconds (default 60).

        Args:
            refresh_action: The :class:`RefreshAction` describing what to run.
            plugin_config: The raw plugin configuration dict from device.json.
            current_dt: The current device-timezone datetime used by the plugin.
            request_id: Optional correlation ID for logging and benchmarking.

        Returns:
            A ``(image, plugin_meta)`` tuple where *image* is a
            ``PIL.Image.Image`` and *plugin_meta* is optional metadata from the
            plugin.

        Raises:
            TimeoutError: If all attempts time out.
            RuntimeError: If all attempts fail with an unrecoverable error.
        """
        plugin_id = refresh_action.get_plugin_id()
        retries = int(os.getenv("INKYPI_PLUGIN_RETRY_MAX", "1") or "1")
        backoff_ms = int(os.getenv("INKYPI_PLUGIN_RETRY_BACKOFF_MS", "500") or "500")
        timeout_s = self._plugin_timeout_seconds(plugin_id)
        attempts = max(1, retries + 1)

        # When isolation is disabled (e.g. in tests or on constrained devices),
        # run the plugin directly in the current process instead of spawning a
        # subprocess.  This avoids pickling issues that arise with the ``spawn``
        # and ``forkserver`` multiprocessing start methods on Linux.
        isolation = (os.getenv("INKYPI_PLUGIN_ISOLATION") or "process").strip().lower()
        if isolation == "none":
            return self._execute_inprocess(refresh_action, plugin_config, current_dt)

        last_exc: BaseException | None = None
        for attempt in range(1, attempts + 1):
            logger.info(
                "plugin_lifecycle: attempt_start | plugin_id=%s attempt=%s attempts=%s timeout_s=%s",
                plugin_id,
                attempt,
                attempts,
                timeout_s,
            )
            image, exc_or_meta = self._run_subprocess_attempt(
                refresh_action, plugin_config, current_dt, plugin_id, timeout_s, attempt
            )
            if image is not None:
                return image, exc_or_meta

            last_exc = exc_or_meta
            if isinstance(last_exc, TimeoutError):
                last_exc = TimeoutError(self._timeout_msg(plugin_id, timeout_s))

            # JTN-778: permanent errors (bad URL, malformed config) will fail
            # identically on retry — skip remaining attempts to avoid burning
            # CPU and log lines on every scheduled playlist tick.
            if isinstance(last_exc, PermanentPluginError):
                logger.info(
                    "plugin_lifecycle: attempt_terminal | plugin_id=%s attempt=%s/%s error=%s",
                    plugin_id,
                    attempt,
                    attempts,
                    last_exc,
                )
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

    # Class-level counter tracking threads that timed out but could not be stopped.
    # Python threads cannot be force-killed; cooperative plugins should check the
    # cancel_event passed via result_holder["cancel_event"] and exit early.
    _zombie_thread_count: int = 0
    _zombie_thread_lock: threading.Lock = threading.Lock()

    @staticmethod
    def _make_inprocess_worker(
        refresh_action: RefreshAction,
        plugin_config: Mapping[str, Any],
        device_config: Any,
        current_dt: datetime,
        plugin_id: str,
    ) -> tuple[Callable[[], None], dict[str, Any], threading.Event]:
        """Return a ``(worker_fn, result_holder, cancel_event)`` tuple.

        The returned *worker_fn* is suitable for ``threading.Thread(target=...)``.
        """
        result_holder: dict[str, Any] = {}
        cancel_event = threading.Event()
        result_holder["cancel_event"] = cancel_event

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
                    with RefreshTask._zombie_thread_lock:
                        RefreshTask._zombie_thread_count = max(
                            0, RefreshTask._zombie_thread_count - 1
                        )
                    logging.getLogger(__name__).info(
                        "Zombie thread for plugin '%s' has finished. "
                        "Active zombie threads: %d",
                        plugin_id,
                        RefreshTask._zombie_thread_count,
                    )

        return _worker, result_holder, cancel_event

    @staticmethod
    def _handle_thread_timeout(
        plugin_id: str, timeout_s: float, cancel_event: threading.Event
    ) -> TimeoutError:
        """Mark a timed-out worker thread as a zombie and return a TimeoutError."""
        cancel_event.set()
        with RefreshTask._zombie_thread_lock:
            RefreshTask._zombie_thread_count += 1
            zombie_count = RefreshTask._zombie_thread_count
        logging.getLogger(__name__).warning(
            "Plugin '%s' timed out after %ds — cancellation event set. "
            "Thread cannot be force-killed; it will run until completion. "
            "Active zombie threads: %d",
            plugin_id,
            int(timeout_s),
            zombie_count,
        )
        return TimeoutError(f"Plugin '{plugin_id}' timed out after {int(timeout_s)}s")

    def _execute_inprocess(
        self,
        refresh_action: RefreshAction,
        plugin_config: Mapping[str, Any],
        current_dt: datetime,
    ) -> tuple[Any, Any]:
        """Run a plugin directly in the current process (no subprocess isolation).

        Used when ``INKYPI_PLUGIN_ISOLATION=none`` to avoid pickling constraints
        imposed by the ``spawn``/``forkserver`` multiprocessing start methods.

        Supports retries and timeouts via a worker thread so the behaviour
        mirrors the subprocess path as closely as possible.

        On timeout a ``threading.Event`` (``cancel_event``) is set so that
        cooperative plugins can detect cancellation and exit early.  Because
        Python threads cannot be force-killed, a timed-out thread becomes a
        "zombie" daemon thread.  The class-level ``_zombie_thread_count``
        counter is incremented for each such thread and decremented when the
        thread eventually finishes, enabling monitoring.
        """
        plugin_id = refresh_action.get_plugin_id()
        retries = int(os.getenv("INKYPI_PLUGIN_RETRY_MAX", "1") or "1")
        backoff_ms = int(os.getenv("INKYPI_PLUGIN_RETRY_BACKOFF_MS", "500") or "500")
        timeout_s = self._plugin_timeout_seconds(plugin_id)
        attempts = max(1, retries + 1)

        last_exc: BaseException | None = None
        for attempt in range(1, attempts + 1):
            _worker, result_holder, cancel_event = self._make_inprocess_worker(
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
                last_exc = self._handle_thread_timeout(
                    plugin_id, timeout_s, cancel_event
                )
            elif "error" in result_holder:
                last_exc = result_holder["error"]
            else:
                return result_holder["image"], result_holder.get("meta")

            # JTN-778: permanent errors are terminal — skip retries.
            if isinstance(last_exc, PermanentPluginError):
                logger.info(
                    "plugin_lifecycle: attempt_terminal | plugin_id=%s attempt=%s/%s error=%s",
                    plugin_id,
                    attempt,
                    attempts,
                    last_exc,
                )
                raise last_exc

            if attempt < attempts:
                sleep(max(0.0, backoff_ms / 1000.0))

        if last_exc is not None:
            raise last_exc
        raise RuntimeError(f"Plugin '{plugin_id}' failed with unknown error")

    def _update_plugin_health(
        self,
        plugin_id: str,
        instance: str | None,
        ok: bool,
        metrics: dict[str, Any] | None,
        error: str | None,
    ) -> None:
        """Update the in-memory health entry for a plugin and trigger circuit-breaker logic.

        Increments success or failure counters, stamps ``last_seen``, records
        timing metrics, and delegates to :meth:`_cb_on_success` or
        :meth:`_cb_on_failure` to manage the circuit-breaker state.

        Args:
            plugin_id: The unique plugin type identifier (e.g. ``"clock"``).
            instance: The named plugin instance within the playlist, or ``None``
                when the instance is unavailable.
            ok: ``True`` if the refresh succeeded; ``False`` on failure.
            metrics: Optional timing/steps dict to store on the health entry.
            error: Human-readable error string to store when *ok* is ``False``.
        """
        self.health_tracker.update(
            plugin_id=plugin_id,
            instance=instance,
            ok=ok,
            metrics=metrics,
            error=error,
            on_success=self._cb_on_success,
            on_failure=self._cb_on_failure,
        )

    def _cb_on_success(
        self, plugin_instance: Any, plugin_id: str, instance: str | None
    ) -> None:
        """Reset the circuit breaker on a successful refresh."""
        self.health_tracker.on_success(plugin_instance, plugin_id, instance)

    def _cb_on_failure(
        self, plugin_instance: Any, plugin_id: str, instance: str | None
    ) -> None:
        """Increment the failure counter and pause the plugin if threshold exceeded."""
        self.health_tracker.on_failure(
            plugin_instance,
            plugin_id,
            instance,
            webhook_sender=send_failure_webhook,
        )

    def reset_circuit_breaker(self, plugin_id: str, instance: str) -> bool:
        """Clear the paused state and failure counter for a plugin instance.

        Returns True if the instance was found and reset, False otherwise.
        """
        return bool(self.health_tracker.reset_circuit_breaker(plugin_id, instance))

    def get_health_snapshot(self) -> dict[str, Any]:
        return cast(dict[str, Any], self.health_tracker.snapshot())

    def signal_config_change(self) -> None:
        """Notify the background thread that config has changed (e.g., interval updated).

        Also rebuilds the ``RefreshContext`` snapshot so that subsequent
        subprocess launches pick up the latest configuration values.
        """
        self.refresh_context = RefreshContext.from_config(self.device_config)
        if self.running:
            with self.condition:
                self.condition.notify_all()

    def _get_current_datetime(self) -> datetime:
        """Retrieves the current datetime based on the device's configured timezone."""
        return now_device_tz(self.device_config)

    def _determine_next_plugin(
        self, playlist_manager: Any, latest_refresh_info: Any, current_dt: datetime
    ) -> tuple[Any | None, Any | None]:
        """Determines the next plugin to refresh based on the active playlist, plugin cycle interval, and current time."""
        playlist = playlist_manager.determine_active_playlist(current_dt)
        if not playlist:
            playlist_manager.active_playlist = None
            logger.info("No active playlist determined.")
            return None, None

        playlist_manager.active_playlist = playlist.name
        if not playlist.plugins:
            logger.info(f"Active playlist '{playlist.name}' has no plugins.")
            return None, None

        latest_refresh_dt = latest_refresh_info.get_refresh_datetime()
        # Allow per-playlist override; fallback to device-level interval
        plugin_cycle_interval = getattr(
            playlist, "cycle_interval_seconds", None
        ) or self.device_config.get_config(
            "plugin_cycle_interval_seconds", default=3600
        )
        should_refresh = PlaylistManager.should_refresh(
            latest_refresh_dt, plugin_cycle_interval, current_dt
        )

        if not should_refresh:
            # latest_refresh_dt is guaranteed non-None here because
            # PlaylistManager.should_refresh() returns True when input is None.
            latest_refresh_str = latest_refresh_dt.strftime("%Y-%m-%d %H:%M:%S")
            logger.info(
                f"Not time to update display. | latest_update: {latest_refresh_str} | plugin_cycle_interval: {plugin_cycle_interval}"
            )
            return None, None

        # Use eligibility-aware selection; skip circuit-breaker paused plugins
        attempts_left = len(playlist.plugins)
        while attempts_left > 0:
            plugin = playlist.get_next_eligible_plugin(current_dt)
            if plugin is None:
                break
            if getattr(plugin, "paused", False):
                logger.info(
                    "plugin circuit_breaker: skipping paused plugin | plugin_id=%s instance=%s",
                    plugin.plugin_id,
                    plugin.name,
                )
                attempts_left -= 1
                continue
            logger.info(
                f"Determined next plugin. | active_playlist: {playlist.name} | plugin_instance: {plugin.name}"
            )
            return playlist, plugin

        logger.info(
            f"No eligible plugin to display in active playlist '{playlist.name}'."
        )
        return None, None

    def log_system_stats(self) -> None:
        """Log a snapshot of CPU, memory, disk, swap, and network I/O metrics.

        Uses ``psutil`` to gather system statistics.  If ``psutil`` is not
        installed the method logs a warning and returns without raising.
        Statistics are emitted at INFO level and include load averages where
        the platform supports them.
        """
        try:
            import psutil
        except Exception:
            logger.info("System Stats: psutil not available")
            return

        metrics = {
            # interval=None ensures a non-blocking snapshot of CPU usage
            "cpu_percent": psutil.cpu_percent(interval=None),
            "memory_percent": psutil.virtual_memory().percent,
            "disk_percent": psutil.disk_usage("/").percent,
            "swap_percent": psutil.swap_memory().percent,
            "net_io": {
                "bytes_sent": psutil.net_io_counters().bytes_sent,
                "bytes_recv": psutil.net_io_counters().bytes_recv,
            },
        }

        try:
            metrics["load_avg_1_5_15"] = os.getloadavg()
        except (OSError, AttributeError):
            metrics["load_avg_1_5_15"] = None

        logger.info(f"System Stats: {metrics}")
