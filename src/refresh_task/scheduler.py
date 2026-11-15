"""Scheduling helpers for the refresh task loop."""

from __future__ import annotations

import logging
import os
import threading
from collections import deque
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import TYPE_CHECKING, Any, Protocol

from services import schedule

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
        # When the loop last acted on a due refresh, whatever the outcome.
        # In memory only: after a restart an overdue refresh runs promptly.
        self.last_attempt: datetime | None = None

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
        should_notify: Callable[[], bool] | None = None,
    ) -> None:
        """Feed the watchdog on a fixed cadence until the task stops.

        ``should_notify`` gates each ping on evidence that the refresh loop is
        still making progress.  Without it the heartbeat is a bare timer, and a
        refresh wedged in a blocking call (SPI write, chromium subprocess,
        plugin socket) would keep systemd satisfied forever — the watchdog
        could never fire for the failure it exists to catch.  Skipping the ping
        lets ``WatchdogSec`` expire and systemd restart the unit.
        """
        while is_running():
            if should_notify is None or should_notify():
                notify_watchdog()
            with self.condition:
                self.condition.wait(timeout=interval_seconds)

    def wait_for_trigger(
        self, *, is_running: Callable[[], bool]
    ) -> tuple[object, object, datetime, ManualUpdateRequest | None] | None:
        """Block until the next refresh is due, a window changes, or a request.

        The wait ends when the active playlist's next refresh is due (its own
        cycle, else the device interval), when a playlist window opens or
        closes, or when another thread notifies the condition.
        """
        with self.condition:
            if not is_running():
                return None
            if not self.manual_update_requests:
                self.condition.wait(timeout=self.seconds_until_next_check())
            if not is_running():
                return None

            playlist_manager = self.device_config.get_playlist_manager()
            latest_refresh = self.device_config.get_refresh_info()
            current_dt = self.get_current_datetime()
            manual_request = None
            if self.manual_update_requests:
                manual_request = self.manual_update_requests.popleft()
            elif self._due(playlist_manager, latest_refresh, current_dt):
                self.last_attempt = current_dt
            return playlist_manager, latest_refresh, current_dt, manual_request

    def device_interval_seconds(self) -> float:
        """Return the device-wide refresh interval in seconds."""
        return self._cycle_interval_seconds()

    def seconds_until_next_check(self) -> float:
        """Return how long to wait before the playlist next needs a look."""
        device_interval = self._cycle_interval_seconds()
        try:
            return schedule.seconds_until_next_check(
                playlist_manager=self.device_config.get_playlist_manager(),
                latest_refresh=_refresh_datetime(self.device_config.get_refresh_info()),
                last_attempt=self.last_attempt,
                now=self.get_current_datetime(),
                device_interval=device_interval,
            )
        except (AttributeError, TypeError, ValueError) as exc:
            logger.warning(
                "Could not work out the next refresh time (%s); waiting the "
                "device interval",
                exc,
            )
            return max(schedule.MIN_WAIT_SECONDS, device_interval)

    def _due(self, playlist_manager: Any, refresh_info: Any, now: datetime) -> bool:
        try:
            return schedule.is_due(
                playlist_manager=playlist_manager,
                latest_refresh=_refresh_datetime(refresh_info),
                last_attempt=self.last_attempt,
                now=now,
                device_interval=self._cycle_interval_seconds(),
            )
        except (AttributeError, TypeError, ValueError):
            return False

    def _cycle_interval_seconds(self) -> float:
        """Read the configured refresh interval with a safe fallback."""
        raw_value = self.device_config.get_config(
            "plugin_cycle_interval_seconds", default=60 * 60
        )
        value = float(60 * 60)
        if isinstance(raw_value, (int, float)) and not isinstance(raw_value, bool):
            value = float(raw_value)
        elif isinstance(raw_value, str):
            try:
                value = float(raw_value or 60 * 60)
            except ValueError:
                pass
        # Zero or negative would make the loop spin; treat it as unset.
        return value if value > 0 else float(60 * 60)


def _refresh_datetime(refresh_info: Any) -> datetime | None:
    value = refresh_info.get_refresh_datetime()
    return value if isinstance(value, datetime) else None
