import time


def test_refresh_task_signal_and_stop(monkeypatch, device_config_dev):
    from refresh_task import RefreshTask
    from display.display_manager import DisplayManager

    dm = DisplayManager(device_config_dev)
    rt = RefreshTask(device_config_dev, dm)

    # Speed up loop for tests
    device_config_dev.update_value("plugin_cycle_interval_seconds", 1)

    rt.start()
    assert rt.running is True
    # Signal config change and ensure it does not crash
    rt.signal_config_change()
    time.sleep(0.1)
    rt.stop()
    assert rt.running is False


def test_refresh_task_plugin_exception_isolated(monkeypatch, device_config_dev):
    from refresh_task import RefreshTask
    from display.display_manager import DisplayManager
    import plugins.ai_text.ai_text as ai_text_mod

    dm = DisplayManager(device_config_dev)
    rt = RefreshTask(device_config_dev, dm)

    # Make AIText raise to simulate plugin failure during cycle
    def boom(settings, cfg):
        raise RuntimeError("cycle failure")

    monkeypatch.setattr(ai_text_mod.AIText, "generate_image", staticmethod(boom), raising=True)

    # Trigger a manual update path when not running to exercise isolation logic
    from refresh_task import ManualRefresh

    metrics = rt.manual_update(ManualRefresh("ai_text", {"text": "x"}))
    # When not running, manual_update returns any captured metrics (possibly None)
    # The primary assertion is that no exception propagates
    assert metrics is None or isinstance(metrics, dict)

