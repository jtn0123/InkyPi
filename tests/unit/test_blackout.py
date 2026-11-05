# pyright: reportMissingImports=false
"""Tests for the blackout / kill switch (B12)."""

from __future__ import annotations

import importlib
from typing import Any

import pytest
from flask import Flask
from PIL import Image

from utils import blackout

#: What a browser sends for a bookmark / typed URL.
_BOOKMARK = {"Sec-Fetch-Site": "none"}


class _Driver:
    def __init__(self) -> None:
        self.images: list[Image.Image] = []

    def display_image(self, image: Image.Image, image_settings: Any = None) -> None:
        self.images.append(image)


@pytest.fixture()
def driver(flask_app: Flask) -> _Driver:
    recording = _Driver()
    flask_app.config["DISPLAY_MANAGER"].display = recording
    return recording


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


def test_state_defaults_off_and_persists(device_config_dev: Any) -> None:
    assert blackout.get_state(device_config_dev) == {"active": False, "since": None}

    blackout.set_active(device_config_dev, True)

    from config import Config

    reloaded = Config()  # a restart reads the file again
    state = blackout.get_state(reloaded)
    assert state["active"] is True
    assert isinstance(state["since"], str)


def test_corrupt_state_reads_as_off(device_config_dev: Any) -> None:
    device_config_dev.update_value("blackout", "yes please")
    assert blackout.is_active(device_config_dev) is False
    device_config_dev.update_value("blackout", {"active": "true"})
    assert blackout.is_active(device_config_dev) is False


def test_blank_image_is_white_at_panel_resolution(device_config_dev: Any) -> None:
    image = blackout.blank_image(device_config_dev)
    assert image.size == (800, 480)
    assert image.getextrema() == ((255, 255), (255, 255), (255, 255))


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


def test_bookmark_get_turns_blackout_on_and_blanks(
    client: Any, flask_app: Flask, driver: _Driver
) -> None:
    resp = client.get("/api/blackout", headers=_BOOKMARK)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["success"] is True
    assert body["active"] is True
    assert body["changed"] is True
    # Refresh task not started in tests, so the blank frame is pushed inline.
    assert body["display"] == "done"
    assert len(driver.images) == 1
    assert driver.images[0].getextrema()[0] == (255, 255)
    assert blackout.is_active(flask_app.config["DEVICE_CONFIG"])


def test_repeat_activation_does_not_repush(client: Any, driver: _Driver) -> None:
    client.get("/api/blackout", headers=_BOOKMARK)
    body = client.get("/api/blackout", headers=_BOOKMARK).get_json()
    assert body["changed"] is False
    assert body["display"] == "unchanged"
    assert len(driver.images) == 1


def test_off_param_and_delete_resume_and_restore_last_frame(
    client: Any, flask_app: Flask, driver: _Driver
) -> None:
    device_config = flask_app.config["DEVICE_CONFIG"]
    Image.new("RGB", (800, 480), "red").save(device_config.processed_image_file)

    client.post("/api/blackout")
    body = client.get("/api/blackout?off=1", headers=_BOOKMARK).get_json()
    assert body["active"] is False
    assert body["changed"] is True
    assert driver.images[-1].getpixel((0, 0)) == (255, 0, 0)

    client.post("/api/blackout")
    resp = client.delete("/api/blackout")
    assert resp.status_code == 200
    assert resp.get_json()["active"] is False
    assert not blackout.is_active(device_config)


def test_browser_navigation_redirects_to_dashboard(
    client: Any, driver: _Driver
) -> None:
    resp = client.get(
        "/api/blackout",
        headers={**_BOOKMARK, "Accept": "text/html,application/xhtml+xml,*/*;q=0.8"},
    )
    assert resp.status_code == 303
    assert resp.headers["Location"].endswith("/")


