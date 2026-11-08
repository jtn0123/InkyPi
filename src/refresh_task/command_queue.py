"""Manual-update and display-command queue mixed into ``RefreshTask``.

Callers on web threads enqueue :class:`ManualUpdateRequest` objects here; the
refresh loop thread picks them up and completes them.
"""

from __future__ import annotations

import logging
import os
import threading
from collections import deque
from collections.abc import Callable, Mapping
from time import monotonic
from typing import TYPE_CHECKING, Any, NoReturn, cast
from uuid import uuid4

from refresh_task.actions import DisplayCommand, ManualUpdateRequest, RefreshAction
from utils import blackout, crash_breadcrumb
from utils.backend_errors import RefreshTaskUnavailable

if TYPE_CHECKING:
    from refresh_task.recorder import RefreshRecorder

# Moved out of task.py; keeps the original logger name so log records, level
# configuration and log-capturing tests see exactly what they did before.
logger = logging.getLogger("refresh_task.task")

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


class CommandQueueMixin:
    """Queues manual refreshes and display commands for the refresh thread."""

    if TYPE_CHECKING:
        device_config: Any
        display_manager: Any
        condition: threading.Condition
        running: bool
        manual_update_requests: deque[ManualUpdateRequest]
        recorder: RefreshRecorder
        _work_started_at: float | None
        _watchdog_stall_logged: bool

        def _update_plugin_health(
            self,
            plugin_id: str,
            instance: str | None,
            ok: bool,
            metrics: dict[str, Any] | None,
            error: str | None,
        ) -> None: ...

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

    # ------------------------------------------------------------------
    # Display commands and blackout
    # ------------------------------------------------------------------

    def _handle_special_request(
        self, manual_request: ManualUpdateRequest | None
    ) -> bool:
        """Run a display command, or refuse a refresh during blackout.

        Returns True when *manual_request* was fully handled here and the loop
        should go back to waiting.
        """
        if manual_request is None:
            return False
        action = manual_request.refresh_action
        if isinstance(action, DisplayCommand):
            self._run_display_command_request(manual_request, action)
            return True
        if blackout.is_active(self.device_config):
            # Queued before blackout began; refuse rather than paint over it.
            self._complete_manual_request(
                manual_request, exception=blackout.BlackoutActiveError()
            )
            return True
        return False

    def _run_display_command_request(
        self, manual_request: ManualUpdateRequest, command: DisplayCommand
    ) -> None:
        """Execute *command* on this (the refresh) thread and complete it."""
        self._work_started_at = monotonic()
        try:
            with crash_breadcrumb.trail("display_command", command=command.name):
                result = command.run(self.display_manager)
        except Exception as exc:  # noqa: BLE001 — reported to the caller
            logger.warning(
                "Display command %s failed: %s", command.name, exc, exc_info=True
            )
            self._complete_manual_request(manual_request, exception=exc)
        else:
            self._complete_manual_request(
                manual_request, metrics=dict(result) if result else {}
            )
        finally:
            self._work_started_at = None
            self._watchdog_stall_logged = False

    def run_display_command(
        self,
        name: str,
        run: Callable[[Any], Mapping[str, object] | None],
        timeout: float = 180.0,
        wait: bool = True,
    ) -> dict[str, Any]:
        """Run *run(display_manager)* on the refresh thread and wait for it.

        Serialising through the loop keeps system frames (blackout blank,
        self-test pattern) from interleaving with a plugin's display write.
        When the loop is not running (web-only mode, run-once) nothing else
        can be driving the panel, so the command runs inline.

        With ``wait=False`` the command is queued and this returns ``{}`` at
        once; a failure is then only logged (by the loop). That suits request
        handlers, which should not sit on a ~30 s e-paper write.

        Raises:
            Whatever *run* raised, or ``TimeoutError`` if the loop did not get
            to the command within *timeout* seconds.
        """
        if not self.running:
            result = run(self.display_manager)
            return dict(result) if result else {}

        command = DisplayCommand(name, run)
        request = ManualUpdateRequest(str(uuid4()), command)
        with self.condition:
            queue = self.manual_update_requests
            if queue.maxlen is not None and len(queue) >= queue.maxlen:
                # A full deque would silently evict the oldest waiter.
                raise RuntimeError("Refresh queue is full; try again shortly")
            queue.append(request)
            self.condition.notify_all()
        if not wait:
            return {}
        if not request.done.wait(timeout=max(0.0, timeout)):
            with self.condition:
                try:
                    self.manual_update_requests.remove(request)
                except ValueError:
                    pass  # already picked up; it will finish on its own
            raise TimeoutError(
                f"Display command '{name}' did not complete within {timeout:.0f}s"
            )
        if request.exception is not None:
            raise request.exception
        return dict(request.metrics or {})

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
        """Manually trigger an update by notifying the background refresh loop.

        Raises:
            RefreshTaskUnavailable: the loop is not running, so nothing would
                pick the request up. Routes map it to HTTP 503 rather than
                reporting a display that never happened.
            BlackoutActiveError: blackout is active.
        """
        if not self.running:
            logger.warning(
                "Background refresh task is not running, unable to do a manual update"
            )
            raise RefreshTaskUnavailable
        if blackout.is_active(self.device_config):
            raise blackout.BlackoutActiveError

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
