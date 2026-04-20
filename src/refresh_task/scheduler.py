"""Scheduling helpers for the refresh task loop."""

from __future__ import annotations

import logging
import os
import threading
from collections import deque
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from refresh_task.actions import ManualUpdateRequest

logger = logging.getLogger(__name__)


class SupportsRefreshScheduling(Protocol):
    """Config surface needed to wait for the next refresh trigger."""

    def get_config(self, key: str, default: object = ...) -> object: ...

    def get_playlist_manager(self) -> object: ...

    def get_refresh_info(self) -> object: ...


class RefreshScheduler:
    """Owns watchdog cadence and trigger waiting for ``RefreshTask``."""

    def __init__(
        self,
        device_config: SupportsRefreshScheduling,
        condition: threading.Condition,
        manual_update_requests: deque[ManualUpdateRequest],
        get_current_datetime: Callable[[], datetime],
    ) -> None:
        self.device_config = device_config
        self.condition = condition
        self.manual_update_requests = manual_update_requests
        self.get_current_datetime = get_current_datetime

    @staticmethod
    def watchdog_interval_seconds(environ: Mapping[str, str] | None = None) -> float:
        """Return half of ``WATCHDOG_USEC`` in seconds, with sane defaults."""
        env = os.environ if environ is None else environ
        try:
            usec = int(env.get("WATCHDOG_USEC", "0"))
        except (ValueError, TypeError):
            usec = 0
        if usec <= 0:
            return 30.0
        return max(1.0, (usec / 1_000_000) / 2)

    @staticmethod
    def notify_watchdog(sd_notify: Callable[[str], None] | None) -> None:
        """Best-effort systemd watchdog notification."""
        if sd_notify is None:
            return
        try:
            sd_notify("WATCHDOG=1")
        except Exception:
            logger.exception("Failed to notify systemd watchdog")

    def watchdog_heartbeat_loop(
        self,
        *,
        is_running: Callable[[], bool],
        notify_watchdog: Callable[[], None],
        interval_seconds: float,
    ) -> None:
        """Feed the watchdog on a fixed cadence until the task stops."""
        while is_running():
            notify_watchdog()
            with self.condition:
                self.condition.wait(timeout=interval_seconds)

    def wait_for_trigger(
        self, *, is_running: Callable[[], bool]
    ) -> tuple[object, object, datetime, ManualUpdateRequest | None] | None:
        """Block until the next interval tick or manual update request."""
        with self.condition:
            sleep_time = self._cycle_interval_seconds()
            if not is_running():
                return None
            if not self.manual_update_requests:
                self.condition.wait(timeout=sleep_time)
            if not is_running():
                return None

            playlist_manager = self.device_config.get_playlist_manager()
            latest_refresh = self.device_config.get_refresh_info()
            current_dt = self.get_current_datetime()
            manual_request = None
            if self.manual_update_requests:
                manual_request = self.manual_update_requests.popleft()
            return playlist_manager, latest_refresh, current_dt, manual_request

    def _cycle_interval_seconds(self) -> float:
        """Read the configured refresh interval with a safe fallback."""
        raw_value = self.device_config.get_config(
            "plugin_cycle_interval_seconds", default=60 * 60
        )
        if isinstance(raw_value, (int, float)):
            return float(raw_value)
        if isinstance(raw_value, str):
            try:
                return float(raw_value or 60 * 60)
            except ValueError:
                return float(60 * 60)
        return float(60 * 60)