@pytest.mark.parametrize(
    "headers",
    [
        {"Sec-Fetch-Site": "cross-site"},
        {"Sec-Fetch-Site": "same-site"},
        {"Referer": "https://evil.example/page"},
        {"Origin": "https://evil.example"},
    ],
    ids=["cross-site", "same-site", "foreign-referer", "foreign-origin"],
)
def test_cross_site_get_is_refused(
    client: Any, flask_app: Flask, driver: _Driver, headers: dict[str, str]
) -> None:
    resp = client.get("/api/blackout", headers=headers)
    assert resp.status_code == 403
    assert not blackout.is_active(flask_app.config["DEVICE_CONFIG"])
    assert driver.images == []


@pytest.mark.parametrize(
    "headers",
    [
        {"Sec-Fetch-Site": "same-origin"},
        {"Referer": "http://localhost/"},
        {},
    ],
    ids=["same-origin", "same-host-referer", "no-browser-headers"],
)
def test_same_origin_get_is_allowed(
    client: Any, flask_app: Flask, driver: _Driver, headers: dict[str, str]
) -> None:
    resp = client.get("/api/blackout", headers=headers)
    assert resp.status_code == 200
    assert blackout.is_active(flask_app.config["DEVICE_CONFIG"])


def test_panel_endpoints_refused_during_blackout(
    client: Any, flask_app: Flask, driver: _Driver
) -> None:
    client.post("/api/blackout")
    resp = client.post("/display-next")
    assert resp.status_code == 409
    body = resp.get_json()
    assert body["code"] == "blackout_active"
    assert "blackout" in body["error"].lower()
    resp = client.post("/update_now", data={"plugin_id": "clock"})
    assert resp.status_code == 409

    client.delete("/api/blackout")
    # Other routes are unaffected once lifted (no 409).
    assert client.post("/display-next").status_code != 409


def test_dashboard_shows_banner_only_during_blackout(
    client: Any, driver: _Driver
) -> None:
    assert b"blackoutBanner" not in client.get("/").data
    client.post("/api/blackout")
    page = client.get("/").data
    assert b"blackoutBanner" in page
    assert b"blackoutResumeBtn" in page


