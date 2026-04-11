# pyright: reportMissingImports=false
"""Tests for plugin failure fallback image and circuit-breaker persistence (JTN-499).

Covers:
- Fallback image is returned (not None) when a plugin always raises
- After 5 consecutive failures the instance's config entry is marked paused
- On a subsequent success the counter resets to 0 and disabled_reason is cleared
- Fallback image is displayed on failure in _perform_refresh
- Circuit-breaker state persists to disk (write_config called)
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from PIL import Image

from model import PluginInstance
from refresh_task import RefreshTask
from refresh_task.actions import PlaylistRefresh
from utils.fallback_image import render_error_image

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_task(device_config_dev):
    dm = MagicMock()
    dm.display_image.return_value = {"display_ms": 10, "preprocess_ms": 5}
    task = RefreshTask(device_config_dev, dm)
    return task, dm


def _make_plugin_instance(plugin_id="dummy", name="my_dummy"):
    return PluginInstance(
        plugin_id=plugin_id,
        name=name,
        settings={},
        refresh={"interval": 3600},
    )


def _add_plugin_to_pm(device_config_dev, plugin_instance):
    pm = device_config_dev.get_playlist_manager()
    playlist = pm.get_playlist("Default")
    if playlist is None:
        pm.add_default_playlist()
        playlist = pm.get_playlist("Default")
    playlist.plugins.append(plugin_instance)
    return pm


# ---------------------------------------------------------------------------
# render_error_image unit tests
# ---------------------------------------------------------------------------


class TestRenderErrorImage:
    def test_returns_pil_image(self):
        img = render_error_image(
            width=800,
            height=480,
            plugin_id="weather",
            instance_name="my_weather",
            error_class="RuntimeError",
            error_message="API unavailable",
        )
        assert isinstance(img, Image.Image)

    def test_correct_dimensions(self):
        img = render_error_image(
            width=800,
            height=480,
            plugin_id="weather",
            instance_name="my_weather",
            error_class="RuntimeError",
            error_message="err",
        )
        assert img.size == (800, 480)

    def test_never_returns_none_on_long_message(self):
        msg = "x" * 500
        img = render_error_image(
            width=400,
            height=300,
            plugin_id="plugin",
            instance_name=None,
            error_class="ValueError",
            error_message=msg,
        )
        assert img is not None
        assert isinstance(img, Image.Image)

    def test_custom_timestamp(self):
        img = render_error_image(
            width=400,
            height=300,
            plugin_id="p",
            instance_name="i",
            error_class="TypeError",
            error_message="bad",
            timestamp="2025-01-01T00:00:00+00:00",
        )
        assert isinstance(img, Image.Image)

    def test_small_dimensions(self):
        """Even tiny dimensions should not raise."""
        img = render_error_image(
            width=50,
            height=50,
            plugin_id="p",
            instance_name=None,
            error_class="E",
            error_message="m",
        )
        assert isinstance(img, Image.Image)


# ---------------------------------------------------------------------------
# Fallback display integration (via _update_plugin_health → _cb_on_failure)
# ---------------------------------------------------------------------------


class TestFallbackImageOnFailure:
    def test_fallback_displayed_when_generate_raises(
        self, device_config_dev, monkeypatch
    ):
        """When generate_image raises, _push_fallback_image is called."""
        monkeypatch.setenv("INKYPI_PLUGIN_ISOLATION", "none")
        monkeypatch.setenv("INKYPI_PLUGIN_RETRY_MAX", "0")
        monkeypatch.setenv("PLUGIN_FAILURE_THRESHOLD", "5")

        task, dm = _make_task(device_config_dev)

        pi = _make_plugin_instance()
        _add_plugin_to_pm(device_config_dev, pi)

        dummy_cfg = {"id": "dummy", "class": "Dummy", "image_settings": []}
        monkeypatch.setattr(device_config_dev, "get_plugin", lambda pid: dummy_cfg)

        class AlwaysRaisesPlugin:
            def generate_image(self, settings, cfg):
                raise RuntimeError("API is down")

            def get_latest_metadata(self):
                return None

        monkeypatch.setattr(
            "refresh_task.task.get_plugin_instance",
            lambda cfg: AlwaysRaisesPlugin(),
        )

        from refresh_task.actions import PlaylistRefresh

        playlist = device_config_dev.get_playlist_manager().get_playlist("Default")
        refresh_action = PlaylistRefresh(playlist, pi)

        current_dt = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)

        fallback_calls = []
        original_push = task._push_fallback_image

        def _tracking_push(*args, **kwargs):
            fallback_calls.append(True)
            return original_push(*args, **kwargs)

        monkeypatch.setattr(task, "_push_fallback_image", _tracking_push)

        with pytest.raises(RuntimeError):
            task._perform_refresh(refresh_action, current_dt, current_dt)

        assert len(fallback_calls) == 1, "Fallback push should have been called once"

    def test_fallback_image_pushed_to_display(self, device_config_dev, monkeypatch):
        """display_manager.display_image is called with a PIL Image on failure."""
        monkeypatch.setenv("INKYPI_PLUGIN_ISOLATION", "none")
        monkeypatch.setenv("INKYPI_PLUGIN_RETRY_MAX", "0")
        monkeypatch.setenv("PLUGIN_FAILURE_THRESHOLD", "5")

        task, dm = _make_task(device_config_dev)

        pi = _make_plugin_instance()
        _add_plugin_to_pm(device_config_dev, pi)

        dummy_cfg = {"id": "dummy", "class": "Dummy", "image_settings": []}
        monkeypatch.setattr(device_config_dev, "get_plugin", lambda pid: dummy_cfg)

        class AlwaysRaisesPlugin:
            def generate_image(self, settings, cfg):
                raise ValueError("config missing")

            def get_latest_metadata(self):
                return None

        monkeypatch.setattr(
            "refresh_task.task.get_plugin_instance",
            lambda cfg: AlwaysRaisesPlugin(),
        )

        playlist = device_config_dev.get_playlist_manager().get_playlist("Default")
        refresh_action = PlaylistRefresh(playlist, pi)

        current_dt = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)

        with pytest.raises(ValueError):
            task._perform_refresh(refresh_action, current_dt, current_dt)

        # display_image should have been called at least once with a PIL Image
        assert dm.display_image.called
        call_args = dm.display_image.call_args
        first_arg = call_args[0][0] if call_args[0] else call_args[1].get("image")
        # Either positional or keyword — accept both
        if first_arg is None:
            first_arg = call_args[1].get("image") if call_args[1] else None
        assert isinstance(
            first_arg, Image.Image
        ), f"Expected PIL Image to be passed to display_image, got {type(first_arg)}"


# ---------------------------------------------------------------------------
# Circuit-breaker persistence to disk
# ---------------------------------------------------------------------------


class TestCircuitBreakerPersistence:
    def test_failure_counter_persisted_to_config(self, device_config_dev, monkeypatch):
        """Consecutive failures increment counter and write_config is called."""
        monkeypatch.setenv("PLUGIN_FAILURE_THRESHOLD", "5")
        task, _dm = _make_task(device_config_dev)
        pi = _make_plugin_instance()
        _add_plugin_to_pm(device_config_dev, pi)

        write_calls = []
        orig_write = device_config_dev.write_config

        def _tracking_write():
            write_calls.append(True)
            return orig_write()

        monkeypatch.setattr(device_config_dev, "write_config", _tracking_write)

        for _ in range(3):
            task._update_plugin_health(
                plugin_id="dummy",
                instance="my_dummy",
                ok=False,
                metrics=None,
                error="some error",
            )

        assert pi.consecutive_failure_count == 3
        assert len(write_calls) == 3, "write_config should be called per failure"

    def test_paused_after_five_failures_persists(self, device_config_dev, monkeypatch):
        """After 5 failures the instance is paused and state is written to disk."""
        monkeypatch.setenv("PLUGIN_FAILURE_THRESHOLD", "5")
        task, _dm = _make_task(device_config_dev)
        pi = _make_plugin_instance()
        _add_plugin_to_pm(device_config_dev, pi)

        for _ in range(5):
            task._update_plugin_health(
                plugin_id="dummy",
                instance="my_dummy",
                ok=False,
                metrics=None,
                error="boom",
            )

        assert pi.paused is True
        assert pi.consecutive_failure_count == 5
        assert pi.disabled_reason is not None
        assert "boom" in pi.disabled_reason

        # Reload config from disk to verify persistence
        import json

        with open(device_config_dev.config_file, encoding="utf-8") as f:
            saved = json.load(f)

        playlists = saved.get("playlist_config", {}).get("playlists", [])
        found_plugin = None
        for pl in playlists:
            for p in pl.get("plugins", []):
                if p.get("plugin_id") == "dummy" and p.get("name") == "my_dummy":
                    found_plugin = p
                    break

        assert found_plugin is not None, "Plugin should be persisted in config"
        assert found_plugin["paused"] is True
        assert found_plugin["consecutive_failure_count"] == 5

    def test_success_resets_counter_and_persists(self, device_config_dev, monkeypatch):
        """Success after failures resets counter to 0 and writes config once."""
        monkeypatch.setenv("PLUGIN_FAILURE_THRESHOLD", "5")
        task, _dm = _make_task(device_config_dev)
        pi = _make_plugin_instance()
        _add_plugin_to_pm(device_config_dev, pi)

        # Simulate 3 prior failures
        for _ in range(3):
            task._update_plugin_health(
                plugin_id="dummy",
                instance="my_dummy",
                ok=False,
                metrics=None,
                error="err",
            )
        assert pi.consecutive_failure_count == 3

        write_calls = []
        orig_write = device_config_dev.write_config

        def _tracking_write():
            write_calls.append(True)
            return orig_write()

        monkeypatch.setattr(device_config_dev, "write_config", _tracking_write)

        # Now a success
        task._update_plugin_health(
            plugin_id="dummy",
            instance="my_dummy",
            ok=True,
            metrics={"request_ms": 100},
            error=None,
        )

        assert pi.consecutive_failure_count == 0
        assert pi.paused is False
        assert pi.disabled_reason is None
        assert (
            len(write_calls) == 1
        ), "write_config should be called exactly once on recovery"

    def test_disabled_reason_cleared_on_success(self, device_config_dev, monkeypatch):
        """disabled_reason is removed after successful refresh."""
        monkeypatch.setenv("PLUGIN_FAILURE_THRESHOLD", "2")
        task, _dm = _make_task(device_config_dev)
        pi = _make_plugin_instance()
        _add_plugin_to_pm(device_config_dev, pi)

        for _ in range(2):
            task._update_plugin_health(
                plugin_id="dummy",
                instance="my_dummy",
                ok=False,
                metrics=None,
                error="test error",
            )
        assert pi.paused is True
        assert pi.disabled_reason is not None

        task._update_plugin_health(
            plugin_id="dummy",
            instance="my_dummy",
            ok=True,
            metrics=None,
            error=None,
        )
        assert pi.disabled_reason is None

    def test_disabled_reason_in_to_dict(self):
        pi = PluginInstance("p", "n", {}, {"interval": 3600})
        pi.paused = True
        pi.disabled_reason = "Paused after 5 consecutive failures"
        d = pi.to_dict()
        assert d["disabled_reason"] == "Paused after 5 consecutive failures"

    def test_disabled_reason_round_trips_from_dict(self):
        data = {
            "plugin_id": "weather",
            "name": "inst",
            "plugin_settings": {},
            "refresh": {"interval": 3600},
            "paused": True,
            "disabled_reason": "too many errors",
            "consecutive_failure_count": 5,
        }
        pi = PluginInstance.from_dict(data)
        assert pi.disabled_reason == "too many errors"

    def test_disabled_reason_absent_from_dict_defaults_none(self):
        data = {
            "plugin_id": "weather",
            "name": "inst",
            "plugin_settings": {},
            "refresh": {"interval": 3600},
        }
        pi = PluginInstance.from_dict(data)
        assert pi.disabled_reason is None

    def test_disabled_reason_not_in_to_dict_when_none(self):
        pi = PluginInstance("p", "n", {}, {"interval": 3600})
        d = pi.to_dict()
        assert "disabled_reason" not in d
