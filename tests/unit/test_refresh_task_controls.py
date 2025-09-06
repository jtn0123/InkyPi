# pyright: reportMissingImports=false
from PIL import Image


def test_signal_config_change_noop_when_not_running(device_config_dev, monkeypatch):
    from refresh_task import RefreshTask
    from display.display_manager import DisplayManager
    dm = DisplayManager(device_config_dev)
    task = RefreshTask(device_config_dev, dm)
    # Not running -> should not error
    task.signal_config_change()


def test_manual_update_raises_exception_from_thread(device_config_dev, monkeypatch):
    from refresh_task import RefreshTask, ManualRefresh
    from display.display_manager import DisplayManager
    dm = DisplayManager(device_config_dev)
    task = RefreshTask(device_config_dev, dm)

    # Start the task with a stub _run that immediately processes and raises
    def fake_run():
        with task.condition:
            task.refresh_result = {"exception": RuntimeError("boom")}
        task.refresh_event.set()
        task.running = False

    monkeypatch.setattr(task, '_run', fake_run, raising=True)
    task.start()

    try:
        try:
            task.manual_update(ManualRefresh('ai_text', {}))
            assert False, "Expected exception to propagate"
        except RuntimeError as e:
            assert "boom" in str(e)
    finally:
        task.stop()

