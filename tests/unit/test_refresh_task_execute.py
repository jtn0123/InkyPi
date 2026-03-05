from PIL import Image


def _dummy_plugin(device_config):
    class DummyPlugin:
        config = {"image_settings": []}

        def generate_image(self, settings, cfg):
            return Image.new("RGB", cfg.get_resolution(), "white")

    return DummyPlugin()


def test_manual_refresh_uses_execute(device_config_dev, monkeypatch, tmp_path):
    """Ensure ManualRefresh is executed via the unified execute method."""
    from display.display_manager import DisplayManager
    from refresh_task import ManualRefresh, RefreshTask

    dm = DisplayManager(device_config_dev)
    task = RefreshTask(device_config_dev, dm)

    # Stub plugin retrieval
    dummy_cfg = {"id": "dummy", "class": "Dummy"}
    monkeypatch.setattr(device_config_dev, "get_plugin", lambda pid: dummy_cfg)
    monkeypatch.setattr(
        "refresh_task.get_plugin_instance",
        lambda cfg: _dummy_plugin(device_config_dev),
        raising=True,
    )

    refresh = ManualRefresh("dummy", {})
    marker = tmp_path / "manual-execute.txt"

    def fake_execute(self, plugin, device_config, current_dt):
        marker.write_text("called", encoding="utf-8")
        return Image.new("RGB", device_config.get_resolution(), "white")

    monkeypatch.setattr(refresh, "execute", fake_execute.__get__(refresh, ManualRefresh))

    try:
        task.start()
        task.manual_update(refresh)
        assert marker.read_text(encoding="utf-8") == "called"
    finally:
        task.stop()


def test_playlist_refresh_uses_execute(device_config_dev, monkeypatch, tmp_path):
    """Ensure PlaylistRefresh is executed via the unified execute method."""
    from display.display_manager import DisplayManager
    from refresh_task import PlaylistRefresh, RefreshTask

    dm = DisplayManager(device_config_dev)
    task = RefreshTask(device_config_dev, dm)

    # Avoid waiting during the loop
    monkeypatch.setattr(task.condition, "wait", lambda timeout=None: None)

    # Stub plugin config and instance
    dummy_cfg = {"id": "dummy", "class": "Dummy"}
    monkeypatch.setattr(device_config_dev, "get_plugin", lambda pid: dummy_cfg)
    monkeypatch.setattr(
        "refresh_task.get_plugin_instance",
        lambda cfg: _dummy_plugin(device_config_dev),
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

    fake_plugin_instance = FakePluginInstance()
    fake_playlist = type("PL", (), {"name": "pl"})()

    def fake_determine(self, pm, latest_refresh, current_dt):
        if not getattr(self, "_done", False):
            self._done = True
            return fake_playlist, fake_plugin_instance
        return None, None

    monkeypatch.setattr(task, "_determine_next_plugin", fake_determine.__get__(task, RefreshTask))

    marker = tmp_path / "playlist-execute.txt"

    def fake_execute(self, plugin, device_config, current_dt):
        marker.write_text("called", encoding="utf-8")
        return Image.new("RGB", device_config.get_resolution(), "white")

    monkeypatch.setattr(PlaylistRefresh, "execute", fake_execute, raising=True)

    try:
        task.start()
        for _ in range(20):
            if marker.exists():
                break
            import time

            time.sleep(0.05)
        assert marker.read_text(encoding="utf-8") == "called"
    finally:
        task.stop()
