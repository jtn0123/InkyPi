"""Progress, event, and benchmark recording for refresh cycles."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol
from uuid import uuid4

from utils.event_bus import EventBus, get_event_bus
from utils.progress_events import ProgressEventBus, get_progress_bus

if TYPE_CHECKING:
    from benchmarks.benchmark_storage import DeviceConfigLike
else:

    class DeviceConfigLike(Protocol):
        BASE_DIR: str

        def get_config(self, key: str, default: Any = None) -> Any: ...


try:
    # Optional import; code must continue if benchmarking is unavailable.
    from benchmarks.benchmark_storage import save_refresh_event, save_stage_event
except Exception:  # pragma: no cover

    def save_refresh_event(
        device_config: DeviceConfigLike,
        refresh_event: dict[str, Any],
    ) -> None:
        return None

    def save_stage_event(
        device_config: DeviceConfigLike,
        refresh_id: str,
        stage: str,
        duration_ms: int | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        return None


logger = logging.getLogger(__name__)

__all__ = ["RefreshRecorder", "save_refresh_event", "save_stage_event"]


class RefreshRecorder:
    """Owns refresh progress, SSE events, and best-effort benchmark writes."""

    def __init__(
        self,
        device_config: DeviceConfigLike,
        *,
        progress_bus: ProgressEventBus | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self.device_config = device_config
        self.progress_bus = (
            progress_bus if progress_bus is not None else get_progress_bus()
        )
        self.event_bus = event_bus if event_bus is not None else get_event_bus()

    @staticmethod
    def refresh_id(request_id: str | None) -> str:
        """Return the external request id or create a correlation id."""
        return request_id or str(uuid4())

    def publish_running(
        self,
        *,
        plugin_id: str,
        instance: str | None,
        refresh_id: str,
        request_id: str | None,
    ) -> None:
        self.progress_bus.publish(
            {
                "state": "running",
                "plugin_id": plugin_id,
                "instance": instance,
                "refresh_id": refresh_id,
                "request_id": request_id,
            }
        )
        self.event_bus.publish(
            "refresh_started",
            {
                "plugin": instance or plugin_id,
                "plugin_id": plugin_id,
                "ts": datetime.now(UTC).isoformat(),
            },
        )

    def publish_error(
        self,
        *,
        plugin_id: str,
        error: str,
        instance: str | None = None,
        refresh_id: str | None = None,
        request_id: str | None = None,
        retained_display: bool | None = None,
        plugin_failed: bool = False,
    ) -> None:
        payload: dict[str, Any] = {
            "state": "error",
            "plugin_id": plugin_id,
            "request_id": request_id,
            "error": error,
        }
        if instance is not None:
            payload["instance"] = instance
        if refresh_id is not None:
            payload["refresh_id"] = refresh_id
        if retained_display is not None:
            payload["retained_display"] = retained_display
        self.progress_bus.publish(payload)

        if plugin_failed:
            self.event_bus.publish(
                "plugin_failed",
                {
                    "plugin": instance or plugin_id,
                    "plugin_id": plugin_id,
                    "error": error,
                },
            )

    def publish_done(
        self,
        *,
        plugin_id: str,
        instance: str | None,
        refresh_id: str,
        request_id: str | None,
        metrics: Mapping[str, Any],
        duration_ms: int,
    ) -> None:
        self.progress_bus.publish(
            {
                "state": "done",
                "plugin_id": plugin_id,
                "instance": instance,
                "refresh_id": refresh_id,
                "request_id": request_id,
                "metrics": metrics,
            }
        )
        self.event_bus.publish(
            "refresh_complete",
            {
                "plugin": instance or plugin_id,
                "plugin_id": plugin_id,
                "duration_ms": duration_ms,
            },
        )

    def publish_queued(self, *, plugin_id: str, request_id: str) -> None:
        self.progress_bus.publish(
            {
                "state": "queued",
                "plugin_id": plugin_id,
                "request_id": request_id,
            }
        )

    def publish_step(
        self, *, plugin_id: str, request_id: str | None, step: str
    ) -> None:
        self.progress_bus.publish(
            {
                "state": "step",
                "plugin_id": plugin_id,
                "request_id": request_id,
                "step": step,
            }
        )

    def save_stage(
        self,
        refresh_id: str,
        stage: str,
        duration_ms: int | None = None,
        *,
        extra: Mapping[str, Any] | None = None,
    ) -> None:
        """Persist a refresh stage row best-effort."""
        try:
            save_stage_event(
                self.device_config,
                refresh_id,
                stage,
                duration_ms,
                extra=dict(extra) if extra is not None else None,
            )
        except Exception:
            logger.debug("Failed to save %s benchmark event", stage, exc_info=True)

    def save_refresh(
        self,
        *,
        refresh_id: str,
        refresh_info: Mapping[str, Any],
        used_cached: bool,
        metrics: Mapping[str, Any],
    ) -> None:
        """Persist a refresh_event row best-effort."""
        try:
            cpu_percent = memory_percent = None
            try:
                import psutil

                cpu_percent = psutil.cpu_percent(interval=None)
                memory_percent = psutil.virtual_memory().percent
            except Exception:
                logger.debug("psutil metrics unavailable", exc_info=True)
            save_refresh_event(
                self.device_config,
                {
                    "refresh_id": refresh_id,
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
