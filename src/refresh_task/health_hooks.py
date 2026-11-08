"""Plugin-health and circuit-breaker hooks mixed into ``RefreshTask``."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, cast

from refresh_task.health import PluginHealthTracker
from utils.webhooks import send_failure_webhook


class PluginHealthMixin:
    """Delegates plugin-health bookkeeping to ``self.health_tracker``."""

    if TYPE_CHECKING:
        health_tracker: PluginHealthTracker

    @staticmethod
    def _get_circuit_breaker_threshold() -> int:
        """Return the consecutive-failure threshold before a plugin is paused.

        Reads ``PLUGIN_FAILURE_THRESHOLD`` from the environment (default 5).
        """
        return int(PluginHealthTracker.circuit_breaker_threshold())

    def _update_plugin_health_positional(
        self,
        plugin_id: str,
        instance: str | None,
        ok: bool,
        metrics: Mapping[str, Any] | None,
        error: str | None,
    ) -> None:
        """Positional adapter for collaborators that update plugin health."""
        self._update_plugin_health(
            plugin_id=plugin_id,
            instance=instance,
            ok=ok,
            metrics=dict(metrics) if metrics is not None else None,
            error=error,
        )

    def _update_plugin_health(
        self,
        plugin_id: str,
        instance: str | None,
        ok: bool,
        metrics: dict[str, Any] | None,
        error: str | None,
    ) -> None:
        """Update the in-memory health entry for a plugin and trigger circuit-breaker logic.

        Increments success or failure counters, stamps ``last_seen``, records
        timing metrics, and delegates to :meth:`_cb_on_success` or
        :meth:`_cb_on_failure` to manage the circuit-breaker state.

        Args:
            plugin_id: The unique plugin type identifier (e.g. ``"clock"``).
            instance: The named plugin instance within the playlist, or ``None``
                when the instance is unavailable.
            ok: ``True`` if the refresh succeeded; ``False`` on failure.
            metrics: Optional timing/steps dict to store on the health entry.
            error: Human-readable error string to store when *ok* is ``False``.
        """
        self.health_tracker.update(
            plugin_id=plugin_id,
            instance=instance,
            ok=ok,
            metrics=metrics,
            error=error,
            on_success=self._cb_on_success,
            on_failure=self._cb_on_failure,
        )

    def _cb_on_success(
        self, plugin_instance: Any, plugin_id: str, instance: str | None
    ) -> None:
        """Reset the circuit breaker on a successful refresh."""
        self.health_tracker.on_success(plugin_instance, plugin_id, instance)

    def _cb_on_failure(
        self, plugin_instance: Any, plugin_id: str, instance: str | None
    ) -> None:
        """Increment the failure counter and pause the plugin if threshold exceeded."""
        self.health_tracker.on_failure(
            plugin_instance,
            plugin_id,
            instance,
            webhook_sender=send_failure_webhook,
        )

    def reset_circuit_breaker(self, plugin_id: str, instance: str) -> bool:
        """Clear the paused state and failure counter for a plugin instance.

        Returns True if the instance was found and reset, False otherwise.
        """
        return bool(self.health_tracker.reset_circuit_breaker(plugin_id, instance))

    def get_health_snapshot(self) -> dict[str, Any]:
        return cast(dict[str, Any], self.health_tracker.snapshot())
