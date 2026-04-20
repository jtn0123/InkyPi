# pyright: reportMissingImports=false
"""Tests for the plugin circuit-breaker (JTN-301).

Covers:
- 5 consecutive failures → plugin paused
- Success resets counter to 0
- Paused plugin skipped by _determine_next_plugin
- Configurable threshold via PLUGIN_FAILURE_THRESHOLD env var
- reset_circuit_breaker method
- /plugin_instance/<plugin_id>/<instance_name>/force_retry endpoint
"""

import os
from datetime import UTC, datetime
from unittest.mock import MagicMock

from model import Playlist, PluginInstance
from refresh_task import RefreshTask

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_task(device_config_dev):
    dm = MagicMock()
    return RefreshTask(device_config_dev, dm)


def _make_plugin_instance(plugin_id="weather", name="my_weather"):
    return PluginInstance(
        plugin_id=plugin_id,
        name=name,
        settings={},
        refresh={"interval": 3600},
    )


def _add_plugin_to_pm(device_config_dev, plugin_instance):
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
    def test_default_threshold_is_5(self):
        original = os.environ.copy()
        os.environ.pop("PLUGIN_FAILURE_THRESHOLD", None)
        try:
            assert RefreshTask._get_circuit_breaker_threshold() == 5
        finally:
            os.environ.clear()
            os.environ.update(original)

    def test_env_var_overrides_threshold(self, monkeypatch):
        monkeypatch.setenv("PLUGIN_FAILURE_THRESHOLD", "3")
        assert RefreshTask._get_circuit_breaker_threshold() == 3

    def test_invalid_env_var_falls_back_to_5(self, monkeypatch):
        monkeypatch.setenv("PLUGIN_FAILURE_THRESHOLD", "notanumber")
        assert RefreshTask._get_circuit_breaker_threshold() == 5

    def test_minimum_threshold_is_1(self, monkeypatch):
        monkeypatch.setenv("PLUGIN_FAILURE_THRESHOLD", "0")
        assert RefreshTask._get_circuit_breaker_threshold() == 1


# ---------------------------------------------------------------------------
# Failure tracking and pausing
# ---------------------------------------------------------------------------


class TestCircuitBreakerFailures:
    def test_consecutive_failures_increment_counter(
        self, device_config_dev, monkeypatch
    ):
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
        self, device_config_dev, monkeypatch
    ):
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
        self, device_config_dev, monkeypatch
    ):
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

    def test_configurable_threshold_honored(self, device_config_dev, monkeypatch):
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

    def test_no_plugin_instance_does_not_crash(self, device_config_dev, monkeypatch):
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
    def test_success_resets_counter_to_zero(self, device_config_dev, monkeypatch):
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

    def test_success_unpauses_plugin(self, device_config_dev, monkeypatch):
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

    def test_manual_reset_circuit_breaker(self, device_config_dev, monkeypatch):
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
        self, device_config_dev, monkeypatch
    ):
        task = _make_task(device_config_dev)
        result = task.reset_circuit_breaker("weather", "does_not_exist")
        assert result is False

    def test_manual_reset_persists_and_clears_metric(
        self, device_config_dev, monkeypatch
    ):
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
        self, device_config_dev, monkeypatch
    ):
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
    def _setup_playlist(self, device_config_dev, plugin_instances):
        """Create a fresh playlist with the given plugin instances."""
        pm = device_config_dev.get_playlist_manager()
        # Remove existing playlists and add a clean one
        pm.playlists = []
        playlist = Playlist("CircuitTest", "00:00", "24:00")
        playlist.plugins = plugin_instances
        pm.playlists.append(playlist)
        pm.active_playlist = "CircuitTest"
        return pm

    def test_paused_plugin_skipped_by_scheduler(self, device_config_dev, monkeypatch):
        from model import RefreshInfo

        monkeypatch.setenv("PLUGIN_FAILURE_THRESHOLD", "5")
        task = _make_task(device_config_dev)

        paused_pi = _make_plugin_instance("weather", "paused_weather")
        paused_pi.paused = True
        paused_pi.consecutive_failure_count = 5

        good_pi = _make_plugin_instance("clock", "my_clock")

        pm = self._setup_playlist(device_config_dev, [paused_pi, good_pi])

        latest_refresh = RefreshInfo(
            refresh_type="Playlist",
            plugin_id="clock",
            refresh_time=None,
            image_hash=None,
        )

        current_dt = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
        playlist, plugin = task._determine_next_plugin(pm, latest_refresh, current_dt)

        # Should have skipped the paused plugin and returned the good one
        assert plugin is not None
        assert plugin.name == "my_clock"
        assert plugin.paused is False

    def test_all_paused_returns_none(self, device_config_dev, monkeypatch):
        from model import RefreshInfo

        monkeypatch.setenv("PLUGIN_FAILURE_THRESHOLD", "5")
        task = _make_task(device_config_dev)

        paused1 = _make_plugin_instance("weather", "w1")
        paused1.paused = True
        paused2 = _make_plugin_instance("clock", "c1")
        paused2.paused = True

        pm = self._setup_playlist(device_config_dev, [paused1, paused2])

        latest_refresh = RefreshInfo(
            refresh_type="Playlist",
            plugin_id="weather",
            refresh_time=None,
            image_hash=None,
        )

        current_dt = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
        playlist, plugin = task._determine_next_plugin(pm, latest_refresh, current_dt)

        assert plugin is None

    def test_non_paused_plugin_not_skipped(self, device_config_dev, monkeypatch):
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
    def test_default_values(self):
        pi = PluginInstance("weather", "inst", {}, {"interval": 3600})
        assert pi.consecutive_failure_count == 0
        assert pi.paused is False

    def test_to_dict_includes_circuit_breaker_fields(self):
        pi = PluginInstance("weather", "inst", {}, {"interval": 3600})
        pi.consecutive_failure_count = 3
        pi.paused = True
        d = pi.to_dict()
        assert d["consecutive_failure_count"] == 3
        assert d["paused"] is True

    def test_from_dict_restores_circuit_breaker_fields(self):
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

    def test_from_dict_defaults_when_fields_absent(self):
        data = {
            "plugin_id": "weather",
            "name": "inst",
            "plugin_settings": {},
            "refresh": {"interval": 3600},
        }
        pi = PluginInstance.from_dict(data)
        assert pi.consecutive_failure_count == 0
        assert pi.paused is False


# ---------------------------------------------------------------------------
# Force-retry endpoint
# ---------------------------------------------------------------------------


class TestForceRetryEndpoint:
    def _make_app(self, device_config_dev, refresh_task):
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

    def test_force_retry_resets_paused_plugin(self, device_config_dev):
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

    def test_force_retry_returns_404_for_unknown_instance(self, device_config_dev):
        task = _make_task(device_config_dev)
        app = self._make_app(device_config_dev, task)
        with app.test_client() as client:
            resp = client.post("/plugin_instance/weather/nonexistent/force_retry")
            assert resp.status_code == 404

    def test_force_retry_returns_503_when_no_refresh_task(self, device_config_dev):
        app = self._make_app(device_config_dev, None)
        with app.test_client() as client:
            resp = client.post("/plugin_instance/weather/my_weather/force_retry")
            assert resp.status_code == 503
