"""Plugin health and circuit-breaker helpers for ``RefreshTask``."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Protocol, cast

from utils.metrics import (
    record_refresh_failure,
    record_refresh_success,
    set_circuit_breaker_open,
)
from utils.time_utils import now_device_tz

logger = logging.getLogger(__name__)

#: How long a paused plugin rests before one automatic probe refresh is tried.
_DEFAULT_PAUSE_COOLDOWN_SECONDS = 6 * 60 * 60

# Control characters that would let a crafted value forge extra log lines, or
# break out of the single-line reason the UI renders.
_CONTROL_CHARS = str.maketrans("", "", "\r\n\t\x00")


def _clean(value: object) -> str:
    """Return *value* as a single-line string, or "" if it is not usable."""
    if not isinstance(value, str):
        return ""
    return value.translate(_CONTROL_CHARS).strip()


if TYPE_CHECKING:
    from config import Config

HealthEntry = dict[str, object]
Metrics = dict[str, object]


def _parse_iso(value: object) -> datetime | None:
    """Parse a stored ISO timestamp; naive values are UTC, junk is ``None``."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


class PluginInstanceLike(Protocol):
    """Playlist instance surface needed for circuit-breaker updates."""

    paused: bool
    consecutive_failure_count: int
    disabled_reason: str | None
    paused_at: str | None


class SupportsPlaylistLookup(Protocol):
    """Playlist manager surface needed to resolve plugin instances."""

    def find_plugin(
        self, plugin_id: str, instance_name: str
    ) -> PluginInstanceLike | None: ...


