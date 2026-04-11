"""RefreshTask — main coordinator for display refresh operations."""

import io
import logging
import os
import queue
import threading
from collections import deque
from datetime import UTC, datetime
from time import perf_counter, sleep
from uuid import uuid4

from model import PlaylistManager, RefreshInfo
from plugins.plugin_registry import get_plugin_instance
from refresh_task.actions import ManualUpdateRequest, PlaylistRefresh
from refresh_task.worker import (
    _execute_refresh_attempt_worker,
    _get_mp_context,
    _remote_exception,
)
from utils.event_bus import get_event_bus
from utils.fallback_image import render_error_image
from utils.history_cleanup import cleanup_history
from utils.image_utils import compute_image_hash
from utils.metrics import (
    record_refresh_failure,
    record_refresh_success,
    set_circuit_breaker_open,
)
from utils.output_validator import OutputDimensionMismatch, validate_image_dimensions
from utils.progress import ProgressTracker, track_progress
from utils.progress_events import get_progress_bus
from utils.time_utils import now_device_tz
from utils.webhooks import send_failure_webhook

try:
    # Optional import; code must continue if unavailable
    from benchmarks.benchmark_storage import save_refresh_event, save_stage_event
except Exception:  # pragma: no cover

    def save_refresh_event(*args, **kwargs):  # type: ignore
        return None

    def save_stage_event(*args, **kwargs):  # type: ignore
        return None


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


