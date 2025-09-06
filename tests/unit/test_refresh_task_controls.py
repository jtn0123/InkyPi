# pyright: reportMissingImports=false


def test_signal_config_change_noop_when_not_running(device_config_dev, monkeypatch):
    from display.display_manager import DisplayManager
    from refresh_task import RefreshTask
    dm = DisplayManager(device_config_dev)
    task = RefreshTask(device_config_dev, dm)
    # Not running -> should not error
    task.signal_config_change()


def test_manual_update_raises_exception_from_thread(device_config_dev, monkeypatch):
    from display.display_manager import DisplayManager
    from refresh_task import ManualRefresh, RefreshTask
    dm = DisplayManager(device_config_dev)
    task = RefreshTask(device_config_dev, dm)

    # Start the task with a stub _run that immediately processes and raises
    def fake_run():
        with task.condition:
            # simulate thread started and waiting
            pass
        # emulate a manual_update being processed and failing
        task.refresh_result = {"exception": RuntimeError("boom")}
        task.refresh_event.set()
        task.running = False

    monkeypatch.setattr(task, '_run', fake_run, raising=True)
    task.start()

    try:
        task.manual_update(ManualRefresh('ai_text', {}))
    finally:
        task.stop()

