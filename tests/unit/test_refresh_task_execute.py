from PIL import Image


def _dummy_plugin(device_config, marker=None):
    class DummyPlugin:
        config = {"image_settings": []}

        def generate_image(self, settings, cfg):
            if marker is not None:
                marker.write_text("called", encoding="utf-8")
            return Image.new("RGB", cfg.get_resolution(), "white")

    return DummyPlugin()


def test_manual_refresh_uses_execute(device_config_dev, monkeypatch, tmp_path):
    """Ensure ManualRefresh exercises the plugin generate_image path."""
    from display.display_manager import DisplayManager
    from refresh_task import ManualRefresh, RefreshTask

    dm = DisplayManager(device_config_dev)
    task = RefreshTask(device_config_dev, dm)

    marker = tmp_path / "manual-execute.txt"

    dummy_cfg = {"id": "dummy", "class": "Dummy"}
    monkeypatch.setattr(device_config_dev, "get_plugin", lambda pid: dummy_cfg)
    monkeypatch.setattr(
        "refresh_task.get_plugin_instance",
        lambda cfg: _dummy_plugin(device_config_dev, marker),
        raising=True,
    )

    try:
        task.start()
        task.manual_update(ManualRefresh("dummy", {}))
        assert marker.read_text(encoding="utf-8") == "called"
    finally:
        task.stop()


def test_playlist_refresh_uses_execute(device_config_dev, monkeypatch, tmp_path):
    """Ensure PlaylistRefresh exercises the plugin generate_image path.

    Uses manual_update with a PlaylistRefresh to avoid timing issues
    with the background refresh loop.
    """
    from display.display_manager import DisplayManager
    from refresh_task import PlaylistRefresh, RefreshTask

    dm = DisplayManager(device_config_dev)
    task = RefreshTask(device_config_dev, dm)

    marker = tmp_path / "playlist-execute.txt"

    dummy_cfg = {"id": "dummy", "class": "Dummy"}
    monkeypatch.setattr(device_config_dev, "get_plugin", lambda pid: dummy_cfg)
    monkeypatch.setattr(
        "refresh_task.get_plugin_instance",
        lambda cfg: _dummy_plugin(device_config_dev, marker),
        raising=True,
    )

    class FakePluginInstance:
        plugin_id = "dummy"
        name = "inst"
        settings = {}

        def get_image_path(self):
            return "dummy.png"

        def should_refresh(self, dt):
            return True

    fake_instance = FakePluginInstance()
    fake_playlist = type("PL", (), {"name": "pl"})()

    refresh = PlaylistRefresh(fake_playlist, fake_instance)

    try:
        task.start()
        task.manual_update(refresh)
        assert marker.exists(), "generate_image should have been called"
        assert marker.read_text(encoding="utf-8") == "called"
    finally:
        task.stop()
