"""One refresh cycle — generate, validate, display, record — for ``RefreshTask``."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from time import perf_counter
from typing import TYPE_CHECKING, Any, cast

from model import RefreshInfo
from refresh_task import plugin_lookup
from refresh_task.actions import ManualUpdateRequest, PlaylistRefresh, RefreshAction
from refresh_task.plugin_lookup import _plugin_requires_api_key
from utils.image_utils import compute_image_hash
from utils.output_validator import (
    OutputDimensionMismatch,
    fit_image_to_panel,
    oriented_resolution,
)
from utils.progress import ProgressTracker, track_progress

if TYPE_CHECKING:
    from refresh_task.display_pipeline import DisplayPipeline
    from refresh_task.executor import RefreshExecutor
    from refresh_task.housekeeping import RefreshHousekeeper
    from refresh_task.recorder import RefreshRecorder

logger = logging.getLogger(__name__)

#: ``(refresh_info, used_cached, metrics)`` — see ``_perform_refresh``.
RefreshOutcome = tuple[dict[str, Any] | None, bool, dict[str, Any]]


@dataclass(frozen=True, slots=True)
class _Turn:
    """What every step of one refresh needs to know about it."""

    refresh_action: RefreshAction
    plugin_config: dict[str, Any]
    current_dt: datetime
    benchmark_id: str
    plugin_id: str
    instance_name: str | None
    request_id: str | None
    manual_request: ManualUpdateRequest | None


class RefreshCycleMixin:
    """Runs a single refresh action end to end on the refresh thread."""

    if TYPE_CHECKING:
        device_config: Any
        recorder: RefreshRecorder
        housekeeper: RefreshHousekeeper
        display_pipeline: DisplayPipeline
        executor: RefreshExecutor

        def _update_plugin_health(
            self,
            plugin_id: str,
            instance: str | None,
            ok: bool,
            metrics: dict[str, Any] | None,
            error: str | None,
        ) -> None: ...

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

        The hook runs here, in the main process, so the plugin is only loaded
        to ask it when ``plugin-info.json`` sets ``skip_display_condition``.
        Every other plugin's code stays in the render worker.
        """
        if plugin_config.get("skip_display_condition") is not True:
            return None
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
        current_dt: datetime,
        request_id: str | None = None,
        manual_request: ManualUpdateRequest | None = None,
    ) -> RefreshOutcome:
        """Execute the refresh action and update the display if needed.

        Returns a tuple ``(refresh_info, used_cached, metrics)`` where
        ``refresh_info`` is a dictionary with metadata, ``used_cached`` indicates
        whether the image was unchanged, and ``metrics`` contains timing data.

        The turn runs in four steps, each of which may end it early: ask the
        plugin whether to skip, generate, fit the image to the panel, then
        display and record.

        Threading:
            Must be called without holding ``self.condition``.
        """
        plugin_config = self._plugin_config_for(refresh_action)
        if plugin_config is None:
            return None, False, {}

        started = perf_counter()
        turn = _Turn(
            refresh_action=refresh_action,
            plugin_config=plugin_config,
            current_dt=current_dt,
            # Correlate this refresh with a benchmark id so parallel stage
            # events can attach.
            benchmark_id=self.recorder.refresh_id(request_id),
            plugin_id=refresh_action.get_plugin_id(),
            instance_name=refresh_action.get_refresh_info().get("plugin_instance"),
            request_id=request_id,
            manual_request=manual_request,
        )

        skipped = self._skip_turn(turn)
        if skipped is not None:
            return None, False, skipped

        image, plugin_meta, generate_ms, tracker = self._generate(turn)
        if image is None:
            return None, False, self._finish_without_image(turn, generate_ms)

        image = self._fit_to_panel(turn, image)
        if image is None:
            return None, False, {}

        return self._display_and_record(
            turn,
            image,
            plugin_meta,
            started=started,
            generate_ms=generate_ms,
            tracker=tracker,
        )

    def _plugin_config_for(
        self, refresh_action: RefreshAction
    ) -> dict[str, Any] | None:
        """Return the plugin's config, or ``None`` if it is not installed.

        Raises ``RuntimeError`` when the plugin has been isolated.
        """
        plugin_id = refresh_action.get_plugin_id()
        plugin_config = self.device_config.get_plugin(plugin_id)
        if plugin_config is None:
            logger.error(f"Plugin config not found for '{plugin_id}'.")
            return None

        isolated_plugins = self.device_config.get_config("isolated_plugins", default=[])
        if isinstance(isolated_plugins, list) and plugin_id in isolated_plugins:
            raise RuntimeError(f"Plugin '{plugin_id}' is currently isolated/disabled.")
        return cast(dict[str, Any], plugin_config)

    def _skip_turn(self, turn: _Turn) -> dict[str, Any] | None:
        """Let the plugin yield this turn; return the skip metrics if it does.

        Asked before paying for a render. The playlist index has already
        advanced, so a skip yields the turn to the next plugin rather than
        sticking.
        """
        skip_reason = self._skip_display_reason(
            turn.refresh_action,
            turn.plugin_config,
            turn.current_dt,
            turn.manual_request,
        )
        if skip_reason is None:
            return None
        logger.info(
            "plugin_lifecycle: skipped | plugin_id=%s instance=%s reason=%s",
            turn.plugin_id,
            turn.instance_name,
            skip_reason,
        )
        self.recorder.publish_step(
            plugin_id=turn.plugin_id,
            request_id=turn.request_id,
            step=f"Skipped: {skip_reason}",
        )
        # A skip is a healthy outcome, not a failure — recording it as one
        # would march the circuit breaker toward pausing a working plugin.
        self._update_plugin_health(
            plugin_id=turn.plugin_id,
            instance=turn.instance_name,
            ok=True,
            metrics={"skipped": True, "skip_reason": skip_reason},
            error=None,
        )
        return {"skipped": True, "skip_reason": skip_reason}

    def _generate(self, turn: _Turn) -> tuple[Any, Any, int, ProgressTracker]:
        """Render the plugin's image; return ``(image, meta, ms, tracker)``.

        A failure is recorded (health, error event, fallback card) and then
        re-raised.
        """
        logger.info(
            "plugin_lifecycle: generate_start",
            extra={
                "stage": "generate_start",
                "plugin_id": turn.plugin_id,
                "instance": turn.instance_name,
                "refresh_id": turn.benchmark_id,
                "request_id": turn.request_id,
            },
        )
        started = perf_counter()
        tracker: ProgressTracker
        with track_progress() as tracker:
            stage_t0 = perf_counter()
            self._announce_generation(turn)
            try:
                image, plugin_meta = self.executor.execute_with_policy(
                    turn.refresh_action,
                    turn.plugin_config,
                    turn.current_dt,
                    request_id=turn.request_id,
                )
            except Exception as exc:
                self._record_generate_failure(turn, exc)
                raise
            # A control-only plugin returns before the normal refresh-info
            # write in ``_run``, so its new timestamp is persisted here.
            self._commit_refresh_state(turn.refresh_action, persist=image is None)
            self.recorder.save_stage(
                turn.benchmark_id,
                "generate_image",
                int((perf_counter() - stage_t0) * 1000),
            )
        generate_ms = int((perf_counter() - started) * 1000)
        logger.info(
            "plugin_lifecycle: generate_complete",
            extra={
                "stage": "generate_complete",
                "plugin_id": turn.plugin_id,
                "instance": turn.instance_name,
                "duration_ms": generate_ms,
                "refresh_id": turn.benchmark_id,
                "request_id": turn.request_id,
            },
        )
        self.recorder.publish_step(
            plugin_id=turn.plugin_id,
            request_id=turn.request_id,
            step="Image generated",
        )
        return image, plugin_meta, generate_ms, tracker

    def _announce_generation(self, turn: _Turn) -> None:
        """Publish the running event and the progress steps before rendering."""
        self.recorder.publish_running(
            plugin_id=turn.plugin_id,
            instance=turn.instance_name,
            refresh_id=turn.benchmark_id,
            request_id=turn.request_id,
        )
        for step in (
            "Preparing plugin",
            (
                "Checking provider credentials"
                if _plugin_requires_api_key(turn.plugin_config)
                else "Checking plugin settings"
            ),
            "Generating image",
        ):
            self.recorder.publish_step(
                plugin_id=turn.plugin_id,
                request_id=turn.request_id,
                step=step,
            )

    def _record_generate_failure(self, turn: _Turn, exc: Exception) -> None:
        """Record a failed render and decide what the panel shows instead."""
        retain_path = self._stale_display_path()
        probing = self._is_paused_probe(turn.refresh_action, turn.manual_request)
        # JTN-779: log the full exception class + message so operators can
        # diagnose. The user-visible fallback image is sanitised via
        # utils.fallback_image.sanitize_error_message.
        logger.error(
            "plugin_lifecycle: failure | plugin_id=%s instance=%s retained_display=%s error_class=%s error=%s",
            turn.plugin_id,
            turn.instance_name,
            bool(retain_path),
            type(exc).__name__,
            exc,
        )
        self._update_plugin_health(
            plugin_id=turn.plugin_id,
            instance=turn.instance_name,
            ok=False,
            metrics={"retained_display": bool(retain_path)},
            error=str(exc),
        )
        self.recorder.publish_error(
            plugin_id=turn.plugin_id,
            instance=turn.instance_name,
            refresh_id=turn.benchmark_id,
            request_id=turn.request_id,
            error=str(exc),
            retained_display=bool(retain_path),
            plugin_failed=True,
        )
        if probing:
            # A failed automatic retry of a paused plugin keeps whatever the
            # panel shows; an error card here would replace a good picture
            # every cooldown.
            logger.info(
                "plugin_lifecycle: probe_failed | plugin_id=%s instance=%s"
                " — keeping the current display",
                turn.plugin_id,
                turn.instance_name,
            )
            return
        self._push_fallback_image(
            plugin_id=turn.plugin_id,
            instance_name=turn.instance_name,
            exc=exc,
            plugin_config=turn.plugin_config,
            refresh_action=turn.refresh_action,
        )

    def _finish_without_image(self, turn: _Turn, generate_ms: int) -> dict[str, Any]:
        """Complete a turn whose plugin legitimately produced no image.

        A control-only plugin (servo, webhook poke, anything whose point is the
        side effect) is a completed refresh with nothing to display — not a
        failure — so the display, the history record and plugin health are all
        left alone rather than being handed a fallback error frame.
        """
        logger.info(
            "plugin_lifecycle: no_image | plugin_id=%s instance=%s — plugin "
            "produced no image; leaving the display unchanged",
            turn.plugin_id,
            turn.instance_name,
        )
        self.recorder.publish_step(
            plugin_id=turn.plugin_id,
            request_id=turn.request_id,
            step="Plugin produced no image",
        )
        self._update_plugin_health(
            plugin_id=turn.plugin_id,
            instance=turn.instance_name,
            ok=True,
            metrics={"no_image": True},
            error=None,
        )
        return {"generate_ms": generate_ms, "no_image": True}

    def _fit_to_panel(self, turn: _Turn, image: Any) -> Any | None:
        """Fit the image to the panel; ``None`` if it cannot be fitted.

        Checked before anything expensive (hash, display push). A wrong-size
        image is fitted rather than rejected; only an image that cannot be
        fitted fails the refresh.
        """
        self.recorder.publish_step(
            plugin_id=turn.plugin_id,
            request_id=turn.request_id,
            step="Checking image",
        )
        expected_w, expected_h = oriented_resolution(self.device_config)
        returned_size = image.size
        try:
            image = fit_image_to_panel(
                image,
                expected_w,
                expected_h,
                plugin_id=turn.plugin_id,
            )
        except OutputDimensionMismatch as exc:
            logger.error(
                "plugin_lifecycle: dimension_mismatch | plugin_id=%s instance=%s "
                "expected=%dx%d actual=%dx%d — image cannot be fitted; "
                "skipping display push",
                turn.plugin_id,
                turn.instance_name,
                exc.expected[0],
                exc.expected[1],
                exc.actual[0],
                exc.actual[1],
            )
            self._update_plugin_health(
                plugin_id=turn.plugin_id,
                instance=turn.instance_name,
                ok=False,
                metrics={"retained_display": bool(self._stale_display_path())},
                error=str(exc),
            )
            self.recorder.publish_error(
                plugin_id=turn.plugin_id,
                instance=turn.instance_name,
                refresh_id=turn.benchmark_id,
                request_id=turn.request_id,
                error=str(exc),
                retained_display=bool(self._stale_display_path()),
                plugin_failed=True,
            )
            return None
        if returned_size not in ((expected_w, expected_h), (expected_h, expected_w)):
            self.recorder.publish_step(
                plugin_id=turn.plugin_id,
                request_id=turn.request_id,
                step=(
                    f"Fitted {returned_size[0]}x{returned_size[1]} image to the "
                    f"{expected_w}x{expected_h} panel"
                ),
            )
        return image

    def _display_and_record(
        self,
        turn: _Turn,
        image: Any,
        plugin_meta: Any,
        *,
        started: float,
        generate_ms: int,
        tracker: ProgressTracker,
    ) -> RefreshOutcome:
        """Show the image (unless unchanged) and record the finished turn."""
        image_hash = compute_image_hash(image)

        refresh_info = turn.refresh_action.get_refresh_info()
        if plugin_meta:
            refresh_info.update({"plugin_meta": plugin_meta})

        refresh_info.update(
            {"refresh_time": turn.current_dt.isoformat(), "image_hash": image_hash}
        )
        # Ask what the panel shows, not what the last successful refresh drew:
        # an error card, a history redisplay or a display-settings change
        # since then means the panel needs this render even if it matches.
        used_cached = self.display_pipeline.panel_shows(
            image_hash, turn.plugin_config.get("image_settings", [])
        )
        display_duration_ms, preprocess_ms = self._push_or_skip_display(
            used_cached=used_cached,
            image=image,
            plugin_config=turn.plugin_config,
            refresh_action=turn.refresh_action,
            refresh_info=cast(Any, refresh_info),
            benchmark_id=turn.benchmark_id,
            plugin_id=turn.plugin_id,
            instance_name=turn.instance_name,
            request_id=turn.request_id,
            manual_request=turn.manual_request,
        )

        request_ms = int((perf_counter() - started) * 1000)
        metrics = {
            "request_ms": request_ms,
            "display_ms": display_duration_ms,
            "generate_ms": generate_ms,
            "preprocess_ms": preprocess_ms,
            "steps": tracker.get_steps(),
        }
        self._save_benchmark(turn.benchmark_id, refresh_info, used_cached, metrics)
        self._update_plugin_health(
            plugin_id=turn.plugin_id,
            instance=turn.instance_name,
            ok=True,
            metrics=metrics,
            error=None,
        )
        self.recorder.publish_done(
            plugin_id=turn.plugin_id,
            instance=turn.instance_name,
            refresh_id=turn.benchmark_id,
            request_id=turn.request_id,
            metrics=metrics,
            duration_ms=request_ms,
        )
        return (
            refresh_info | {"benchmark_id": turn.benchmark_id},
            used_cached,
            metrics,
        )

    @staticmethod
    def _is_paused_probe(
        refresh_action: RefreshAction, manual_request: ManualUpdateRequest | None
    ) -> bool:
        """Return whether this refresh is the scheduler's retry of a paused plugin.

        The scheduler only hands out a paused instance when its cooldown has
        elapsed; anything the user asked for arrives as a manual request and
        keeps the normal failure handling.
        """
        if manual_request is not None or not isinstance(
            refresh_action, PlaylistRefresh
        ):
            return False
        return bool(getattr(refresh_action.plugin_instance, "paused", False))

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