class SupportsPluginHealth(Protocol):
    """Config surface needed by plugin-health bookkeeping."""

    def get_playlist_manager(self) -> SupportsPlaylistLookup: ...

    def get_config(self, key: str, default: object = ...) -> object: ...

    def update_atomic(self, update_fn: Callable[[dict[str, Any]], None]) -> None: ...


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

    @staticmethod
    def pause_cooldown_seconds(environ: Mapping[str, str] | None = None) -> int | None:
        """Return how long a paused plugin waits before an automatic probe.

        Read from ``PLUGIN_PAUSE_COOLDOWN_SECONDS`` (default six hours), next to
        ``PLUGIN_FAILURE_THRESHOLD``. Invalid values fall back to the default;
        ``0`` or a negative value turns automatic probing off, leaving the
        manual "Force retry" as the only way out of a pause.
        """
        env = os.environ if environ is None else environ
        try:
            value = int(
                env.get(
                    "PLUGIN_PAUSE_COOLDOWN_SECONDS",
                    str(_DEFAULT_PAUSE_COOLDOWN_SECONDS),
                )
            )
        except (ValueError, TypeError):
            return _DEFAULT_PAUSE_COOLDOWN_SECONDS
        return value if value > 0 else None

    @classmethod
    def next_probe_at(
        cls, plugin_instance: PluginInstanceLike, now: datetime
    ) -> datetime | None:
        """Return when a paused instance may next be probed, or ``None``.

        ``None`` means the instance is not paused or automatic probing is off.
        A pause with no usable ``paused_at`` (written before the field existed,
        or hand-edited) is due at *now*: its age is unknown, and a pause that
        predates this code is old enough that waiting longer only prolongs it.
        """
        if not plugin_instance.paused:
            return None
        cooldown = cls.pause_cooldown_seconds()
        if cooldown is None:
            return None
        paused_at = _parse_iso(getattr(plugin_instance, "paused_at", None))
        if paused_at is None:
            return now
        return paused_at + timedelta(seconds=cooldown)

    @classmethod
    def probe_due(cls, plugin_instance: PluginInstanceLike, now: datetime) -> bool:
        """Return whether a paused instance has rested long enough to retry."""
        due_at = cls.next_probe_at(plugin_instance, now)
        return due_at is not None and now >= due_at

    def begin_probe(
        self, plugin_instance: PluginInstanceLike, plugin_id: str, instance: str
    ) -> None:
        """Restart the cooldown before a paused instance is retried.

        Stamped and persisted *before* the probe runs, so a probe that takes
        the whole process down (the crash-quarantine case) still waits a full
        cooldown before the next attempt instead of being retried on every
        restart. A successful probe clears the pause through ``on_success``.
        """
        now_iso = self._now_iso()

        def _stamp() -> None:
            plugin_instance.paused_at = now_iso

        self._persist(
            _stamp,
            "plugin circuit_breaker: failed to persist probe start for %s/%s",
            plugin_id,
            instance,
        )
        logger.info(
            "plugin circuit_breaker: probing paused plugin | plugin_id=%s "
            "instance=%s failures=%s reason=%s",
            plugin_id,
            instance,
            plugin_instance.consecutive_failure_count,
            plugin_instance.disabled_reason or "not recorded",
        )

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
        set_circuit_breaker_open(plugin_id, False)
        if not self._breaker_state_set(plugin_instance):
            return
        logger.info(
            "plugin circuit_breaker: recovered | plugin_id=%s instance=%s",
            plugin_id,
            instance,
        )
        self._persist(
            lambda: self._clear_breaker(plugin_instance),
            "plugin circuit_breaker: failed to persist reset for %s/%s",
            plugin_id,
            instance,
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
        if plugin_instance is None:
            return
        if plugin_instance.paused:
            self._record_failed_probe(plugin_instance, plugin_id, instance)
            return
        threshold = self.circuit_breaker_threshold()
        error_msg = str(
            self.plugin_health.get(plugin_id, {}).get("last_error") or "unknown"
        )

        def _record_failure() -> None:
            # The counter's read-modify-write happens under the config lock so
            # a concurrent update_atomic rollback cannot undo it.
            plugin_instance.consecutive_failure_count += 1
            if plugin_instance.consecutive_failure_count >= threshold:
                plugin_instance.paused = True
                plugin_instance.paused_at = self._now_iso()
                plugin_instance.disabled_reason = (
                    f"Paused after {plugin_instance.consecutive_failure_count} "
                    f"consecutive failures at {self._now_iso()}. "
                    f"Last error: {error_msg[:120]}"
                )

        self._persist(
            _record_failure,
            "plugin circuit_breaker: failed to persist failure state for %s/%s",
            plugin_id,
            instance,
        )
        logger.warning(
            "plugin circuit_breaker: failure | plugin_id=%s instance=%s count=%d/%d",
            plugin_id,
            instance,
            plugin_instance.consecutive_failure_count,
            threshold,
        )
        # The early return above means any pause now is new, and a failed
        # write rolls the model back, so this reflects what was persisted.
        if self._is_paused(plugin_instance):
            set_circuit_breaker_open(plugin_id, True)
            logger.error(
                "plugin circuit_breaker: paused | plugin_id=%s instance=%s"
                " paused after %d consecutive failures",
                plugin_id,
                instance,
                plugin_instance.consecutive_failure_count,
            )

        self._send_failure_webhook(
            plugin_id=plugin_id,
            instance=instance,
            webhook_sender=webhook_sender,
        )

    def quarantine_after_crash(self, breadcrumb: Mapping[str, object]) -> bool:
        """Pause the plugin that was in flight when the previous run died.

        The circuit breaker only sees *handled* failures. A plugin that gets the
        process OOM-killed or segfaults raises nothing catchable, so it never
        trips the breaker — it simply crash-loops, and each loop is another SD
        write. Once the process is gone the in-memory failure count is gone too,
        so the streak never accumulates either.

        This is the same move ``crashlog``'s SD sentinel makes in the
        ESP32-Garage-Fan firmware: a resource that killed the last boot is
        disabled on this one so it "can never boot-loop the controller".

        Reuses the existing paused / ``disabled_reason`` plumbing so the UI,
        the API and the manual re-enable path all work unchanged.

        Args:
            breadcrumb: The record left by the run that died — see
                :func:`utils.crash_breadcrumb.examine_boot`.

        Returns:
            Whether a plugin instance was newly quarantined.
        """
        # The breadcrumb is read back from disk after a crash, so it is
        # untrusted input: it may be truncated mid-write or hand-edited. Strip
        # control characters at this boundary rather than at each use — these
        # values reach the log *and* `disabled_reason`, which the web UI shows.
        plugin_id = _clean(breadcrumb.get("plugin_id"))
        instance = _clean(breadcrumb.get("instance"))
        if not plugin_id:
            return False
        if not instance:
            # Without an instance we cannot name a single playlist entry, and
            # pausing every instance of the plugin would be too blunt.
            logger.warning(
                "crash quarantine: previous run died in plugin %s but named no "
                "instance; not quarantining",
                plugin_id,
            )
            return False

        plugin_instance = self._find_plugin_instance(plugin_id, instance)
        if plugin_instance is None or plugin_instance.paused:
            return False

        started = breadcrumb.get("started_at") or "an earlier run"

        def _quarantine() -> None:
            plugin_instance.paused = True
            plugin_instance.paused_at = self._now_iso()
            plugin_instance.disabled_reason = (
                f"Paused automatically: the service died while this plugin was "
                f"rendering (started {started}). It is retried automatically "
                f"after a cooldown, or re-enable it once the cause is understood."
            )

        set_circuit_breaker_open(plugin_id, True)
        logger.error(
            "crash quarantine: paused | plugin_id=%s instance=%s — it was in "
            "flight when the previous run died",
            plugin_id,
            instance,
        )
        self._persist(
            _quarantine,
            "crash quarantine: failed to persist paused state for %s/%s",
            plugin_id,
            instance,
        )
        return True

    def reset_circuit_breaker(self, plugin_id: str, instance: str) -> bool:
        """Clear the paused state and failure counter for a plugin instance."""
        plugin_instance = self._find_plugin_instance(plugin_id, instance)
        if plugin_instance is None:
            return False
        changed = self._breaker_state_set(plugin_instance)
        set_circuit_breaker_open(plugin_id, False)
        safe_pid = str(plugin_id).replace("\r", "").replace("\n", "")[:64]
        safe_inst = str(instance).replace("\r", "").replace("\n", "")[:64]
        logger.info(
            "plugin circuit_breaker: manual_reset | plugin_id=%s instance=%s",
            safe_pid,
            safe_inst,
        )
        if changed:
            self._persist(
                lambda: self._clear_breaker(plugin_instance),
                "plugin circuit_breaker: failed to persist manual reset for %s/%s",
                safe_pid,
                safe_inst,
            )
        return True

    @staticmethod
    def _breaker_state_set(plugin_instance: PluginInstanceLike) -> bool:
        """Return whether any circuit-breaker field differs from its reset value."""
        return (
            plugin_instance.paused
            or plugin_instance.consecutive_failure_count > 0
            or plugin_instance.disabled_reason is not None
            or getattr(plugin_instance, "paused_at", None) is not None
        )

    @staticmethod
    def _is_paused(plugin_instance: PluginInstanceLike) -> bool:
        # Read through a call: type checkers otherwise keep the "not paused"
        # narrowing from on_failure's early return across the mutation.
        return bool(plugin_instance.paused)

    @staticmethod
    def _clear_breaker(plugin_instance: PluginInstanceLike) -> None:
        plugin_instance.consecutive_failure_count = 0
        plugin_instance.paused = False
        plugin_instance.disabled_reason = None
        plugin_instance.paused_at = None

    def _record_failed_probe(
        self,
        plugin_instance: PluginInstanceLike,
        plugin_id: str,
        instance: str | None,
    ) -> None:
        """Keep a paused instance paused after another failure, and say so.

        Reached when a probe (or a manual refresh) of a paused instance fails.
        The counter is left alone — it already records the streak that tripped
        the breaker — but the reason is refreshed so the UI shows the latest
        error, and the cooldown restarts from now.
        """
        error_msg = str(
            self.plugin_health.get(plugin_id, {}).get("last_error") or "unknown"
        )
        now_iso = self._now_iso()

        def _restamp() -> None:
            plugin_instance.paused_at = now_iso
            plugin_instance.disabled_reason = (
                f"Still failing on retry at {now_iso} "
                f"(paused after {plugin_instance.consecutive_failure_count} "
                f"consecutive failures). Last error: {error_msg[:120]}"
            )

        self._persist(
            _restamp,
            "plugin circuit_breaker: failed to persist probe failure for %s/%s",
            plugin_id,
            instance,
        )
        logger.warning(
            "plugin circuit_breaker: probe failed; staying paused | plugin_id=%s "
            "instance=%s retry_in_s=%s",
            plugin_id,
            instance,
            self.pause_cooldown_seconds(),
        )

    def _persist(
        self, mutate: Callable[[], None], failure_msg: str, *args: object
    ) -> None:
        """Apply *mutate* to the model and persist it under the config lock.

        The refresh thread and web threads share these model objects. A bare
        mutation followed by ``write_config()`` can land between another
        thread's ``update_atomic`` snapshot and its rollback, which then
        silently restores the old value. ``update_atomic`` serialises the
        mutation with every other config transaction and rolls it back if the
        write fails, matching ``write_config``'s own rollback on failure.
        """
        try:
            self.device_config.update_atomic(lambda _config: mutate())
        except Exception:
            logger.warning(failure_msg, *args, exc_info=True)

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
        device_config = cast("Config", self.device_config)
        current_dt = now_device_tz(device_config)
        return str(current_dt.astimezone(UTC).isoformat())

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
