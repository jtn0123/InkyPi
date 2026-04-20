"""Housekeeping helpers for refresh-task cleanup and fallback display."""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from typing import Protocol, cast

from utils.fallback_image import render_error_image
from utils.history_cleanup import cleanup_history

logger = logging.getLogger(__name__)


class SupportsHousekeeping(Protocol):
    """Config surface needed for refresh-task housekeeping."""

    history_image_dir: str
    processed_image_file: str
    current_image_file: str

    def get_config(self, key: str, default: object = ...) -> object: ...

    def get_resolution(self) -> tuple[int, int]: ...


class SupportsDisplayImage(Protocol):
    """Display-manager surface needed to show a fallback image."""

    def display_image(
        self,
        image: object,
        image_settings: object,
        history_meta: dict[str, str | None],
    ) -> object: ...


class RefreshActionLike(Protocol):
    """Refresh action surface needed to derive history metadata."""

    def get_refresh_info(self) -> Mapping[str, str | None]: ...


class RefreshHousekeeper:
    """Encapsulates cleanup and fallback-display concerns."""

    def __init__(
        self,
        device_config: SupportsHousekeeping,
        display_manager: SupportsDisplayImage,
    ) -> None:
        self.device_config = device_config
        self.display_manager = display_manager

    def maybe_run_history_cleanup(
        self, *, tick_count: int, cleanup_interval_ticks: int
    ) -> None:
        """Run periodic history cleanup without letting failures escape."""
        if tick_count % cleanup_interval_ticks != 0:
            return
        try:
            raw_cfg = self.device_config.get_config("history_cleanup") or {}
            cfg = raw_cfg if isinstance(raw_cfg, Mapping) else {}
            history_dir = self.device_config.history_image_dir
            cleanup_history(
                history_dir,
                max_age_days=int(cfg.get("max_age_days", 30)),
                max_count=int(cfg.get("max_count", 500)),
                min_free_bytes=int(cfg.get("min_free_bytes", 500_000_000)),
            )
        except Exception:
            logger.exception("history_cleanup: unexpected error during cleanup")

    @staticmethod
    def build_history_meta(
        refresh_action: RefreshActionLike,
        *,
        instance_name: str | None = None,
    ) -> dict[str, str | None]:
        """Build a consistent history metadata payload from a refresh action."""
        refresh_info = refresh_action.get_refresh_info()
        return {
            "refresh_type": refresh_info.get("refresh_type"),
            "plugin_id": refresh_info.get("plugin_id"),
            "playlist": refresh_info.get("playlist"),
            "plugin_instance": (
                instance_name
                if instance_name is not None
                else refresh_info.get("plugin_instance")
            ),
        }

    def stale_display_path(self) -> str | None:
        """Return the currently displayed image path if one exists."""
        for path in (
            getattr(self.device_config, "processed_image_file", None),
            getattr(self.device_config, "current_image_file", None),
        ):
            path_str = cast(str | None, path)
            if path_str and os.path.exists(path_str):
                return path_str
        return None

    def push_fallback_image(
        self,
        *,
        plugin_id: str,
        instance_name: str | None,
        exc: BaseException,
        plugin_config: Mapping[str, object],
        refresh_action: RefreshActionLike,
    ) -> None:
        """Render and display a best-effort fallback error image."""
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
            self.display_manager.display_image(
                fallback,
                image_settings=plugin_config.get("image_settings", []),
                history_meta=self.build_history_meta(
                    refresh_action, instance_name=instance_name
                ),
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
