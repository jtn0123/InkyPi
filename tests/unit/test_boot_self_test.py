# pyright: reportMissingImports=false
"""Tests for the once-per-version boot self-test (B9)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from utils import blackout, boot_self_test


@pytest.fixture(autouse=True)
def _state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    state = tmp_path / "state"
    monkeypatch.delenv("INKYPI_LOCKFILE_DIR", raising=False)
    monkeypatch.setenv("INKYPI_STATE_DIR", str(state))
    monkeypatch.delenv(boot_self_test.SKIP_ENV, raising=False)
    return state


class _Driver:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.images: list[Image.Image] = []

    def display_image(self, image: Image.Image, image_settings: Any = None) -> None:
        if self.fail:
            raise OSError("SPI bus not found")
        self.images.append(image)


def _real_display(device_config: Any, driver: _Driver) -> Any:
    """A DisplayManager on the mock config, with a recording driver."""
    from display.display_manager import DisplayManager

    dm = DisplayManager(device_config)
    dm.display = driver
    return dm


def _task(device_config: Any, dm: Any) -> Any:
    from refresh_task import RefreshTask

    return RefreshTask(device_config, dm)


def test_pattern_matches_panel_resolution() -> None:
    image = boot_self_test.make_test_pattern(800, 480, "1.2.3")
    assert image.size == (800, 480)
    # First bar is black, label strip is white.
    assert image.getpixel((5, 5)) == (0, 0, 0)
    assert image.getpixel((5, 479)) == (255, 255, 255)


def test_due_when_never_run_and_after_version_change() -> None:
    assert boot_self_test.is_due("1.0.0") is True
    boot_self_test._record("1.0.0", "pass")
    assert boot_self_test.is_due("1.0.0") is False
    assert boot_self_test.is_due("1.0.1") is True


def test_skip_reasons(device_config_dev: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    # The shared fixture uses the mock display, which has no panel to test.
    assert boot_self_test.skip_reason(device_config_dev) == "mock display"

    device_config_dev.update_value("display_type", "inky")
    assert boot_self_test.skip_reason(device_config_dev) is None

    device_config_dev.update_value("boot_self_test", False)
    assert "device config" in (boot_self_test.skip_reason(device_config_dev) or "")

    device_config_dev.update_value("boot_self_test", True)
    monkeypatch.setenv(boot_self_test.SKIP_ENV, "1")
    assert boot_self_test.SKIP_ENV in (
        boot_self_test.skip_reason(device_config_dev) or ""
    )


def test_run_records_pass_and_restores_previous_frame(device_config_dev: Any) -> None:
    previous = Image.new("RGB", (800, 480), "blue")
    previous.save(device_config_dev.processed_image_file)
    driver = _Driver()
    dm = _real_display(device_config_dev, driver)
    task = _task(device_config_dev, dm)

    task.start()
    try:
        record = boot_self_test.run(task, device_config_dev, "2.0.0", hold_seconds=0)
    finally:
        task.stop()

    assert record["status"] == "pass"
    assert record["version"] == "2.0.0"
    assert record["error"] is None
    assert record["display_driver"] == "_Driver"
    assert len(driver.images) == 2  # pattern, then the restored frame
    assert driver.images[0].getpixel((5, 5)) == (0, 0, 0)
    assert driver.images[1].getpixel((5, 5)) == (0, 0, 255)
    assert boot_self_test.last_result() == record
    assert boot_self_test.is_due("2.0.0") is False


def test_run_records_fail_when_driver_raises(device_config_dev: Any) -> None:
    dm = _real_display(device_config_dev, _Driver(fail=True))
    task = _task(device_config_dev, dm)

    task.start()
    try:
        record = boot_self_test.run(task, device_config_dev, "2.0.0", hold_seconds=0)
    finally:
        task.stop()

    assert record["status"] == "fail"
    assert "SPI bus not found" in record["error"]
    # A failure is still recorded against this version, so it is not retried
    # every boot; diagnostics shows the failure instead.
    assert boot_self_test.is_due("2.0.0") is False


def test_run_without_restore_leaves_pattern(device_config_dev: Any) -> None:
    Image.new("RGB", (800, 480), "blue").save(device_config_dev.processed_image_file)
    driver = _Driver()
    task = _task(device_config_dev, _real_display(device_config_dev, driver))
    # Not started: web-only mode runs the command inline.
    record = boot_self_test.run(
        task, device_config_dev, "2.0.0", restore=False, hold_seconds=0
    )
    assert record["status"] == "pass"
    assert len(driver.images) == 1


def test_maybe_run_skips_and_defers(device_config_dev: Any) -> None:
    driver = _Driver()
    task = _task(device_config_dev, _real_display(device_config_dev, driver))

    # Mock display: skipped, nothing recorded.
    assert boot_self_test.maybe_run(task, device_config_dev, "3.0.0") is None
    assert boot_self_test.last_result() is None

    device_config_dev.update_value("display_type", "inky")
    blackout.set_active(device_config_dev, True)
    # Blackout defers without recording, so it runs after the blackout ends.
    assert boot_self_test.maybe_run(task, device_config_dev, "3.0.0") is None
    assert boot_self_test.last_result() is None
    assert driver.images == []


def test_maybe_run_runs_once_per_version(
    device_config_dev: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(boot_self_test, "_DEFAULT_HOLD_SECONDS", 0)
    driver = _Driver()
    task = _task(device_config_dev, _real_display(device_config_dev, driver))
    # After building the manager: the real Inky driver is not installed here.
    device_config_dev.update_value("display_type", "inky")

    first = boot_self_test.maybe_run(task, device_config_dev, "3.0.0", restore=False)
    assert first is not None and first["status"] == "pass"
    assert boot_self_test.maybe_run(task, device_config_dev, "3.0.0") is None
    assert len(driver.images) == 1

    again = boot_self_test.maybe_run(task, device_config_dev, "3.0.1", restore=False)
    assert again is not None and again["version"] == "3.0.1"
    assert len(driver.images) == 2


def test_run_boot_display_tasks_runs_self_test_then_startup_image(
    flask_app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import inkypi

    calls: list[str] = []
    device_config = flask_app.config["DEVICE_CONFIG"]
    device_config.update_value("startup", True)

    def _fake_maybe_run(*_a: Any, restore: bool, **_k: Any) -> None:
        calls.append(f"self_test(restore={restore})")

    monkeypatch.setattr(boot_self_test, "maybe_run", _fake_maybe_run)
    dm = flask_app.config["DISPLAY_MANAGER"]
    monkeypatch.setattr(dm, "display_image", lambda img: calls.append("startup"))

    inkypi.run_boot_display_tasks(flask_app)

    assert calls == ["self_test(restore=False)", "startup"]
    assert device_config.get_config("startup") is False


def test_run_boot_display_tasks_skips_everything_in_blackout(
    flask_app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import inkypi

    calls: list[str] = []
    device_config = flask_app.config["DEVICE_CONFIG"]
    device_config.update_value("startup", True)
    blackout.set_active(device_config, True)
    monkeypatch.setattr(
        boot_self_test, "maybe_run", lambda *a, **k: calls.append("self_test")
    )
    dm = flask_app.config["DISPLAY_MANAGER"]
    monkeypatch.setattr(dm, "display_image", lambda img: calls.append("startup"))

    inkypi.run_boot_display_tasks(flask_app)

    assert calls == []
    assert device_config.get_config("startup") is True
