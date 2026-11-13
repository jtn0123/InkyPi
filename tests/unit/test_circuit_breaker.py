# pyright: reportMissingImports=false
"""Tests for the plugin circuit-breaker (JTN-301).

Covers:
- 5 consecutive failures → plugin paused
- Success resets counter to 0
- Paused plugin skipped by _determine_next_plugin
- Configurable threshold via PLUGIN_FAILURE_THRESHOLD env var
- reset_circuit_breaker method
- /plugin_instance/<plugin_id>/<instance_name>/force_retry endpoint
- Automatic retry: one probe per PLUGIN_PAUSE_COOLDOWN_SECONDS (default 6 h)
"""

import logging
import os
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock

import pytest

from model import Playlist, PluginInstance
from refresh_task import RefreshTask

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_task(device_config_dev: Any) -> Any:
    dm = MagicMock()
    return RefreshTask(device_config_dev, dm)


def _make_plugin_instance(plugin_id: Any = "weather", name: Any = "my_weather") -> Any:
    return PluginInstance(
        plugin_id=plugin_id,
        name=name,
        settings={},
        refresh={"interval": 3600},
    )


def _add_plugin_to_pm(device_config_dev: Any, plugin_instance: Any) -> Any:
    """Add a plugin instance to the Default playlist of the playlist manager."""
    pm = device_config_dev.get_playlist_manager()
    playlist = pm.get_playlist("Default")
    if playlist is None:
        pm.add_default_playlist()
        playlist = pm.get_playlist("Default")
    playlist.plugins.append(plugin_instance)
    return pm


# ---------------------------------------------------------------------------
# Threshold configuration
# ---------------------------------------------------------------------------