def test_diagnostics_reports_blackout(
    client: Any, driver: _Driver, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INKYPI_ENV", "dev")
    assert client.get("/api/diagnostics").get_json()["blackout"]["active"] is False
    client.post("/api/blackout")
    assert client.get("/api/diagnostics").get_json()["blackout"]["active"] is True


# ---------------------------------------------------------------------------
# Real CSRF middleware
# ---------------------------------------------------------------------------


@pytest.fixture()
def csrf_client(device_config_dev: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    """The production app with the real CSRF check left in place."""
    import inkypi
    from display.display_manager import DisplayManager
    from plugins.plugin_registry import load_plugins
    from refresh_task import RefreshTask

    monkeypatch.delenv("INKYPI_ENV", raising=False)
    monkeypatch.delenv("FLASK_ENV", raising=False)
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-blackout")
    inkypi = importlib.reload(inkypi)

    def _fake_init_core_services(app: Flask) -> Any:
        display_manager = DisplayManager(device_config_dev)
        display_manager.display = _Driver()
        app.config["DEVICE_CONFIG"] = device_config_dev
        app.config["DISPLAY_MANAGER"] = display_manager
        app.config["REFRESH_TASK"] = RefreshTask(device_config_dev, display_manager)
        app.config["WEB_ONLY"] = False
        load_plugins(device_config_dev.get_plugins())
        return device_config_dev

    monkeypatch.setattr(inkypi, "_init_core_services", _fake_init_core_services)
    monkeypatch.setattr(inkypi, "setup_signal_handlers", lambda app: None)
    return inkypi.create_app().test_client()


def test_post_and_delete_require_csrf_token(
    csrf_client: Any, device_config_dev: Any
) -> None:
    assert csrf_client.post("/api/blackout").status_code == 403
    assert not blackout.is_active(device_config_dev)

    # The bookmark GET needs no token.
    assert csrf_client.get("/api/blackout", headers=_BOOKMARK).status_code == 200
    assert blackout.is_active(device_config_dev)
    assert csrf_client.delete("/api/blackout").status_code == 403
    assert blackout.is_active(device_config_dev)

    with csrf_client.session_transaction() as sess:
        sess["_csrf_token"] = "tok"
    resp = csrf_client.delete("/api/blackout", headers={"X-CSRFToken": "tok"})
    assert resp.status_code == 200
    assert not blackout.is_active(device_config_dev)


# ---------------------------------------------------------------------------
# Refresh loop
# ---------------------------------------------------------------------------


def _task(device_config: Any) -> tuple[Any, _Driver]:
    from display.display_manager import DisplayManager
    from refresh_task import RefreshTask

    dm = DisplayManager(device_config)
    recording = _Driver()
    dm.display = recording
    return RefreshTask(device_config, dm), recording


def test_scheduled_refresh_is_skipped_during_blackout(
    device_config_dev: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    task, _ = _task(device_config_dev)
    blackout.set_active(device_config_dev, True)
    selected: list[Any] = []

    def _select(*args: Any) -> tuple[None, None]:
        selected.append(args)
        return None, None

    monkeypatch.setattr(task, "_select_refresh_action", _select)
    calls = iter([("pm", "latest", "now", None), None])
    monkeypatch.setattr(task, "_wait_for_trigger", lambda: next(calls))

    task._run()

    assert selected == []


def test_manual_update_refused_during_blackout(device_config_dev: Any) -> None:
    from refresh_task import ManualRefresh

    task, _ = _task(device_config_dev)
    blackout.set_active(device_config_dev, True)
    task.start()
    try:
        with pytest.raises(blackout.BlackoutActiveError):
            task.manual_update(ManualRefresh("clock", {}))
    finally:
        task.stop()


def test_queued_manual_request_refused_once_blackout_starts(
    device_config_dev: Any,
) -> None:
    from refresh_task import ManualRefresh, ManualUpdateRequest

    task, _ = _task(device_config_dev)
    request = ManualUpdateRequest("rid", ManualRefresh("clock", {}))
    blackout.set_active(device_config_dev, True)

    assert task._handle_special_request(request) is True
    assert isinstance(request.exception, blackout.BlackoutActiveError)
    assert request.done.is_set()


def test_display_command_runs_on_refresh_thread(device_config_dev: Any) -> None:
    import threading

    task, recording = _task(device_config_dev)
    seen: list[str] = []

    def _command(dm: Any) -> dict[str, object]:
        seen.append(threading.current_thread().name)
        return dict(dm.show_system_image(blackout.blank_image(device_config_dev)))

    task.start()
    try:
        metrics = task.run_display_command("probe", _command, timeout=10)
    finally:
        task.stop()

    assert seen == ["RefreshTask"]
    assert metrics["display_driver"] == "_Driver"
    assert len(recording.images) == 1


def test_display_command_error_is_raised_to_caller(device_config_dev: Any) -> None:
    task, _ = _task(device_config_dev)

    def _boom(_dm: Any) -> None:
        raise OSError("panel unplugged")

    task.start()
    try:
        with pytest.raises(OSError, match="panel unplugged"):
            task.run_display_command("probe", _boom, timeout=10)
    finally:
        task.stop()


def test_system_image_clears_dedup_hash_and_skips_previews(
    device_config_dev: Any,
) -> None:
    import os

    _, recording = _task(device_config_dev)
    from display.display_manager import DisplayManager

    dm = DisplayManager(device_config_dev)
    dm.display = recording
    content = Image.new("RGB", (800, 480), "green")
    dm.display_image(content)
    os.remove(device_config_dev.current_image_file)

    dm.show_system_image(blackout.blank_image(device_config_dev))

    # No preview written for the system frame...
    assert not os.path.exists(device_config_dev.current_image_file)
    # ...and the same content is pushed again afterwards, not deduped away.
    dm.display_image(content)
    assert len(recording.images) == 3
