"""Refresh-loop scheduling mixed into ``RefreshTask``.

Covers waiting for the next trigger, choosing the next playlist plugin, the
watchdog stall gate, periodic history cleanup and system-stats logging.
"""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime
from time import monotonic
from typing import TYPE_CHECKING, Any, cast

from model import PlaylistManager
from refresh_task.actions import ManualUpdateRequest, PlaylistRefresh, RefreshAction
from refresh_task.context import RefreshContext
from refresh_task.scheduler import RefreshScheduler
from utils.time_utils import now_device_tz

if TYPE_CHECKING:
    from refresh_task.executor import RefreshExecutor
    from refresh_task.housekeeping import RefreshHousekeeper

# Moved out of task.py; keeps the original logger name so log records, level
# configuration and log-capturing tests see exactly what they did before.
logger = logging.getLogger("refresh_task.task")

#: A single refresh may occupy the loop this long before the watchdog heartbeat
#: treats it as wedged.  Deliberately well clear of the slowest sanctioned
#: refresh (ai_image allows 180s of plugin time, plus render and the e-paper
#: write) so an ordinary slow cycle is never mistaken for a hang; systemd then
#: takes a further WatchdogSec to act.
_DEFAULT_REFRESH_STALL_TIMEOUT = 600.0


class SchedulingMixin:
    """Decides when to refresh and what to refresh next."""

    if TYPE_CHECKING:
        device_config: Any
        condition: threading.Condition
        running: bool
        scheduler: RefreshScheduler
        housekeeper: RefreshHousekeeper
        executor: RefreshExecutor
        refresh_context: RefreshContext
        _tick_count: int
        _work_started_at: float | None
        _watchdog_stall_logged: bool

        @staticmethod
        def _notify_watchdog() -> None: ...

    @staticmethod
    def _watchdog_interval_seconds() -> float:
        """Half of WATCHDOG_USEC (set by systemd when WatchdogSec= is in the unit file).

        Defaults to 30s if WATCHDOG_USEC is unset (e.g. running outside systemd).
        """
        return float(RefreshScheduler.watchdog_interval_seconds())

    @staticmethod
    def _refresh_stall_timeout_seconds() -> float:
        """How long a single refresh may run before the loop is judged wedged.

        Must comfortably exceed the slowest legitimate refresh — AI image
        generation and chromium screenshots are the long poles — because
        exceeding it stops the watchdog pings and systemd restarts the service
        ``WatchdogSec`` later.  Override with
        ``INKYPI_REFRESH_STALL_TIMEOUT_SECONDS``; non-numeric or non-positive
        values fall back to the default rather than disabling the guard.
        """
        raw = os.environ.get("INKYPI_REFRESH_STALL_TIMEOUT_SECONDS", "")
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return _DEFAULT_REFRESH_STALL_TIMEOUT
        return value if value > 0 else _DEFAULT_REFRESH_STALL_TIMEOUT

    def _watchdog_should_notify(self) -> bool:
        """True while the refresh loop is idle or working within its budget.

        Returning False stops the heartbeat, which is the whole point: a
        refresh stuck in a blocking call holds no lock, so nothing else would
        ever notice it. Idle waiting between cycles is healthy and always
        pings, no matter how long ``plugin_cycle_interval_seconds`` is — that
        is the JTN-596 property this must not regress.
        """
        started = self._work_started_at
        if started is None:
            return True
        elapsed = monotonic() - started
        if elapsed <= self._refresh_stall_timeout_seconds():
            return True
        if not self._watchdog_stall_logged:
            self._watchdog_stall_logged = True
            logger.error(
                "Refresh has been running for %.0fs with no progress; withholding "
                "systemd watchdog keepalive so the service is restarted.",
                elapsed,
            )
        return False

    def _watchdog_heartbeat_loop(self) -> None:
        """Background loop that feeds the systemd watchdog at WatchdogSec/2 cadence.

        Decoupled from the refresh cycle so a long plugin_cycle_interval_seconds
        cannot stall the heartbeat (JTN-596), but gated on refresh progress so a
        wedged cycle still trips the watchdog.
        """
        self.scheduler.watchdog_heartbeat_loop(
            is_running=lambda: self.running,
            notify_watchdog=self._notify_watchdog,
            interval_seconds=self._watchdog_interval_seconds(),
            should_notify=self._watchdog_should_notify,
        )

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

    def signal_config_change(self) -> None:
        """Notify the background thread that config has changed (e.g., interval updated).

        Also rebuilds the ``RefreshContext`` snapshot so that subsequent
        subprocess launches pick up the latest configuration values.
        """
        self.refresh_context = RefreshContext.from_config(self.device_config)
        self.executor.refresh_context = self.refresh_context
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
        # Selection mutates the playlist manager (active playlist, plugin
        # index); hold the config lock so it cannot interleave with a web
        # thread's update_atomic snapshot/rollback. Persisted by the
        # refresh-info write at the end of the cycle.
        with self.device_config.locked():
            return self._determine_next_plugin_locked(
                playlist_manager, latest_refresh_info, current_dt
            )

    def _determine_next_plugin_locked(
        self, playlist_manager: Any, latest_refresh_info: Any, current_dt: datetime
    ) -> tuple[Any | None, Any | None]:
        """Body of :meth:`_determine_next_plugin`; caller holds the config lock."""
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
                    "plugin circuit_breaker: skipping paused plugin | "
                    "plugin_id=%s instance=%s failures=%s reason=%s",
                    plugin.plugin_id,
                    plugin.name,
                    getattr(plugin, "consecutive_failure_count", "?"),
                    getattr(plugin, "disabled_reason", None) or "not recorded",
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