class TestCircuitBreakerThreshold:
    def test_default_threshold_is_5(self) -> None:
        original = os.environ.copy()
        os.environ.pop("PLUGIN_FAILURE_THRESHOLD", None)
        try:
            assert RefreshTask._get_circuit_breaker_threshold() == 5
        finally:
            os.environ.clear()
            os.environ.update(original)

    def test_env_var_overrides_threshold(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PLUGIN_FAILURE_THRESHOLD", "3")
        assert RefreshTask._get_circuit_breaker_threshold() == 3

    def test_invalid_env_var_falls_back_to_5(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PLUGIN_FAILURE_THRESHOLD", "notanumber")
        assert RefreshTask._get_circuit_breaker_threshold() == 5

    def test_minimum_threshold_is_1(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PLUGIN_FAILURE_THRESHOLD", "0")
        assert RefreshTask._get_circuit_breaker_threshold() == 1


# ---------------------------------------------------------------------------
# Failure tracking and pausing
# ---------------------------------------------------------------------------


class TestCircuitBreakerFailures:
    def test_consecutive_failures_increment_counter(
        self, device_config_dev: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PLUGIN_FAILURE_THRESHOLD", "5")
        task = _make_task(device_config_dev)
        pi = _make_plugin_instance()
        _add_plugin_to_pm(device_config_dev, pi)

        for i in range(1, 4):
            task._update_plugin_health(
                plugin_id="weather",
                instance="my_weather",
                ok=False,
                metrics=None,
                error="API error",
            )
            assert pi.consecutive_failure_count == i
            assert not pi.paused

    def test_five_consecutive_failures_pause_plugin(
        self, device_config_dev: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PLUGIN_FAILURE_THRESHOLD", "5")
        task = _make_task(device_config_dev)
        pi = _make_plugin_instance()
        _add_plugin_to_pm(device_config_dev, pi)

        for _ in range(5):
            task._update_plugin_health(
                plugin_id="weather",
                instance="my_weather",
                ok=False,
                metrics=None,
                error="API error",
            )

        assert pi.paused is True
        assert pi.consecutive_failure_count == 5

    def test_counter_does_not_increment_once_paused(
        self, device_config_dev: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PLUGIN_FAILURE_THRESHOLD", "5")
        task = _make_task(device_config_dev)
        pi = _make_plugin_instance()
        _add_plugin_to_pm(device_config_dev, pi)

        for _ in range(5):
            task._update_plugin_health(
                plugin_id="weather",
                instance="my_weather",
                ok=False,
                metrics=None,
                error="API error",
            )
        assert pi.paused

        # additional failures should not increment beyond threshold
        task._update_plugin_health(
            plugin_id="weather",
            instance="my_weather",
            ok=False,
            metrics=None,
            error="API error",
        )
        assert pi.consecutive_failure_count == 5  # still at threshold

    def test_configurable_threshold_honored(
        self, device_config_dev: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PLUGIN_FAILURE_THRESHOLD", "3")
        task = _make_task(device_config_dev)
        pi = _make_plugin_instance()
        _add_plugin_to_pm(device_config_dev, pi)

        for _ in range(3):
            task._update_plugin_health(
                plugin_id="weather",
                instance="my_weather",
                ok=False,
                metrics=None,
                error="bad key",
            )

        assert pi.paused is True
        assert pi.consecutive_failure_count == 3

    def test_no_plugin_instance_does_not_crash(
        self, device_config_dev: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Health update without a matching PluginInstance should not raise."""
        monkeypatch.setenv("PLUGIN_FAILURE_THRESHOLD", "5")
        task = _make_task(device_config_dev)

        # instance="nonexistent" won't be found in the playlist manager
        task._update_plugin_health(
            plugin_id="weather",
            instance="nonexistent",
            ok=False,
            metrics=None,
            error="API error",
        )
        # Should not raise; health dict updated but no plugin_instance fields touched


# ---------------------------------------------------------------------------
# Success resets counter
# ---------------------------------------------------------------------------


class TestCircuitBreakerReset:
    def test_success_resets_counter_to_zero(
        self, device_config_dev: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PLUGIN_FAILURE_THRESHOLD", "5")
        task = _make_task(device_config_dev)
        pi = _make_plugin_instance()
        _add_plugin_to_pm(device_config_dev, pi)

        # 3 failures
        for _ in range(3):
            task._update_plugin_health(
                plugin_id="weather",
                instance="my_weather",
                ok=False,
                metrics=None,
                error="err",
            )
        assert pi.consecutive_failure_count == 3

        # success
        task._update_plugin_health(
            plugin_id="weather",
            instance="my_weather",
            ok=True,
            metrics={"request_ms": 100},
            error=None,
        )
        assert pi.consecutive_failure_count == 0
        assert pi.paused is False

    def test_success_unpauses_plugin(
        self, device_config_dev: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PLUGIN_FAILURE_THRESHOLD", "5")
        task = _make_task(device_config_dev)
        pi = _make_plugin_instance()
        _add_plugin_to_pm(device_config_dev, pi)

        # Pause it manually
        pi.paused = True
        pi.consecutive_failure_count = 5

        task._update_plugin_health(
            plugin_id="weather",
            instance="my_weather",
            ok=True,
            metrics=None,
            error=None,
        )
        assert pi.paused is False
        assert pi.consecutive_failure_count == 0

    def test_manual_reset_circuit_breaker(
        self, device_config_dev: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        task = _make_task(device_config_dev)
        pi = _make_plugin_instance()
        _add_plugin_to_pm(device_config_dev, pi)

        pi.paused = True
        pi.consecutive_failure_count = 5

        result = task.reset_circuit_breaker("weather", "my_weather")
        assert result is True
        assert pi.paused is False
        assert pi.consecutive_failure_count == 0

    def test_manual_reset_returns_false_for_unknown_instance(
        self, device_config_dev: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        task = _make_task(device_config_dev)
        result = task.reset_circuit_breaker("weather", "does_not_exist")
        assert result is False

    def test_manual_reset_persists_and_clears_metric(
        self, device_config_dev: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Manual reset should persist config and clear the circuit-breaker metric."""
        task = _make_task(device_config_dev)
        pi = _make_plugin_instance()
        _add_plugin_to_pm(device_config_dev, pi)

        pi.paused = True
        pi.consecutive_failure_count = 5
        pi.disabled_reason = "Paused after 5 failures"

        metric_calls: list[tuple[str, bool]] = []
        monkeypatch.setattr(
            "refresh_task.health.set_circuit_breaker_open",
            lambda pid, is_open: metric_calls.append((pid, is_open)),
        )
        write_calls: list[int] = []
        monkeypatch.setattr(
            device_config_dev,
            "write_config",
            lambda: write_calls.append(1),
        )

        assert task.reset_circuit_breaker("weather", "my_weather") is True
        assert ("weather", False) in metric_calls
        assert len(write_calls) == 1

    def test_manual_reset_no_persist_when_unchanged(
        self, device_config_dev: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Reset on an already-clean instance should not persist config."""
        task = _make_task(device_config_dev)
        pi = _make_plugin_instance()
        _add_plugin_to_pm(device_config_dev, pi)
        # Instance is already in a clean state.

        write_calls: list[int] = []
        monkeypatch.setattr(
            device_config_dev,
            "write_config",
            lambda: write_calls.append(1),
        )

        assert task.reset_circuit_breaker("weather", "my_weather") is True
        assert write_calls == []


# ---------------------------------------------------------------------------
# Scheduler skips paused plugins
# ---------------------------------------------------------------------------


class TestCircuitBreakerScheduler:
    def _setup_playlist(self, device_config_dev: Any, plugin_instances: Any) -> Any:
        """Create a fresh playlist with the given plugin instances."""
        pm = device_config_dev.get_playlist_manager()
        # Remove existing playlists and add a clean one
        pm.playlists = []
        playlist = Playlist("CircuitTest", "00:00", "24:00")
        playlist.plugins = plugin_instances
        pm.playlists.append(playlist)
        pm.active_playlist = "CircuitTest"
        return pm

    def test_paused_plugin_skipped_by_scheduler(
        self,
        device_config_dev: Any,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        from model import RefreshInfo

        monkeypatch.setenv("PLUGIN_FAILURE_THRESHOLD", "5")
        caplog.set_level(logging.INFO, logger="refresh_task.task")
        task = _make_task(device_config_dev)

        current_dt = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
        paused_pi = _make_plugin_instance("weather", "paused_weather")
        paused_pi.paused = True
        paused_pi.consecutive_failure_count = 5
        paused_pi.disabled_reason = "last API error"
        # Paused an hour ago: still inside the six-hour cooldown.
        paused_pi.paused_at = (current_dt - timedelta(hours=1)).isoformat()

        good_pi = _make_plugin_instance("clock", "my_clock")

        pm = self._setup_playlist(device_config_dev, [paused_pi, good_pi])

        latest_refresh = RefreshInfo(
            refresh_type="Playlist",
            plugin_id="clock",
            refresh_time=None,
            image_hash=None,
        )

        playlist, plugin = task._determine_next_plugin(pm, latest_refresh, current_dt)

        # Should have skipped the paused plugin and returned the good one
        assert plugin is not None
        assert plugin.name == "my_clock"
        assert plugin.paused is False
        assert "failures=5 reason=last API error" in caplog.text
        assert "next_retry=2025-01-01T17:00:00+00:00" in caplog.text

    def test_all_paused_returns_none(
        self, device_config_dev: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from model import RefreshInfo

        monkeypatch.setenv("PLUGIN_FAILURE_THRESHOLD", "5")
        task = _make_task(device_config_dev)

        current_dt = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
        recently = (current_dt - timedelta(minutes=5)).isoformat()
        paused1 = _make_plugin_instance("weather", "w1")
        paused1.paused = True
        paused1.paused_at = recently
        paused2 = _make_plugin_instance("clock", "c1")
        paused2.paused = True
        paused2.paused_at = recently

        pm = self._setup_playlist(device_config_dev, [paused1, paused2])

        latest_refresh = RefreshInfo(
            refresh_type="Playlist",
            plugin_id="weather",
            refresh_time=None,
            image_hash=None,
        )

        playlist, plugin = task._determine_next_plugin(pm, latest_refresh, current_dt)

        assert plugin is None

    def test_non_paused_plugin_not_skipped(
        self, device_config_dev: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from model import RefreshInfo

        monkeypatch.setenv("PLUGIN_FAILURE_THRESHOLD", "5")
        task = _make_task(device_config_dev)

        healthy_pi = _make_plugin_instance("weather", "healthy_weather")

        pm = self._setup_playlist(device_config_dev, [healthy_pi])

        latest_refresh = RefreshInfo(
            refresh_type="Playlist",
            plugin_id="weather",
            refresh_time=None,
            image_hash=None,
        )

        current_dt = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
        playlist, plugin = task._determine_next_plugin(pm, latest_refresh, current_dt)

        assert plugin is not None
        assert plugin.name == "healthy_weather"


# ---------------------------------------------------------------------------
# PluginInstance model — serialization round-trip
# ---------------------------------------------------------------------------


class TestPluginInstanceCircuitBreakerFields:
    def test_default_values(self) -> None:
        pi = PluginInstance("weather", "inst", {}, {"interval": 3600})
        assert pi.consecutive_failure_count == 0
        assert pi.paused is False

    def test_to_dict_includes_circuit_breaker_fields(self) -> None:
        pi = PluginInstance("weather", "inst", {}, {"interval": 3600})
        pi.consecutive_failure_count = 3
        pi.paused = True
        d = pi.to_dict()
        assert d["consecutive_failure_count"] == 3
        assert d["paused"] is True

    def test_from_dict_restores_circuit_breaker_fields(self) -> None:
        data = {
            "plugin_id": "weather",
            "name": "inst",
            "plugin_settings": {},
            "refresh": {"interval": 3600},
            "consecutive_failure_count": 4,
            "paused": True,
        }
        pi = PluginInstance.from_dict(data)
        assert pi.consecutive_failure_count == 4
        assert pi.paused is True

    def test_from_dict_defaults_when_fields_absent(self) -> None:
        data = {
            "plugin_id": "weather",
            "name": "inst",
            "plugin_settings": {},
            "refresh": {"interval": 3600},
        }
        pi = PluginInstance.from_dict(data)
        assert pi.consecutive_failure_count == 0
        assert pi.paused is False
        assert pi.paused_at is None
        assert "paused_at" not in pi.to_dict()

    def test_paused_at_round_trips(self) -> None:
        pi = PluginInstance("weather", "inst", {}, {"interval": 3600})
        pi.paused = True
        pi.paused_at = "2026-04-25T10:00:00+00:00"
        restored = PluginInstance.from_dict(pi.to_dict())
        assert restored.paused_at == "2026-04-25T10:00:00+00:00"


# ---------------------------------------------------------------------------
# Force-retry endpoint
# ---------------------------------------------------------------------------


class TestForceRetryEndpoint:
    def _make_app(self, device_config_dev: Any, refresh_task: Any) -> Any:
        """Create a minimal Flask test app with the plugin blueprint."""
        import sys

        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../src"))
        from flask import Flask

        from blueprints.plugin import plugin_bp

        app = Flask(
            __name__,
            template_folder=os.path.join(
                os.path.dirname(__file__), "../../src/templates"
            ),
        )
        app.secret_key = "test"
        app.config["DEVICE_CONFIG"] = device_config_dev
        app.config["REFRESH_TASK"] = refresh_task
        app.config["TESTING"] = True
        app.register_blueprint(plugin_bp)
        return app

    def test_force_retry_resets_paused_plugin(self, device_config_dev: Any) -> None:
        task = _make_task(device_config_dev)
        pi = _make_plugin_instance("weather", "my_weather")
        pi.paused = True
        pi.consecutive_failure_count = 5
        _add_plugin_to_pm(device_config_dev, pi)

        app = self._make_app(device_config_dev, task)
        with app.test_client() as client:
            resp = client.post("/plugin_instance/weather/my_weather/force_retry")
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["success"] is True

        assert pi.paused is False
        assert pi.consecutive_failure_count == 0

    def test_force_retry_returns_404_for_unknown_instance(
        self, device_config_dev: Any
    ) -> None:
        task = _make_task(device_config_dev)
        app = self._make_app(device_config_dev, task)
        with app.test_client() as client:
            resp = client.post("/plugin_instance/weather/nonexistent/force_retry")
            assert resp.status_code == 404

    def test_force_retry_returns_503_when_no_refresh_task(
        self, device_config_dev: Any
    ) -> None:
        app = self._make_app(device_config_dev, None)
        with app.test_client() as client:
            resp = client.post("/plugin_instance/weather/my_weather/force_retry")
            assert resp.status_code == 503


# ---------------------------------------------------------------------------
# Automatic retry of paused plugins (cooldown + probe)
# ---------------------------------------------------------------------------


def _latest_refresh() -> Any:
    from model import RefreshInfo

    return RefreshInfo(
        refresh_type="Playlist", plugin_id="clock", refresh_time=None, image_hash=None
    )


def _paused(plugin_id: str, name: str, paused_at: str | None) -> Any:
    pi = _make_plugin_instance(plugin_id, name)
    pi.paused = True
    pi.consecutive_failure_count = 5
    pi.disabled_reason = "Paused after 5 consecutive failures. Last error: boom"
    pi.paused_at = paused_at
    return pi


def _playlist_of(device_config_dev: Any, plugins: list[Any]) -> Any:
    pm = device_config_dev.get_playlist_manager()
    pm.playlists = []
    playlist = Playlist("CircuitTest", "00:00", "24:00")
    playlist.plugins = plugins
    pm.playlists.append(playlist)
    pm.active_playlist = "CircuitTest"
    return pm


class TestPauseCooldownSetting:
    def test_default_is_six_hours(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from refresh_task.health import PluginHealthTracker

        monkeypatch.delenv("PLUGIN_PAUSE_COOLDOWN_SECONDS", raising=False)
        assert PluginHealthTracker.pause_cooldown_seconds() == 6 * 3600

    def test_env_var_overrides(self) -> None:
        from refresh_task.health import PluginHealthTracker

        env = {"PLUGIN_PAUSE_COOLDOWN_SECONDS": "600"}
        assert PluginHealthTracker.pause_cooldown_seconds(env) == 600

    def test_invalid_value_falls_back_to_default(self) -> None:
        from refresh_task.health import PluginHealthTracker

        env = {"PLUGIN_PAUSE_COOLDOWN_SECONDS": "soon"}
        assert PluginHealthTracker.pause_cooldown_seconds(env) == 6 * 3600

    @pytest.mark.parametrize("value", ["0", "-5"])
    def test_non_positive_disables_auto_retry(self, value: str) -> None:
        from refresh_task.health import PluginHealthTracker

        env = {"PLUGIN_PAUSE_COOLDOWN_SECONDS": value}
        assert PluginHealthTracker.pause_cooldown_seconds(env) is None


class TestPausedPluginProbe:
    # Real time: the tracker stamps probes with the wall clock, so the
    # cooldown arithmetic in these tests must start from the same clock.
    NOW = datetime.now(UTC).replace(microsecond=0)

    def test_nothing_probes_before_the_cooldown(
        self, device_config_dev: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("PLUGIN_PAUSE_COOLDOWN_SECONDS", raising=False)
        task = _make_task(device_config_dev)
        stamp = (self.NOW - timedelta(hours=5, minutes=59)).isoformat()
        paused = _paused("apod", "apod_inst", stamp)
        clock = _make_plugin_instance("clock", "clock_inst")
        pm = _playlist_of(device_config_dev, [paused, clock])

        for _ in range(3):
            _, plugin = task._determine_next_plugin(pm, _latest_refresh(), self.NOW)
            assert plugin is clock

        assert paused.paused is True
        assert paused.paused_at == stamp  # no probe started, cooldown untouched

    def test_probe_is_selected_once_the_cooldown_has_elapsed(
        self,
        device_config_dev: Any,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        monkeypatch.delenv("PLUGIN_PAUSE_COOLDOWN_SECONDS", raising=False)
        caplog.set_level(logging.INFO, logger="refresh_task.health")
        task = _make_task(device_config_dev)
        stamp = (self.NOW - timedelta(hours=6)).isoformat()
        paused = _paused("apod", "apod_inst", stamp)
        clock = _make_plugin_instance("clock", "clock_inst")
        pm = _playlist_of(device_config_dev, [paused, clock])
        writes: list[int] = []
        monkeypatch.setattr(device_config_dev, "write_config", lambda: writes.append(1))

        _, plugin = task._determine_next_plugin(pm, _latest_refresh(), self.NOW)

        assert plugin is paused
        # Still paused until the probe succeeds, but the cooldown restarted and
        # was persisted before the probe runs (crash safety).
        assert paused.paused is True
        assert paused.paused_at is not None and paused.paused_at > stamp
        assert writes, "probe start must be persisted before the probe runs"
        assert "probing paused plugin" in caplog.text

    def test_env_cooldown_is_honoured(
        self, device_config_dev: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PLUGIN_PAUSE_COOLDOWN_SECONDS", "600")
        task = _make_task(device_config_dev)
        paused = _paused(
            "apod", "apod_inst", (self.NOW - timedelta(minutes=11)).isoformat()
        )
        pm = _playlist_of(device_config_dev, [paused])

        _, plugin = task._determine_next_plugin(pm, _latest_refresh(), self.NOW)
        assert plugin is paused

    def test_disabled_cooldown_never_probes(
        self, device_config_dev: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PLUGIN_PAUSE_COOLDOWN_SECONDS", "0")
        task = _make_task(device_config_dev)
        paused = _paused("apod", "apod_inst", None)
        pm = _playlist_of(device_config_dev, [paused])

        _, plugin = task._determine_next_plugin(pm, _latest_refresh(), self.NOW)
        assert plugin is None

    def test_persisted_old_pause_resumes_on_first_cycle(
        self, device_config_dev: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The owner's APOD entry: paused in April, written before paused_at
        existed. It must be probed on the first cycle after the upgrade, and
        resume when that probe succeeds."""
        monkeypatch.delenv("PLUGIN_PAUSE_COOLDOWN_SECONDS", raising=False)
        task = _make_task(device_config_dev)
        apod = PluginInstance.from_dict(
            {
                "plugin_id": "apod",
                "name": "NASA APOD",
                "plugin_settings": {},
                "refresh": {"interval": 3600},
                "consecutive_failure_count": 5,
                "paused": True,
                "disabled_reason": (
                    "Paused after 5 consecutive failures at "
                    "2026-04-25T08:00:00+00:00. Last error: Plugin 'apod' "
                    "returned image with wrong dimensions: expected 800x480, "
                    "got 1024x676"
                ),
            }
        )
        assert apod.paused_at is None
        clock = _make_plugin_instance("clock", "Clock")
        pm = _playlist_of(device_config_dev, [apod, clock])

        _, plugin = task._determine_next_plugin(pm, _latest_refresh(), self.NOW)
        assert plugin is apod

        task._update_plugin_health(
            plugin_id="apod", instance="NASA APOD", ok=True, metrics=None, error=None
        )
        assert apod.paused is False
        assert apod.consecutive_failure_count == 0
        assert apod.disabled_reason is None
        assert apod.paused_at is None
        persisted = device_config_dev.get_playlist_manager().find_plugin(
            "apod", "NASA APOD"
        )
        assert persisted is apod

    def test_failed_probe_stays_paused_and_restarts_the_cooldown(
        self, device_config_dev: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("PLUGIN_PAUSE_COOLDOWN_SECONDS", raising=False)
        task = _make_task(device_config_dev)
        stamp = (self.NOW - timedelta(hours=7)).isoformat()
        paused = _paused("apod", "apod_inst", stamp)
        clock = _make_plugin_instance("clock", "clock_inst")
        pm = _playlist_of(device_config_dev, [paused, clock])

        _, plugin = task._determine_next_plugin(pm, _latest_refresh(), self.NOW)
        assert plugin is paused
        task._update_plugin_health(
            plugin_id="apod",
            instance="apod_inst",
            ok=False,
            metrics=None,
            error="still broken",
        )

        assert paused.paused is True
        assert paused.consecutive_failure_count == 5
        assert paused.paused_at is not None and paused.paused_at > stamp
        assert "Still failing on retry" in (paused.disabled_reason or "")
        assert "still broken" in (paused.disabled_reason or "")

        # The playlist moves on, and the cooldown now runs from the probe.
        probe_time = datetime.fromisoformat(paused.paused_at)
        _, plugin = task._determine_next_plugin(
            pm, _latest_refresh(), probe_time + timedelta(hours=1)
        )
        assert plugin is clock
        _, plugin = task._determine_next_plugin(
            pm, _latest_refresh(), probe_time + timedelta(hours=6, seconds=1)
        )
        assert plugin is paused

    def test_unparseable_paused_at_is_treated_as_due(self) -> None:
        from refresh_task.health import PluginHealthTracker

        paused = _paused("apod", "apod_inst", "last tuesday")
        assert PluginHealthTracker.probe_due(paused, self.NOW)

    def test_naive_paused_at_is_read_as_utc(self) -> None:
        from refresh_task.health import PluginHealthTracker

        paused = _paused("apod", "apod_inst", "2026-11-12T10:00:00")
        now = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)
        due = PluginHealthTracker.next_probe_at(paused, now)
        assert due == datetime(2026, 11, 12, 16, 0, tzinfo=UTC)

    def test_tripping_the_breaker_stamps_paused_at(
        self, device_config_dev: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PLUGIN_FAILURE_THRESHOLD", "2")
        task = _make_task(device_config_dev)
        pi = _make_plugin_instance()
        _add_plugin_to_pm(device_config_dev, pi)
        for _ in range(2):
            task._update_plugin_health(
                plugin_id="weather",
                instance="my_weather",
                ok=False,
                metrics=None,
                error="API error",
            )
        assert pi.paused is True
        assert pi.paused_at is not None
        assert datetime.fromisoformat(pi.paused_at).tzinfo is not None

    def test_manual_reset_clears_paused_at(self, device_config_dev: Any) -> None:
        task = _make_task(device_config_dev)
        pi = _paused("weather", "my_weather", "2026-11-12T10:00:00+00:00")
        _add_plugin_to_pm(device_config_dev, pi)
        assert task.reset_circuit_breaker("weather", "my_weather") is True
        assert pi.paused_at is None
