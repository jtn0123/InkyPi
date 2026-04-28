"""Display update and fallback handling for refresh cycles."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from time import perf_counter
from typing import Any, Protocol

from PIL import Image

from refresh_task.actions import ManualUpdateRequest
from refresh_task.housekeeping import RefreshActionLike, RefreshHousekeeper
from refresh_task.recorder import RefreshRecorder

logger = logging.getLogger(__name__)


class SupportsDisplayPipeline(Protocol):
    """Display-manager surface needed for refresh display pushes."""

    def display_image(
        self,
        image: Image.Image,
        image_settings: object = ...,
        history_meta: dict[str, str | None] | None = ...,
        on_image_saved: Callable[[Mapping[str, Any]], None] | None = ...,
    ) -> object: ...


HealthUpdater = Callable[
    [str, str | None, bool, Mapping[str, Any] | None, str | None],
    None,
]


class DisplayPipeline:
    """Owns display persistence, fallback rendering, and display-stage metrics."""

    def __init__(
        self,
        *,
        display_manager: SupportsDisplayPipeline,
        housekeeper: RefreshHousekeeper,
        recorder: RefreshRecorder,
        update_plugin_health: HealthUpdater,
    ) -> None:
        self.display_manager = display_manager
        self.housekeeper = housekeeper
        self.recorder = recorder
        self.update_plugin_health = update_plugin_health

    def push_or_skip_display(
        self,
        *,
        used_cached: bool,
        image: Image.Image,
        plugin_config: Mapping[str, Any],
        refresh_action: RefreshActionLike,
        refresh_info: Mapping[str, Any],
        benchmark_id: str | None,
        plugin_id: str,
        instance_name: str | None,
        request_id: str | None,
        manual_request: ManualUpdateRequest | None,
    ) -> tuple[int | None, int | None]:
        """Push the image to the display, or skip when the cache is warm."""
        if not used_cached:
            return self.push_to_display(
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
        logger.info(
            f"Image already displayed, skipping refresh. | refresh_info: {refresh_info}"
        )
        # No display push means no ``on_image_saved`` callback, but the
        # image-on-disk invariant still holds because the previous refresh
        # already wrote it. Unblock the manual-update waiter immediately.
        if manual_request is not None:
            manual_request.image_saved.set()
        self.recorder.publish_step(
            plugin_id=plugin_id,
            request_id=request_id,
            step="Image unchanged; display skipped",
        )
        return None, None

    def push_to_display(
        self,
        *,
        image: Image.Image,
        plugin_config: Mapping[str, Any],
        refresh_action: RefreshActionLike,
        refresh_info: Mapping[str, Any],
        benchmark_id: str | None,
        plugin_id: str,
        instance_name: str | None,
        request_id: str | None,
        manual_request: ManualUpdateRequest | None = None,
    ) -> tuple[int | None, int | None]:
        """Push image to the display hardware and record display benchmark stages."""
        logger.info(f"Updating display. | refresh_info: {refresh_info}")
        history_meta = self.housekeeper.build_history_meta(refresh_action)
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
        display_ok = False
        on_image_saved = self._image_saved_callback(
            manual_request=manual_request,
            plugin_id=plugin_id,
            request_id=request_id,
        )
        self.recorder.publish_step(
            plugin_id=plugin_id,
            request_id=request_id,
            step="Saving image",
        )

        try:
            display_metrics = self.display_manager.display_image(
                image,
                image_settings=plugin_config.get("image_settings", []),
                history_meta=history_meta,
                on_image_saved=on_image_saved,
            )
            if isinstance(display_metrics, dict):
                preprocess_ms = display_metrics.get("preprocess_ms")
                display_duration_ms = display_metrics.get("display_ms")
                display_driver = display_metrics.get("display_driver")
            display_ok = True
        except Exception as exc:
            logger.error(
                "plugin_lifecycle: display_failure | plugin_id=%s instance=%s error=%s",
                plugin_id,
                instance_name,
                exc,
            )
            retained_display = bool(self.housekeeper.stale_display_path())
            self.update_plugin_health(
                plugin_id,
                instance_name,
                False,
                {"retained_display": retained_display},
                str(exc),
            )
            self.recorder.publish_error(
                plugin_id=plugin_id,
                instance=instance_name,
                refresh_id=benchmark_id,
                request_id=request_id,
                error=str(exc),
                retained_display=retained_display,
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
            if display_ok:
                self.recorder.publish_step(
                    plugin_id=plugin_id,
                    request_id=request_id,
                    step="Display complete",
                )
            self.recorder.save_stage(
                benchmark_id or "",
                "display_pipeline",
                display_duration_ms,
            )
            if display_driver:
                self.recorder.save_stage(
                    benchmark_id or "",
                    "display_driver",
                    display_duration_ms,
                    extra={"driver": display_driver},
                )
        return display_duration_ms, preprocess_ms

    def push_fallback_image(
        self,
        *,
        plugin_id: str,
        instance_name: str | None,
        exc: BaseException,
        plugin_config: Mapping[str, Any],
        refresh_action: RefreshActionLike,
    ) -> None:
        """Render and push an error-card fallback image to the display."""
        self.housekeeper.push_fallback_image(
            plugin_id=plugin_id,
            instance_name=instance_name,
            exc=exc,
            plugin_config=plugin_config,
            refresh_action=refresh_action,
        )

    def _image_saved_callback(
        self,
        *,
        manual_request: ManualUpdateRequest | None,
        plugin_id: str,
        request_id: str | None,
    ) -> Callable[[Mapping[str, Any]], None]:
        """Return a callback that reports disk-save progress and releases waiters."""

        def on_image_saved(save_metrics: Mapping[str, Any]) -> None:
            self.recorder.publish_step(
                plugin_id=plugin_id,
                request_id=request_id,
                step="Image saved; writing to display",
            )
            if manual_request is None:
                return
            manual_request.image_saved_metrics = {
                "generate_ms": None,
                "preprocess_ms": save_metrics.get("preprocess_ms"),
                "display_ms": None,
                "stage": "image_saved",
            }
            manual_request.image_saved.set()

        return on_image_saved
