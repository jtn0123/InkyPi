# pyright: reportMissingImports=false
"""Integration tests for the full refresh cycle (JTN-291).

These tests exercise the path from playlist resolution through plugin
image generation to the mock display, calling the synchronous entry
points directly so no sleep() or thread-timing hacks are needed.
"""

from datetime import UTC, datetime

import pytest
from PIL import Image

from display.display_manager import DisplayManager
from model import Playlist, PlaylistManager, PluginInstance
from refresh_task import PlaylistRefresh, RefreshTask

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_plugin_instance(plugin_id, name, refresh_interval=0):
    """Create a PluginInstance that is always due for a refresh."""
    return PluginInstance(
        plugin_id=plugin_id,
        name=name,
        settings={},
        refresh={"interval": refresh_interval},
        latest_refresh_time=None,
    )


def _make_playlist_with_plugins(*plugin_instances):
    """Create an always-active playlist containing the given plugin instances.

    Playlist.__init__ calls PluginInstance.from_dict on whatever is in the
    plugins list, so we construct the playlist with an empty list and then
    inject the PluginInstance objects directly.
    """
    pl = Playlist(
        name="Test Playlist",
        start_time="00:00",
        end_time="24:00",
        plugins=[],
    )
    pl.plugins = list(plugin_instances)
    return pl


def _fake_image(width=800, height=480):
    """Return a small solid-colour PIL image for use as a plugin output stub."""
    return Image.new("RGB", (width, height), "white")


# ---------------------------------------------------------------------------
# Test 1 — happy-path: plugin renders an image that reaches the display
# ---------------------------------------------------------------------------


def test_refresh_cycle_runs_plugin_to_display(device_config_dev, monkeypatch):
    """Full cycle: playlist → year_progress plugin → mock display receives image.

    The display is real (MockDisplay backed by tmp_path) but the plugin's
    rendering step is stubbed at the screenshot level (conftest autouse fixture
    already patches take_screenshot_html).  We additionally spy on
    DisplayManager.display_image to capture the image passed to it.
    """
    # Register year_progress plugin in the device config's plugin registry
    year_progress_cfg = {"id": "year_progress", "class": "YearProgress"}
    monkeypatch.setattr(
        device_config_dev,
        "get_plugin",
        lambda pid: year_progress_cfg if pid == "year_progress" else None,
    )

    # Build the playlist manager with one year_progress instance
    pi = _make_plugin_instance("year_progress", "my_year_progress")
    playlist = _make_playlist_with_plugins(pi)
    pm = PlaylistManager(playlists=[playlist], active_playlist="Test Playlist")
    monkeypatch.setattr(device_config_dev, "get_playlist_manager", lambda: pm)

    # Load year_progress into the plugin registry so get_plugin_instance can find it
    from plugins.plugin_registry import load_plugins

    load_plugins([year_progress_cfg])

    dm = DisplayManager(device_config_dev)
    task = RefreshTask(device_config_dev, dm)

    received_images: list[Image.Image] = []
    real_display_image = dm.display.display_image

    def _spy_display_image(image, image_settings=None):
        received_images.append(image.copy())
        return real_display_image(image, image_settings=image_settings)

    monkeypatch.setattr(dm.display, "display_image", _spy_display_image)

    refresh_action = PlaylistRefresh(playlist, pi, force=True)

    current_dt = datetime.now(UTC).astimezone()

    # Trigger one synchronous refresh tick (no thread needed)
    refresh_info, used_cached, metrics = task._perform_refresh(
        refresh_action,
        device_config_dev.get_refresh_info(),
        current_dt,
    )

    # The mock display must have received exactly one image
    assert len(received_images) == 1, "Expected display_image to be called once"

    img = received_images[0]
    expected_w, expected_h = device_config_dev.get_resolution()
    assert img.size == (
        expected_w,
        expected_h,
    ), f"Display received wrong dimensions: {img.size}"

    # Plugin health must show a successful run
    assert "year_progress" in task.plugin_health
    assert task.plugin_health["year_progress"]["status"] == "green"
    assert task.plugin_health["year_progress"]["failure_count"] == 0

    # refresh_info must be populated
    assert refresh_info is not None
    assert refresh_info.get("plugin_id") == "year_progress"
    assert refresh_info.get("image_hash") is not None

    # Timing metrics must be present
    assert metrics.get("request_ms") is not None


# ---------------------------------------------------------------------------
# Test 2 — failure path: broken plugin, display must NOT be called
# ---------------------------------------------------------------------------


