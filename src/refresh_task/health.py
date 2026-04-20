"""Plugin health and circuit-breaker helpers for ``RefreshTask``."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, Protocol, cast

from utils.metrics import (
    record_refresh_failure,
    record_refresh_success,
    set_circuit_breaker_open,
)
from utils.time_utils import now_device_tz

logger = logging.getLogger(__name__)

HealthEntry = dict[str, object]
Metrics = dict[str, object]


class PluginInstanceLike(Protocol):
    """Playlist instance surface needed for circuit-breaker updates."""

    paused: bool
    consecutive_failure_count: int
    disabled_reason: str | None


class SupportsPlaylistLookup(Protocol):
    """Playlist manager surface needed to resolve plugin instances."""

    def find_plugin(
        self, plugin_id: str, instance_name: str
    ) -> PluginInstanceLike | None: ...


class SupportsPluginHealth(Protocol):
    """Config surface needed by plugin-health bookkeeping."""

    def get_playlist_manager(self) -> SupportsPlaylistLookup: ...

    def get_config(self, key: str, default: object = ...) -> object: ...

    def write_config(self) -> None: ...


class PluginHealthTracker:
    """Tracks per-plugin health and owns circuit-breaker transitions."""

    def __init__(
        self,
        device_config: SupportsPluginHealth,
        plugin_health: dict[str, HealthEntry] | None = None,
    ) -> None:
        self.device_config = device_config
        self.plugin_health = plugin_health if plugin_health is not None else {}

    @staticmethod
    def circuit_breaker_threshold(environ: Mapping[str, str] | None = None) -> int:
        """Return the consecutive-failure threshold before pausing a plugin.

        The value is read from ``PLUGIN_FAILURE_THRESHOLD`` and clamped to a
        minimum of 1 (so ``"0"`` becomes ``1``, not ``5``). Invalid values
        (non-integer strings, etc.) fall back to the default of ``5``.
        """
        env = os.environ if environ is None else environ
        try:
            value = int(env.get("PLUGIN_FAILURE_THRESHOLD", "5"))
        except (ValueError, TypeError):
            return 5
        return max(1, value)

    def update(
        self,
        *,
        plugin_id: str,
        instance: str | None,
        ok: bool,
        metrics: Metrics | None,
        error: str | None,
        on_success: Callable[[PluginInstanceLike | None, str, str | None], None],
        on_failure: Callable[[PluginInstanceLike | None, str, str | None], None],
    ) -> None:
        """Update the plugin-health entry and invoke circuit-breaker hooks."""
        now_iso = self._now_iso()
        entry: HealthEntry = dict(self.plugin_health.get(plugin_id, {}))
        entry.setdefault("success_count", 0)
        entry.setdefault("failure_count", 0)
        entry.setdefault("retry_count", 0)
        entry.setdefault("timeout_count", 0)
        entry["instance"] = instance
        entry["last_seen"] = now_iso

        plugin_instance = self._find_plugin_instance(plugin_id, instance)

        if ok:
            entry["status"] = "green"
            entry["last_success_at"] = now_iso
            entry["last_error"] = None
            entry["success_count"] = self._entry_int(entry, "success_count") + 1
            entry["failure_count"] = 0
            entry["retained_display"] = False
            if metrics:
                entry["last_metrics"] = metrics
            self.plugin_health[plugin_id] = entry
            record_refresh_success()
            on_success(plugin_instance, plugin_id, instance)
            return

        msg = error or "unknown error"
        entry["status"] = "red"
        entry["last_failure_at"] = now_iso
        entry["last_error"] = msg
        entry["failure_count"] = self._entry_int(entry, "failure_count") + 1
        if "timed out" in msg.lower():
            entry["timeout_count"] = self._entry_int(entry, "timeout_count") + 1
        entry["retry_count"] = int(os.getenv("INKYPI_PLUGIN_RETRY_MAX", "1") or "1")
        entry["retained_display"] = bool((metrics or {}).get("retained_display"))
        if metrics:
            entry["last_metrics"] = metrics
        self.plugin_health[plugin_id] = entry
        record_refresh_failure(plugin_id)
        on_failure(plugin_instance, plugin_id, instance)

    def on_success(
        self,
        plugin_instance: PluginInstanceLike | None,
        plugin_id: str,
        instance: str | None,
    ) -> None:
        """Reset the circuit breaker after a successful refresh."""
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

    def on_failure(
        self,
        plugin_instance: PluginInstanceLike | None,
        plugin_id: str,
        instance: str | None,
        *,
        webhook_sender: Callable[[list[str], dict[str, object]], None] | None = None,
    ) -> None:
        """Increment failure state and trip the circuit breaker when needed."""
        if plugin_instance is None or plugin_instance.paused:
            return
        threshold = self.circuit_breaker_threshold()
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
            now_iso = self._now_iso()
            error_msg = str(
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

        self._send_failure_webhook(
            plugin_id=plugin_id,
            instance=instance,
            webhook_sender=webhook_sender,
        )

    def reset_circuit_breaker(self, plugin_id: str, instance: str) -> bool:
        """Clear the paused state and failure counter for a plugin instance."""
        plugin_instance = self._find_plugin_instance(plugin_id, instance)
        if plugin_instance is None:
            return False
        changed = (
            plugin_instance.paused
            or plugin_instance.consecutive_failure_count > 0
            or plugin_instance.disabled_reason is not None
        )
        plugin_instance.consecutive_failure_count = 0
        plugin_instance.paused = False
        plugin_instance.disabled_reason = None
        set_circuit_breaker_open(plugin_id, False)
        safe_pid = str(plugin_id).replace("\r", "").replace("\n", "")[:64]
        safe_inst = str(instance).replace("\r", "").replace("\n", "")[:64]
        logger.info(
            "plugin circuit_breaker: manual_reset | plugin_id=%s instance=%s",
            safe_pid,
            safe_inst,
        )
        if changed:
            try:
                self.device_config.write_config()
            except Exception:
                logger.warning(
                    "plugin circuit_breaker: failed to persist manual reset for %s/%s",
                    safe_pid,
                    safe_inst,
                    exc_info=True,
                )
        return True

    def snapshot(self) -> dict[str, HealthEntry]:
        """Return a shallow copy of the health snapshot."""
        return dict(self.plugin_health)

    def _find_plugin_instance(
        self, plugin_id: str, instance: str | None
    ) -> PluginInstanceLike | None:
        if not instance:
            return None
        return self.device_config.get_playlist_manager().find_plugin(
            plugin_id, instance
        )

    def _send_failure_webhook(
        self,
        *,
        plugin_id: str,
        instance: str | None,
        webhook_sender: Callable[[list[str], dict[str, object]], None] | None,
    ) -> None:
        if webhook_sender is None:
            return
        try:
            webhook_urls = self.device_config.get_config("webhook_urls", default=[])
            if not isinstance(webhook_urls, list) or not webhook_urls:
                return
            now_iso = self._now_iso()
            error_msg = str(
                self.plugin_health.get(plugin_id, {}).get("last_error") or "unknown"
            )
            payload: dict[str, object] = {
                "event": "plugin_failure",
                "plugin_id": plugin_id,
                "instance_name": instance,
                "error": error_msg,
                "ts": now_iso,
            }
            webhook_sender(webhook_urls, payload)
        except Exception:
            logger.warning(
                "webhook: unexpected error building webhook payload", exc_info=True
            )

    def _now_iso(self) -> str:
        """Return the current device-local timestamp normalized to UTC ISO format."""
        device_config = cast(Any, self.device_config)
        current_dt = cast(datetime, now_device_tz(device_config))
        return current_dt.astimezone(UTC).isoformat()

    @staticmethod
    def _entry_int(entry: HealthEntry, key: str) -> int:
        """Coerce a health-entry counter to ``int`` with a safe default."""
        value = entry.get(key, 0)
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, (int, float, str)):
            try:
                return int(value)
            except ValueError:
                return 0
        return 0
