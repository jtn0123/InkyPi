"""One refresh cycle — generate, validate, display, record — for ``RefreshTask``."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import datetime
from time import perf_counter
from typing import TYPE_CHECKING, Any, cast

from model import RefreshInfo
from refresh_task import plugin_lookup
from refresh_task.actions import ManualUpdateRequest, PlaylistRefresh, RefreshAction
from refresh_task.plugin_lookup import _plugin_requires_api_key
from utils.image_utils import compute_image_hash
from utils.output_validator import OutputDimensionMismatch, validate_image_dimensions
from utils.progress import ProgressTracker, track_progress

if TYPE_CHECKING:
    from refresh_task.display_pipeline import DisplayPipeline
    from refresh_task.housekeeping import RefreshHousekeeper
    from refresh_task.recorder import RefreshRecorder

# Moved out of task.py; keeps the original logger name so log records, level
# configuration and log-capturing tests see exactly what they did before.
logger = logging.getLogger("refresh_task.task")


class RefreshCycleMixin:
    """Runs a single refresh action end to end on the refresh thread."""

    if TYPE_CHECKING:
        device_config: Any
        recorder: RefreshRecorder
        housekeeper: RefreshHousekeeper
        display_pipeline: DisplayPipeline

        def _update_plugin_health(
            self,
            plugin_id: str,
            instance: str | None,
            ok: bool,
            metrics: dict[str, Any] | None,
            error: str | None,
        ) -> None: ...

        def _execute_with_policy(
            self,
            refresh_action: RefreshAction,
            plugin_config: Mapping[str, Any],
            current_dt: datetime,
            request_id: str | None = None,
        ) -> tuple[Any, Any]: ...

    def _skip_display_reason(
        self,
        refresh_action: RefreshAction,
        plugin_config: Mapping[str, Any],
        current_dt: datetime,
        manual_request: ManualUpdateRequest | None = None,
    ) -> str | None:
        """Ask the plugin whether it wants to yield this playlist turn.

        Only the scheduler's own turn may be skipped: anything the user asked
        for is an explicit request, and silently declining it would look like
        the button is broken.

        What makes a refresh manual is *how it arrived* — via ``manual_update``
        — not the action class. "Display Now" and ``--run-once`` both hand us a
        ``PlaylistRefresh``, so keying off the type alone would let a plugin
        veto a button press.

        A hook that raises is treated as "do not skip" — a broken optional hook
        must not be able to stop a plugin from ever displaying.
        """
        if manual_request is not None:
            return None
        if not isinstance(refresh_action, PlaylistRefresh):
            return None

        settings = getattr(refresh_action.plugin_instance, "settings", None)
        if not isinstance(settings, Mapping):
            return None

        try:
            plugin = plugin_lookup.get_plugin_instance(dict(plugin_config))
            reason = plugin.skip_display_condition(
                settings, self.device_config, current_dt
            )
        except Exception:
            logger.warning(
                "skip_display_condition raised for plugin %s; rendering normally",
                refresh_action.get_plugin_id(),
                exc_info=True,
            )
            return None

        if reason is None:
            return None
        if not isinstance(reason, str) or not reason.strip():
            logger.warning(
                "skip_display_condition for plugin %s returned %r; expected None "
                "or a non-empty reason string — rendering normally",
                refresh_action.get_plugin_id(),
                reason,
            )
            return None
        return reason.strip()

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

        # Ask the plugin whether it has anything worth showing before paying for
        # a render. The playlist index has already advanced, so a skip yields
        # the turn to the next plugin rather than sticking.
        skip_reason = self._skip_display_reason(
            refresh_action, plugin_config, current_dt, manual_request
        )
        if skip_reason is not None:
            logger.info(
                "plugin_lifecycle: skipped | plugin_id=%s instance=%s reason=%s",
                plugin_id,
                instance_name,
                skip_reason,
            )
            self.recorder.publish_step(
                plugin_id=plugin_id,
                request_id=request_id,
                step=f"Skipped: {skip_reason}",
            )
            # A skip is a healthy outcome, not a failure — recording it as one
            # would march the circuit breaker toward pausing a working plugin.
            self._update_plugin_health(
                plugin_id=plugin_id,
                instance=instance_name,
                ok=True,
                metrics={"skipped": True, "skip_reason": skip_reason},
                error=None,
            )
            return None, False, {"skipped": True, "skip_reason": skip_reason}

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
            self.recorder.publish_step(
                plugin_id=plugin_id,
                request_id=request_id,
                step="Preparing plugin",
            )
            self.recorder.publish_step(
                plugin_id=plugin_id,
                request_id=request_id,
                step=(
                    "Checking provider credentials"
                    if _plugin_requires_api_key(plugin_config)
                    else "Checking plugin settings"
                ),
            )
            self.recorder.publish_step(
                plugin_id=plugin_id,
                request_id=request_id,
                step="Generating image",
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
            # A control-only plugin returns before the normal refresh-info
            # write in ``_run``, so its new timestamp is persisted here.
            self._commit_refresh_state(refresh_action, persist=image is None)
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
        self.recorder.publish_step(
            plugin_id=plugin_id,
            request_id=request_id,
            step="Image generated",
        )
        if image is None:
            # A control-only plugin (servo, webhook poke, anything whose point
            # is the side effect) legitimately produces no image. That is a
            # completed refresh with nothing to display — not a failure — so
            # the display, the history record and plugin health are all left
            # alone rather than being handed a fallback error frame.
            logger.info(
                "plugin_lifecycle: no_image | plugin_id=%s instance=%s — plugin "
                "produced no image; leaving the display unchanged",
                plugin_id,
                instance_name,
            )
            self.recorder.publish_step(
                plugin_id=plugin_id,
                request_id=request_id,
                step="Plugin produced no image",
            )
            self._update_plugin_health(
                plugin_id=plugin_id,
                instance=instance_name,
                ok=True,
                metrics={"no_image": True},
                error=None,
            )
            return None, False, {"generate_ms": generate_ms, "no_image": True}

        # Validate dimensions before doing anything expensive (hash / display push).
        self.recorder.publish_step(
            plugin_id=plugin_id,
            request_id=request_id,
            step="Checking image",
        )
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
        latest = RefreshInfo(
            **refresh_info,
            request_ms=metrics.get("request_ms"),
            display_ms=metrics.get("display_ms"),
            generate_ms=metrics.get("generate_ms"),
            preprocess_ms=metrics.get("preprocess_ms"),
            used_cached=used_cached,
        )

        def _set_refresh_info(_config: dict[str, Any]) -> None:
            self.device_config.refresh_info = latest

        # Under the config lock, so a web thread's update_atomic rollback
        # cannot interleave with (and discard) this assignment.
        self.device_config.update_atomic(_set_refresh_info)

    def _commit_refresh_state(
        self, refresh_action: RefreshAction, *, persist: bool
    ) -> None:
        """Apply plugin-instance state changed by the refresh to the live model.

        With process isolation ``execute()`` ran against the worker's copy of
        the plugin instance, so its new ``latest_refresh_time`` (and any
        settings the plugin wrote back) only reach the parent through the
        state delta. Without this every playlist turn re-renders, because
        ``should_refresh()`` never sees the refresh happen. In-process the
        live instance was already updated and re-applying is idempotent.

        The change is made under the config lock. ``persist`` writes it
        immediately; otherwise the refresh-info write at the end of the cycle
        carries it to disk.
        """
        if not refresh_action.state_delta():
            return
        if not persist:
            with self.device_config.locked():
                refresh_action.commit_state()
            return
        try:
            self.device_config.update_atomic(
                lambda _config: refresh_action.commit_state()
            )
        except Exception:
            logger.warning(
                "Failed to persist refresh state for plugin %s",
                refresh_action.get_plugin_id(),
                exc_info=True,
            )