def test_refresh_cycle_handles_plugin_failure(device_config_dev, monkeypatch):
    """When the plugin raises, the display is skipped and health records the error."""
    failing_cfg = {"id": "bad_plugin", "class": "BadPlugin"}
    monkeypatch.setattr(
        device_config_dev,
        "get_plugin",
        lambda pid: failing_cfg if pid == "bad_plugin" else None,
    )

    pi = _make_plugin_instance("bad_plugin", "bad_inst")
    playlist = _make_playlist_with_plugins(pi)
    pm = PlaylistManager(playlists=[playlist], active_playlist="Test Playlist")
    monkeypatch.setattr(device_config_dev, "get_playlist_manager", lambda: pm)

    dm = DisplayManager(device_config_dev)
    task = RefreshTask(device_config_dev, dm)

    display_calls: list = []
    monkeypatch.setattr(
        dm.display, "display_image", lambda *a, **kw: display_calls.append(a)
    )

    # Stub the plugin to raise unconditionally
    def _boom(*args, **kwargs):
        raise RuntimeError("Simulated plugin crash")

    monkeypatch.setattr(
        "refresh_task.task.get_plugin_instance",
        lambda cfg: type(
            "BadPlugin",
            (),
            {"generate_image": staticmethod(_boom)},
        )(),
        raising=True,
    )

    refresh_action = PlaylistRefresh(playlist, pi, force=True)
    current_dt = datetime.now(UTC).astimezone()

    with pytest.raises(RuntimeError, match="Simulated plugin crash"):
        task._perform_refresh(
            refresh_action,
            device_config_dev.get_refresh_info(),
            current_dt,
        )

    # Display must NOT have been called
    assert display_calls == [], "Display should not be called when plugin fails"

    # Plugin health must record the failure
    assert "bad_plugin" in task.plugin_health
    health = task.plugin_health["bad_plugin"]
    assert health["status"] == "red"
    assert health["failure_count"] >= 1
    assert "Simulated plugin crash" in (health.get("last_error") or "")


# ---------------------------------------------------------------------------
# Test 3 — playlist advances: two plugins rendered in sequence
# ---------------------------------------------------------------------------


def test_refresh_cycle_advances_playlist(device_config_dev, monkeypatch):
    """With two plugins in the playlist each refresh tick renders the next one."""
    call_log: list[str] = []

    def _make_fake_plugin(plugin_id):
        """Return a plugin object whose generate_image records the plugin_id."""

        class FakePlugin:
            def generate_image(self, settings, cfg):
                call_log.append(plugin_id)
                return _fake_image(*cfg.get_resolution())

        return FakePlugin()

    # Two separate plugin ids so we can distinguish them
    pi_a = _make_plugin_instance("plugin_a", "inst_a")
    pi_b = _make_plugin_instance("plugin_b", "inst_b")
    playlist = _make_playlist_with_plugins(pi_a, pi_b)
    pm = PlaylistManager(playlists=[playlist], active_playlist="Test Playlist")
    monkeypatch.setattr(device_config_dev, "get_playlist_manager", lambda: pm)

    def _fake_get_plugin(pid):
        if pid in ("plugin_a", "plugin_b"):
            return {"id": pid, "class": pid.title().replace("_", "")}
        return None

    monkeypatch.setattr(device_config_dev, "get_plugin", _fake_get_plugin)

    # Route get_plugin_instance to our fake plugin factory
    monkeypatch.setattr(
        "refresh_task.task.get_plugin_instance",
        lambda cfg: _make_fake_plugin(cfg["id"]),
        raising=True,
    )

    dm = DisplayManager(device_config_dev)
    # Silence the display writes — we only care about plugin call order
    monkeypatch.setattr(dm.display, "display_image", lambda *a, **kw: None)

    task = RefreshTask(device_config_dev, dm)
    current_dt = datetime.now(UTC).astimezone()
    latest_refresh = device_config_dev.get_refresh_info()

    # First tick — should render plugin_a (first in playlist)
    refresh_a = PlaylistRefresh(playlist, pi_a, force=True)
    task._perform_refresh(refresh_a, latest_refresh, current_dt)

    # Second tick — should render plugin_b (second in playlist)
    refresh_b = PlaylistRefresh(playlist, pi_b, force=True)
    task._perform_refresh(refresh_b, latest_refresh, current_dt)

    assert call_log == [
        "plugin_a",
        "plugin_b",
    ], f"Expected plugin_a then plugin_b, got: {call_log}"

    # Both plugins must appear in health with green status
    assert task.plugin_health.get("plugin_a", {}).get("status") == "green"
    assert task.plugin_health.get("plugin_b", {}).get("status") == "green"

    # latest_refresh_time on each instance must be updated after a refresh
    assert pi_a.latest_refresh_time is not None, "pi_a should have a refresh timestamp"
    assert pi_b.latest_refresh_time is not None, "pi_b should have a refresh timestamp"
