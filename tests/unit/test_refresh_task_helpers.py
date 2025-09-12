from PIL import Image


def _dummy_plugin(device_config):
    class DummyPlugin:
        config = {"image_settings": []}

        def generate_image(self, settings, cfg):
            return Image.new("RGB", cfg.get_resolution(), "white")

        def get_latest_metadata(self):
            return {"meta": 1}

    return DummyPlugin()


def test_wait_for_trigger_returns_manual_refresh(device_config_dev, monkeypatch):
    from display.display_manager import DisplayManager
    from refresh_task import ManualRefresh, RefreshTask

    dm = DisplayManager(device_config_dev)
    task = RefreshTask(device_config_dev, dm)
    task.running = True
    monkeypatch.setattr(task.condition, "wait", lambda timeout=None: None)

    manual = ManualRefresh("dummy", {})
    task.manual_update_request = manual
    pm, latest, dt, action = task._wait_for_trigger()
    assert action is manual
    assert task.manual_update_request is None


def test_select_refresh_action_playlist(device_config_dev, monkeypatch):
    from display.display_manager import DisplayManager
    from refresh_task import PlaylistRefresh, RefreshTask

    dm = DisplayManager(device_config_dev)
    task = RefreshTask(device_config_dev, dm)

    class FakePlaylist:
        name = "pl"

    class FakePlugin:
        plugin_id = "dummy"
        name = "inst"
        settings = {}

        def get_image_path(self):
            return "dummy.png"

        def should_refresh(self, dt):
            return True

    fake_playlist = FakePlaylist()
    fake_plugin = FakePlugin()

    def fake_determine(self, pm, latest, current_dt):
        return fake_playlist, fake_plugin

    monkeypatch.setattr(task, "_determine_next_plugin", fake_determine.__get__(task, RefreshTask))
    action = task._select_refresh_action(None, None, task._get_current_datetime(), None)
    assert isinstance(action, PlaylistRefresh)
    assert action.playlist is fake_playlist
    assert action.plugin_instance is fake_plugin


def test_select_refresh_action_manual(device_config_dev):
    from display.display_manager import DisplayManager
    from refresh_task import ManualRefresh, RefreshTask

    dm = DisplayManager(device_config_dev)
    task = RefreshTask(device_config_dev, dm)
    manual = ManualRefresh("dummy", {})
    action = task._select_refresh_action(None, None, task._get_current_datetime(), manual)
    assert action is manual


def test_perform_refresh_skips_when_cached(device_config_dev, monkeypatch):
    from display.display_manager import DisplayManager
    from refresh_task import ManualRefresh, RefreshTask
    from model import RefreshInfo

    dm = DisplayManager(device_config_dev)
    task = RefreshTask(device_config_dev, dm)

    dummy_cfg = {"id": "dummy", "class": "Dummy"}
    monkeypatch.setattr(device_config_dev, "get_plugin", lambda pid: dummy_cfg)
    monkeypatch.setattr(
        "refresh_task.get_plugin_instance",
        lambda cfg: _dummy_plugin(device_config_dev),
        raising=True,
    )
    monkeypatch.setattr(
        "refresh_task.compute_image_hash", lambda img: "same", raising=True
    )

    called = {"val": False}
    monkeypatch.setattr(
        dm, "display_image", lambda *a, **k: called.__setitem__("val", True)
    )

    latest = RefreshInfo("Manual Update", "dummy", "2020-01-01T00:00:00", "same")
    action = ManualRefresh("dummy", {})
    info, used_cached, metrics = task._perform_refresh(
        action, latest, task._get_current_datetime()
    )
    assert used_cached is True
    assert not called["val"]
    assert info["image_hash"] == "same"


def test_update_refresh_info_persists(device_config_dev, monkeypatch):
    from display.display_manager import DisplayManager
    from refresh_task import RefreshTask

    dm = DisplayManager(device_config_dev)
    task = RefreshTask(device_config_dev, dm)

    called = {"val": False}
    monkeypatch.setattr(
        device_config_dev, "write_config", lambda: called.__setitem__("val", True)
    )

    refresh_info = {
        "refresh_type": "Manual Update",
        "plugin_id": "dummy",
        "refresh_time": "2020-01-01T00:00:00",
        "image_hash": "abc",
    }
    metrics = {"request_ms": 1, "display_ms": 2, "generate_ms": 3, "preprocess_ms": 4}
    task._update_refresh_info(refresh_info, metrics, used_cached=False)
    ri = device_config_dev.refresh_info
    assert ri.image_hash == "abc"
    assert ri.used_cached is False
    assert called["val"]