class RefreshTask:
    """Handles the logic for refreshing the display using a background thread."""

    def __init__(self, device_config, display_manager):
        self.device_config = device_config
        self.display_manager = display_manager

        self.thread = None
        self.lock = threading.Lock()
        self.condition = threading.Condition(self.lock)
        self.running = False
        self.manual_update_requests: deque[ManualUpdateRequest] = deque(maxlen=50)
        self.progress_bus = get_progress_bus()
        self.event_bus = get_event_bus()
        self.plugin_health: dict[str, dict] = {}
        self._tick_count: int = 0
        self.watchdog_thread: threading.Thread | None = None

    @staticmethod
    def _get_circuit_breaker_threshold() -> int:
        """Return the consecutive-failure threshold before a plugin is paused.

        Reads ``PLUGIN_FAILURE_THRESHOLD`` from the environment (default 5).
        """
        try:
            return max(1, int(os.getenv("PLUGIN_FAILURE_THRESHOLD", "5") or "5"))
        except (ValueError, TypeError):
            return 5

    def start(self):
        """Starts the background thread for refreshing the display."""
        if not self.thread or not self.thread.is_alive():
            logger.info("Starting refresh task")
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

    def stop(self):
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
        try:
            usec = int(os.environ.get("WATCHDOG_USEC", "0"))
        except (ValueError, TypeError):
            usec = 0
        if usec <= 0:
            return 30.0
        return max(1.0, (usec / 1_000_000) / 2)

    def _watchdog_heartbeat_loop(self) -> None:
        """Background loop that feeds the systemd watchdog at WatchdogSec/2 cadence.

        Decoupled from the refresh cycle so a long plugin_cycle_interval_seconds
        cannot stall the heartbeat (JTN-596).
        """
        interval = self._watchdog_interval_seconds()
        while self.running:
            self._notify_watchdog()
            # Wake on stop() so shutdown is responsive.
            with self.condition:
                self.condition.wait(timeout=interval)

    @staticmethod
    def _notify_watchdog():
        """Send a WATCHDOG=1 keepalive notification to systemd, if available.

        The ``cysystemd`` import is optional; when the library is absent or the
        process is not running under systemd, this method is a no-op.  Errors
        from the notification call are caught and logged rather than propagated,
        so a watchdog hiccup never aborts the refresh loop.
        """
        if _sd_notify:
            try:
                _sd_notify("WATCHDOG=1")
            except Exception:
                logger.exception("Failed to notify systemd watchdog")

    @staticmethod
    def _complete_manual_request(manual_request, metrics=None, exception=None):
        """Signal the waiting caller that a manual update request has finished.

        Sets the ``done`` event on *manual_request* so the thread blocked in
        :meth:`manual_update` can unblock and inspect the outcome.

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

    def _run(self):
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
        if self._tick_count % self._CLEANUP_INTERVAL_TICKS != 0:
            return
        try:
            cfg = self.device_config.get_config("history_cleanup") or {}
            history_dir = self.device_config.history_image_dir
            cleanup_history(
                history_dir,
                max_age_days=int(cfg.get("max_age_days", 30)),
                max_count=int(cfg.get("max_count", 500)),
                min_free_bytes=int(cfg.get("min_free_bytes", 500_000_000)),
            )
        except Exception:
            logger.exception("history_cleanup: unexpected error during cleanup")

    def _wait_for_trigger(self):
        """Wait for the next refresh trigger while holding the condition lock.

        The method blocks for ``plugin_cycle_interval_seconds`` or until notified
        of a manual update. It returns the contextual objects required for the
        refresh cycle or ``None`` if the task was stopped.

        Threading:
            Acquires ``self.condition`` and releases it before returning.
        """
        with self.condition:
            sleep_time = self.device_config.get_config(
                "plugin_cycle_interval_seconds", default=60 * 60
            )
            if not self.running:
                return None
            if not self.manual_update_requests:
                self.condition.wait(timeout=sleep_time)
            if not self.running:
                return None

            playlist_manager = self.device_config.get_playlist_manager()
            latest_refresh = self.device_config.get_refresh_info()
            current_dt = self._get_current_datetime()
            manual_request = None
            if self.manual_update_requests:
                manual_request = self.manual_update_requests.popleft()
            return playlist_manager, latest_refresh, current_dt, manual_request

    def _select_refresh_action(
        self, playlist_manager, latest_refresh, current_dt, manual_request
    ):
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
            if plugin_instance:
                refresh_action = PlaylistRefresh(playlist, plugin_instance)
        return refresh_action, request_id

    def _perform_refresh(
        self, refresh_action, latest_refresh, current_dt, request_id=None
    ):
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
        benchmark_id = request_id or str(uuid4())
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
            self.progress_bus.publish(
                {
                    "state": "running",
                    "plugin_id": plugin_id,
                    "instance": instance_name,
                    "refresh_id": benchmark_id,
                    "request_id": request_id,
                }
            )
            self.event_bus.publish(
                "refresh_started",
                {
                    "plugin": instance_name or plugin_id,
                    "plugin_id": plugin_id,
                    "ts": datetime.now(UTC).isoformat(),
                },
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
                logger.error(
                    "plugin_lifecycle: failure | plugin_id=%s instance=%s retained_display=%s error=%s",
                    plugin_id,
                    instance_name,
                    bool(retain_path),
                    exc,
                )
                self._update_plugin_health(
                    plugin_id=plugin_id,
                    instance=instance_name,
                    ok=False,
                    metrics={"retained_display": bool(retain_path)},
                    error=str(exc),
                )
                self.progress_bus.publish(
                    {
                        "state": "error",
                        "plugin_id": plugin_id,
                        "instance": instance_name,
                        "refresh_id": benchmark_id,
                        "request_id": request_id,
                        "error": str(exc),
                        "retained_display": bool(retain_path),
                    }
                )
                self.event_bus.publish(
                    "plugin_failed",
                    {
                        "plugin": instance_name or plugin_id,
                        "plugin_id": plugin_id,
                        "error": str(exc),
                    },
                )
                self._push_fallback_image(
                    plugin_id=plugin_id,
                    instance_name=instance_name,
                    exc=exc,
                    plugin_config=plugin_config,
                    refresh_action=refresh_action,
                )
                raise
            try:
                save_stage_event(
                    self.device_config,
                    benchmark_id,
                    "generate_image",
                    int((perf_counter() - stage_t0) * 1000),
                )
            except Exception:
                logger.debug(
                    "Failed to save generate_image benchmark event", exc_info=True
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
            self.progress_bus.publish(
                {
                    "state": "error",
                    "plugin_id": plugin_id,
                    "instance": instance_name,
                    "refresh_id": benchmark_id,
                    "request_id": request_id,
                    "error": str(exc),
                    "retained_display": bool(self._stale_display_path()),
                }
            )
            self.event_bus.publish(
                "plugin_failed",
                {
                    "plugin": instance_name or plugin_id,
                    "plugin_id": plugin_id,
                    "error": str(exc),
                },
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
        if not used_cached:
            display_duration_ms, preprocess_ms = self._push_to_display(
                image,
                plugin_config,
                refresh_action,
                refresh_info,
                benchmark_id,
                plugin_id,
                instance_name,
                request_id,
            )
        else:
            display_duration_ms = preprocess_ms = None
            logger.info(
                f"Image already displayed, skipping refresh. | refresh_info: {refresh_info}"
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
        self.progress_bus.publish(
            {
                "state": "done",
                "plugin_id": plugin_id,
                "instance": instance_name,
                "refresh_id": benchmark_id,
                "request_id": request_id,
                "metrics": metrics,
            }
        )
        self.event_bus.publish(
            "refresh_complete",
            {
                "plugin": instance_name or plugin_id,
                "plugin_id": plugin_id,
                "duration_ms": request_ms,
            },
        )
        return refresh_info | {"benchmark_id": benchmark_id}, used_cached, metrics

    def _push_to_display(
        self,
        image,
        plugin_config,
        refresh_action,
        refresh_info,
        benchmark_id,
        plugin_id,
        instance_name,
        request_id,
    ):
        """Push image to the display hardware and record benchmark stages."""
        logger.info(f"Updating display. | refresh_info: {refresh_info}")
        history_meta = {
            "refresh_type": refresh_action.get_refresh_info().get("refresh_type"),
            "plugin_id": refresh_action.get_refresh_info().get("plugin_id"),
            "playlist": refresh_action.get_refresh_info().get("playlist"),
            "plugin_instance": refresh_action.get_refresh_info().get("plugin_instance"),
        }
        logger.info(
            "plugin_lifecycle: display_start",
            extra={
                "stage": "display_start",
                "plugin_id": plugin_id,
                "instance": instance_name,
                "refresh_id": benchmark_id,
                "request_id": request_id,
            },
        )
        stage_t1 = perf_counter()
        display_duration_ms = None
        preprocess_ms = None
        display_driver = None
        try:
            display_metrics = self.display_manager.display_image(
                image,
                image_settings=plugin_config.get("image_settings", []),
                history_meta=history_meta,
            )
            if isinstance(display_metrics, dict):
                preprocess_ms = display_metrics.get("preprocess_ms")
                display_duration_ms = display_metrics.get("display_ms")
                display_driver = display_metrics.get("display_driver")
            else:
                display_driver = None
        except Exception as exc:
            logger.error(
                "plugin_lifecycle: display_failure | plugin_id=%s instance=%s error=%s",
                plugin_id,
                instance_name,
                exc,
            )
            self._update_plugin_health(
                plugin_id=plugin_id,
                instance=instance_name,
                ok=False,
                metrics={"retained_display": bool(self._stale_display_path())},
                error=str(exc),
            )
            self.progress_bus.publish(
                {
                    "state": "error",
                    "plugin_id": plugin_id,
                    "instance": instance_name,
                    "refresh_id": benchmark_id,
                    "request_id": request_id,
                    "error": str(exc),
                    "retained_display": bool(self._stale_display_path()),
                }
            )
            raise
        finally:
            if display_duration_ms is None:
                display_duration_ms = int((perf_counter() - stage_t1) * 1000)
            logger.info(
                "plugin_lifecycle: display_complete",
                extra={
                    "stage": "display_complete",
                    "plugin_id": plugin_id,
                    "instance": instance_name,
                    "duration_ms": display_duration_ms,
                    "refresh_id": benchmark_id,
                    "request_id": request_id,
                },
            )
            try:
                save_stage_event(
                    self.device_config,
                    benchmark_id,
                    "display_pipeline",
                    display_duration_ms,
                )
                if display_driver:
                    save_stage_event(
                        self.device_config,
                        benchmark_id,
                        "display_driver",
                        display_duration_ms,
                        extra={"driver": display_driver},
                    )
            except Exception:
                logger.debug(
                    "Failed to save display_pipeline benchmark event", exc_info=True
                )
        return display_duration_ms, preprocess_ms

    def _save_benchmark(self, benchmark_id, refresh_info, used_cached, metrics):
        """Persist a refresh_event row best-effort."""
        try:
            cpu_percent = memory_percent = None
            try:
                import psutil  # type: ignore

                cpu_percent = psutil.cpu_percent(interval=None)
                memory_percent = psutil.virtual_memory().percent
            except Exception:
                logger.debug("psutil metrics unavailable", exc_info=True)
            save_refresh_event(
                self.device_config,
                {
                    "refresh_id": benchmark_id,
                    "ts": None,
                    "plugin_id": refresh_info.get("plugin_id"),
                    "instance": refresh_info.get("plugin_instance"),
                    "playlist": refresh_info.get("playlist"),
                    "used_cached": used_cached,
                    "request_ms": metrics.get("request_ms"),
                    "generate_ms": metrics.get("generate_ms"),
                    "preprocess_ms": metrics.get("preprocess_ms"),
                    "display_ms": metrics.get("display_ms"),
                    "cpu_percent": cpu_percent,
                    "memory_percent": memory_percent,
                    "notes": None,
                },
            )
        except Exception:
            logger.debug("Failed to save refresh benchmark event", exc_info=True)

    def _stale_display_path(self) -> str | None:
        """Return the path to an existing display image file, or ``None``.

        Checks ``processed_image_file`` first, then ``current_image_file``.
        Used to detect whether the display currently shows stale content that
        can be retained when a plugin refresh fails.

        Returns:
            An absolute path string if an image file exists, otherwise ``None``.
        """
        for path in (
            getattr(self.device_config, "processed_image_file", None),
            getattr(self.device_config, "current_image_file", None),
        ):
            if path and os.path.exists(path):
                return path
        return None

    def _push_fallback_image(
        self,
        plugin_id: str,
        instance_name: str | None,
        exc: BaseException,
        plugin_config: dict,
        refresh_action,
    ) -> None:
        """Render and push an error-card fallback image to the display.

        Called when ``generate_image()`` raises so the user sees *something*
        changed rather than stale content.  Best-effort: any error here is
        logged but never re-raised.
        """
        try:
            width, height = self.device_config.get_resolution()
            fallback = render_error_image(
                width=width,
                height=height,
                plugin_id=plugin_id,
                instance_name=instance_name,
                error_class=type(exc).__name__,
                error_message=str(exc),
            )
            history_meta = {
                "refresh_type": refresh_action.get_refresh_info().get("refresh_type"),
                "plugin_id": plugin_id,
                "playlist": refresh_action.get_refresh_info().get("playlist"),
                "plugin_instance": instance_name,
            }
            self.display_manager.display_image(
                fallback,
                image_settings=plugin_config.get("image_settings", []),
                history_meta=history_meta,
            )
            logger.info(
                "plugin_lifecycle: fallback_displayed | plugin_id=%s instance=%s",
                plugin_id,
                instance_name,
            )
        except Exception:
            logger.warning(
                "plugin_lifecycle: fallback_display_failed | plugin_id=%s instance=%s",
                plugin_id,
                instance_name,
                exc_info=True,
            )

    def _update_refresh_info(self, refresh_info, metrics, used_cached):
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

    def manual_update(self, refresh_action):
        """Manually triggers an update for the specified plugin id and plugin settings by notifying the background process."""
        if self.running:
            request = ManualUpdateRequest(str(uuid4()), refresh_action)
            with self.condition:
                if (
                    len(self.manual_update_requests)
                    >= self.manual_update_requests.maxlen
                ):
                    raise RuntimeError(
                        "Manual update queue is full. Please wait for pending requests to complete."
                    )
                self.progress_bus.publish(
                    {
                        "state": "queued",
                        "plugin_id": refresh_action.get_plugin_id(),
                        "request_id": request.request_id,
                    }
                )
                self.manual_update_requests.append(request)
                self.condition.notify_all()  # Wake the thread to process manual update

            wait_s = float(os.getenv("INKYPI_MANUAL_UPDATE_WAIT_S", "60") or "60")
            completed = request.done.wait(timeout=max(0.0, wait_s))
            if not completed:
                with self.condition:
                    try:
                        self.manual_update_requests.remove(request)
                    except ValueError:
                        pass
                timeout_exc = TimeoutError(
                    f"Manual update timed out after {int(wait_s)}s"
                )
                self._update_plugin_health(
                    plugin_id=refresh_action.get_plugin_id(),
                    instance=refresh_action.get_refresh_info().get("plugin_instance"),
                    ok=False,
                    metrics=None,
                    error=str(timeout_exc),
                )
                self.progress_bus.publish(
                    {
                        "state": "error",
                        "plugin_id": refresh_action.get_plugin_id(),
                        "request_id": request.request_id,
                        "error": str(timeout_exc),
                    }
                )
                raise timeout_exc
            metrics = request.metrics
            exc = request.exception
            if exc is not None:
                self.progress_bus.publish(
                    {
                        "state": "error",
                        "plugin_id": refresh_action.get_plugin_id(),
                        "request_id": request.request_id,
                        "error": str(exc),
                    }
                )
                if isinstance(exc, BaseException):
                    raise exc
                raise RuntimeError(str(exc))
            return metrics
        else:
            logger.warning(
                "Background refresh task is not running, unable to do a manual update"
            )

    @staticmethod
    def _timeout_msg(plugin_id: str, timeout_s: float) -> str:
        """Return a canonical timeout error message string."""
        return f"Plugin '{plugin_id}' timed out after {int(timeout_s)}s"

    @staticmethod
    def _cleanup_subprocess(proc, plugin_id: str) -> None:
        """Terminate a subprocess that is still alive after its timeout.

        Attempts graceful termination first, escalates to SIGKILL if needed,
        and logs a warning if the process becomes a zombie.
        """
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
    def _handle_process_result(result_queue, proc, plugin_id: str, attempt: int):
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

            with Image.open(io.BytesIO(payload["image_bytes"])) as image:
                result_image = image.copy()
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
        self, refresh_action, plugin_config, current_dt, plugin_id, timeout_s, attempt
    ):
        """Spawn a subprocess for one plugin execution attempt.

        Returns ``(image, exc_or_meta)`` on success, or raises/returns an exception
        as the second element when the attempt fails.
        """
        ctx = _get_mp_context()
        result_queue = ctx.Queue(maxsize=1)
        proc = ctx.Process(
            target=_execute_refresh_attempt_worker,
            args=(
                result_queue,
                plugin_config,
                refresh_action,
                self.device_config,
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
        self, refresh_action, plugin_config, current_dt: datetime, request_id=None
    ):
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
        timeout_s = float(os.getenv("INKYPI_PLUGIN_TIMEOUT_S", "60") or "60")
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
                self.progress_bus.publish(
                    {
                        "state": "step",
                        "plugin_id": plugin_id,
                        "request_id": request_id,
                        "step": f"retry {attempt}/{attempts - 1}",
                    }
                )

        if last_exc is not None:
            raise last_exc
        raise RuntimeError(f"Plugin '{plugin_id}' failed with unknown error")

    # Class-level counter tracking threads that timed out but could not be stopped.
    # Python threads cannot be force-killed; cooperative plugins should check the
    # cancel_event passed via result_holder["cancel_event"] and exit early.
    _zombie_thread_count: int = 0
    _zombie_thread_lock: threading.Lock = threading.Lock()

    def _execute_inprocess(self, refresh_action, plugin_config, current_dt: datetime):
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
        timeout_s = float(os.getenv("INKYPI_PLUGIN_TIMEOUT_S", "60") or "60")
        attempts = max(1, retries + 1)

        last_exc: BaseException | None = None
        for attempt in range(1, attempts + 1):
            result_holder: dict = {}
            cancel_event = threading.Event()
            result_holder["cancel_event"] = cancel_event

            def _worker(holder=result_holder, _cancel=cancel_event):
                try:
                    plugin = get_plugin_instance(plugin_config)
                    image = refresh_action.execute(
                        plugin, self.device_config, current_dt
                    )
                    meta = None
                    if hasattr(plugin, "get_latest_metadata"):
                        meta = plugin.get_latest_metadata()
                    holder["image"] = image
                    holder["meta"] = meta
                except Exception as exc:
                    holder["error"] = exc
                finally:
                    if _cancel.is_set():
                        # Decrement zombie count now that this thread is finishing.
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

            worker_thread = threading.Thread(target=_worker, daemon=True)
            worker_thread.start()
            worker_thread.join(timeout=timeout_s)

            if worker_thread.is_alive():
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
                last_exc = TimeoutError(
                    f"Plugin '{plugin_id}' timed out after {int(timeout_s)}s"
                )
            elif "error" in result_holder:
                last_exc = result_holder["error"]
            else:
                return result_holder["image"], result_holder.get("meta")

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
        metrics: dict | None,
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
        now_iso = now_device_tz(self.device_config).astimezone(UTC).isoformat()
        entry = self.plugin_health.get(plugin_id, {})
        entry.setdefault("success_count", 0)
        entry.setdefault("failure_count", 0)
        entry.setdefault("retry_count", 0)
        entry.setdefault("timeout_count", 0)
        entry["instance"] = instance
        entry["last_seen"] = now_iso

        # Resolve the PluginInstance so we can mutate its circuit-breaker fields
        plugin_instance = None
        if instance:
            plugin_instance = self.device_config.get_playlist_manager().find_plugin(
                plugin_id, instance
            )

        if ok:
            entry["status"] = "green"
            entry["last_success_at"] = now_iso
            entry["last_error"] = None
            entry["success_count"] = int(entry.get("success_count", 0)) + 1
            entry["failure_count"] = 0
            entry["retained_display"] = False
            if metrics:
                entry["last_metrics"] = metrics
            record_refresh_success()
            self._cb_on_success(plugin_instance, plugin_id, instance)
        else:
            msg = error or "unknown error"
            entry["status"] = "red"
            entry["last_failure_at"] = now_iso
            entry["last_error"] = msg
            entry["failure_count"] = int(entry.get("failure_count", 0)) + 1
            if "timed out" in msg.lower():
                entry["timeout_count"] = int(entry.get("timeout_count", 0)) + 1
            entry["retry_count"] = int(os.getenv("INKYPI_PLUGIN_RETRY_MAX", "1") or "1")
            entry["retained_display"] = bool((metrics or {}).get("retained_display"))
            if metrics:
                entry["last_metrics"] = metrics
            record_refresh_failure(plugin_id)
            self._cb_on_failure(plugin_instance, plugin_id, instance)
        self.plugin_health[plugin_id] = entry

    def _cb_on_success(
        self,
        plugin_instance,
        plugin_id: str,
        instance: str | None,
    ) -> None:
        """Reset the circuit breaker on a successful refresh."""
        if plugin_instance is None:
            return
        changed = (
            plugin_instance.paused or plugin_instance.consecutive_failure_count > 0
        )
        if changed:
            logger.info(
                "plugin circuit_breaker: recovered | plugin_id=%s instance=%s",
                plugin_id,
                instance,
            )
        plugin_instance.consecutive_failure_count = 0
        plugin_instance.paused = False
        plugin_instance.disabled_reason = None
        set_circuit_breaker_open(plugin_id, False)
        if changed:
            try:
                self.device_config.write_config()
            except Exception:
                logger.warning(
                    "plugin circuit_breaker: failed to persist reset for %s/%s",
                    plugin_id,
                    instance,
                    exc_info=True,
                )

    def _cb_on_failure(
        self,
        plugin_instance,
        plugin_id: str,
        instance: str | None,
    ) -> None:
        """Increment the failure counter and pause the plugin if threshold exceeded."""
        if plugin_instance is None or plugin_instance.paused:
            return
        threshold = self._get_circuit_breaker_threshold()
        plugin_instance.consecutive_failure_count += 1
        logger.warning(
            "plugin circuit_breaker: failure | plugin_id=%s instance=%s count=%d/%d",
            plugin_id,
            instance,
            plugin_instance.consecutive_failure_count,
            threshold,
        )
        newly_paused = False
        if plugin_instance.consecutive_failure_count >= threshold:
            now_iso = now_device_tz(self.device_config).astimezone(UTC).isoformat()
            error_msg = (
                self.plugin_health.get(plugin_id, {}).get("last_error") or "unknown"
            )
            plugin_instance.paused = True
            plugin_instance.disabled_reason = (
                f"Paused after {plugin_instance.consecutive_failure_count} consecutive "
                f"failures at {now_iso}. Last error: {error_msg[:120]}"
            )
            newly_paused = True
            set_circuit_breaker_open(plugin_id, True)
            logger.error(
                "plugin circuit_breaker: paused | plugin_id=%s instance=%s"
                " paused after %d consecutive failures",
                plugin_id,
                instance,
                plugin_instance.consecutive_failure_count,
            )
        # Persist the updated counter (and paused state if newly paused) to disk
        # so that a daemon restart preserves the circuit-breaker state.
        if newly_paused or plugin_instance.consecutive_failure_count > 0:
            try:
                self.device_config.write_config()
            except Exception:
                logger.warning(
                    "plugin circuit_breaker: failed to persist failure state for %s/%s",
                    plugin_id,
                    instance,
                    exc_info=True,
                )

        # Best-effort webhook notification — never raises.
        try:
            webhook_urls = self.device_config.get_config("webhook_urls", default=[])
            if webhook_urls:
                now_iso = now_device_tz(self.device_config).astimezone(UTC).isoformat()
                error_msg = (
                    self.plugin_health.get(plugin_id, {}).get("last_error") or "unknown"
                )
                payload = {
                    "event": "plugin_failure",
                    "plugin_id": plugin_id,
                    "instance_name": instance,
                    "error": error_msg,
                    "ts": now_iso,
                }
                send_failure_webhook(webhook_urls, payload)
        except Exception:
            logger.warning(
                "webhook: unexpected error building webhook payload", exc_info=True
            )

    def reset_circuit_breaker(self, plugin_id: str, instance: str) -> bool:
        """Clear the paused state and failure counter for a plugin instance.

        Returns True if the instance was found and reset, False otherwise.
        """
        plugin_instance = self.device_config.get_playlist_manager().find_plugin(
            plugin_id, instance
        )
        if plugin_instance is None:
            return False
        plugin_instance.consecutive_failure_count = 0
        plugin_instance.paused = False
        plugin_instance.disabled_reason = None
        # Sanitize user-controlled values for the audit log (S5145):
        # strip CR/LF (log injection) and truncate to a sane length.
        safe_pid = str(plugin_id).replace("\r", "").replace("\n", "")[:64]
        safe_inst = str(instance).replace("\r", "").replace("\n", "")[:64]
        logger.info(
            "plugin circuit_breaker: manual_reset | plugin_id=%s instance=%s",
            safe_pid,
            safe_inst,
        )
        return True

    def get_health_snapshot(self) -> dict:
        return dict(self.plugin_health)

    def signal_config_change(self):
        """Notify the background thread that config has changed (e.g., interval updated)."""
        if self.running:
            with self.condition:
                self.condition.notify_all()

    def _get_current_datetime(self):
        """Retrieves the current datetime based on the device's configured timezone."""
        return now_device_tz(self.device_config)

    def _determine_next_plugin(self, playlist_manager, latest_refresh_info, current_dt):
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

    def log_system_stats(self):
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
