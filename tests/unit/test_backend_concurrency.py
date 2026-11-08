"""Regression tests for panel-write serialisation and route error handling.

Covers: serialised panel writes (startup image, history redisplay, the
DisplayManager driver lock), ``manual_update`` refusing when the refresh task
is stopped, the playlist index advance being held under the config lock, a
single benchmark row per ``/display-next``, and internal errors not echoing
exception text to the client.
"""

from __future__ import annotations

import os
import subprocess
import threading
import time
from typing import Any

import pytest
from flask import Flask
from flask.testing import FlaskClient
from PIL import Image

from utils.backend_errors import RefreshTaskUnavailable

_SECRET = "/var/lib/inkypi/secret-path.db: no such table refresh_events"


# ---------------------------------------------------------------------------
# Panel writes are serialised
# ---------------------------------------------------------------------------


class _SlowDriver:
    """Driver stub that records how many writes overlap."""

    def __init__(self) -> None:
        self._guard = threading.Lock()
        self.active = 0
        self.max_active = 0
        self.writes = 0

    def display_image(self, image: Any, image_settings: Any = None) -> None:
        with self._guard:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        time.sleep(0.05)
        with self._guard:
            self.active -= 1
            self.writes += 1


def test_display_manager_serialises_concurrent_driver_writes(
    device_config_dev: Any, tmp_path: Any
) -> None:
    from display.display_manager import DisplayManager

    dm = DisplayManager(device_config_dev)
    driver = _SlowDriver()
    dm.display = driver

    frame_path = str(tmp_path / "frame.png")
    Image.new("RGB", (16, 16), "white").save(frame_path)
    frame = Image.new("RGB", (16, 16), "black")

    callers = [
        lambda: dm.show_system_image(frame),
        lambda: dm.display_preprocessed_image(frame_path),
        lambda: dm.show_system_image(frame),
        lambda: dm.display_preprocessed_image(frame_path),
    ]
    threads = [threading.Thread(target=fn) for fn in callers]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert driver.writes == len(callers)
    assert driver.max_active == 1


def test_history_redisplay_goes_through_refresh_task(
    client: FlaskClient,
    device_config_dev: Any,
    flask_app: Flask,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    d = device_config_dev.history_image_dir
    os.makedirs(d, exist_ok=True)
    fname = "display_20250101_030000.png"
    Image.new("RGB", (10, 10), "white").save(os.path.join(d, fname))

    rt = flask_app.config["REFRESH_TASK"]
    dm = flask_app.config["DISPLAY_MANAGER"]
    commands: list[str] = []
    shown: list[str] = []

    def _run_display_command(name: str, run: Any, **_kw: Any) -> dict[str, Any]:
        commands.append(name)
        run(dm)
        return {}

    monkeypatch.setattr(rt, "run_display_command", _run_display_command)
    monkeypatch.setattr(dm, "display_preprocessed_image", lambda p: shown.append(p))

    resp = client.post("/history/redisplay", json={"filename": fname})

    assert resp.status_code == 200
    assert commands == ["history_redisplay"]
    assert len(shown) == 1 and shown[0].endswith(fname)


def test_startup_image_goes_through_refresh_task(
    flask_app: Flask, monkeypatch: pytest.MonkeyPatch
) -> None:
    import inkypi
    from utils import boot_self_test

    device_config = flask_app.config["DEVICE_CONFIG"]
    device_config.update_value("startup", True)
    monkeypatch.setattr(boot_self_test, "maybe_run", lambda *a, **k: None)

    rt = flask_app.config["REFRESH_TASK"]
    dm = flask_app.config["DISPLAY_MANAGER"]
    commands: list[str] = []
    shown: list[Any] = []

    def _run_display_command(name: str, run: Any, **_kw: Any) -> dict[str, Any]:
        commands.append(name)
        run(dm)
        return {}

    monkeypatch.setattr(rt, "run_display_command", _run_display_command)
    monkeypatch.setattr(dm, "display_image", lambda img: shown.append(img))

    inkypi.run_boot_display_tasks(flask_app)

    assert commands == ["startup_image"]
    assert len(shown) == 1
    assert device_config.get_config("startup") is False


# ---------------------------------------------------------------------------
# manual_update when the refresh task is stopped
# ---------------------------------------------------------------------------


def test_manual_update_raises_when_task_not_running(device_config_dev: Any) -> None:
    from unittest.mock import MagicMock

    from refresh_task import ManualRefresh, RefreshTask

    task = RefreshTask(device_config_dev, MagicMock())
    assert task.running is False

    with pytest.raises(RefreshTaskUnavailable) as excinfo:
        task.manual_update(ManualRefresh("clock", {}))
    assert excinfo.value.status == 503


def test_update_now_returns_503_if_task_stops_before_enqueue(
    client: FlaskClient, flask_app: Flask, monkeypatch: pytest.MonkeyPatch
) -> None:
    rt = flask_app.config["REFRESH_TASK"]
    monkeypatch.setattr(rt, "running", True)

    def _stopped(_action: Any) -> None:
        raise RefreshTaskUnavailable

    monkeypatch.setattr(rt, "manual_update", _stopped)

    resp = client.post("/update_now", data={"plugin_id": "clock"})

    assert resp.status_code == 503
    assert resp.get_json()["code"] == "refresh_task_unavailable"


# ---------------------------------------------------------------------------
# /display_next_in_playlist advances the index under the config lock
# ---------------------------------------------------------------------------


def test_display_next_in_playlist_advances_index_under_config_lock(
    client: FlaskClient,
    device_config_dev: Any,
    flask_app: Flask,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import model

    pm = device_config_dev.get_playlist_manager()
    pm.add_playlist("Locked", "00:00", "24:00")
    pm.get_playlist("Locked").add_plugin(
        {
            "plugin_id": "clock",
            "name": "Clock L",
            "plugin_settings": {},
            "refresh": {"interval": 300},
        }
    )

    held: list[bool] = []
    original = model.Playlist.get_next_eligible_plugin

    def _probe(self: Any, current_time: Any) -> Any:
        # Another thread can take the lock only if this one does not hold it.
        result: dict[str, bool] = {}

        def _try() -> None:
            got = device_config_dev._config_lock.acquire(blocking=False)
            if got:
                device_config_dev._config_lock.release()
            result["free"] = got

        t = threading.Thread(target=_try)
        t.start()
        t.join()
        held.append(not result["free"])
        return original(self, current_time)

    monkeypatch.setattr(model.Playlist, "get_next_eligible_plugin", _probe)
    rt = flask_app.config["REFRESH_TASK"]
    monkeypatch.setattr(rt, "running", True)
    monkeypatch.setattr(rt, "manual_update", lambda _a: {})

    resp = client.post("/display_next_in_playlist", json={"playlist_name": "Locked"})

    assert resp.status_code == 200
    assert held == [True]


# ---------------------------------------------------------------------------
# /display-next records exactly one benchmark row
# ---------------------------------------------------------------------------


def _single_clock_playlist(device_config_dev: Any) -> None:
    pm = device_config_dev.get_playlist_manager()
    if not pm.get_playlist("Default"):
        pm.add_playlist("Default", "00:00", "24:00")
    pm.get_playlist("Default").add_plugin(
        {
            "plugin_id": "clock",
            "name": "Clock N",
            "plugin_settings": {},
            "refresh": {"interval": 300},
        }
    )


def test_display_next_via_refresh_task_does_not_record_extra_benchmark_row(
    client: FlaskClient,
    device_config_dev: Any,
    flask_app: Flask,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import blueprints.main as main_mod

    _single_clock_playlist(device_config_dev)
    rows: list[dict[str, Any]] = []
    monkeypatch.setattr(
        main_mod, "save_refresh_event", lambda _cfg, row: rows.append(row)
    )
    rt = flask_app.config["REFRESH_TASK"]
    monkeypatch.setattr(rt, "running", True)
    # The real loop records its own row in RefreshTask._save_benchmark.
    monkeypatch.setattr(rt, "manual_update", lambda _a: {})

    resp = client.post("/display-next")

    assert resp.status_code == 200
    assert rows == []


def test_display_next_direct_path_records_one_benchmark_row(
    client: FlaskClient,
    device_config_dev: Any,
    flask_app: Flask,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import blueprints.main as main_mod
    from plugins import plugin_registry

    _single_clock_playlist(device_config_dev)
    rows: list[dict[str, Any]] = []
    monkeypatch.setattr(
        main_mod, "save_refresh_event", lambda _cfg, row: rows.append(row)
    )

    class _StubPlugin:
        def generate_image(self, settings: Any, device_config: Any) -> Any:
            return Image.new("RGB", (800, 480), "white")

    monkeypatch.setattr(
        plugin_registry, "get_plugin_instance", lambda cfg: _StubPlugin()
    )
    dm = flask_app.config["DISPLAY_MANAGER"]
    monkeypatch.setattr(dm, "display_image", lambda *a, **k: None)
    assert flask_app.config["REFRESH_TASK"].running is False

    resp = client.post("/display-next")

    assert resp.status_code == 200
    assert len(rows) == 1
    assert rows[0]["notes"] == "display_next_dev"


# ---------------------------------------------------------------------------
# Internal errors do not leak exception text
# ---------------------------------------------------------------------------


def _assert_no_leak(resp: Any, context: str) -> None:
    assert resp.status_code == 500
    body = resp.get_json()
    assert body["error"] == "An internal error occurred"
    assert body["details"]["context"] == context
    assert "error" not in body["details"]
    assert "secret-path" not in resp.get_data(as_text=True)


@pytest.mark.parametrize(
    ("path", "context"),
    [
        ("/api/benchmarks/summary", "benchmarks summary"),
        ("/api/benchmarks/refreshes", "benchmarks refreshes"),
        ("/api/benchmarks/plugins", "benchmarks plugins"),
        ("/api/benchmarks/stages?refresh_id=abc", "benchmarks stages"),
    ],
)
def test_benchmark_errors_do_not_leak_exception_text(
    client: FlaskClient, monkeypatch: pytest.MonkeyPatch, path: str, context: str
) -> None:
    import blueprints.settings as settings_mod

    def _boom() -> str:
        raise RuntimeError(_SECRET)

    monkeypatch.setattr(settings_mod, "_benchmarks_enabled", lambda: True)
    monkeypatch.setattr(settings_mod, "_get_bench_db_path", _boom)

    _assert_no_leak(client.get(path), context)


def test_health_plugins_error_does_not_leak_exception_text(
    client: FlaskClient, flask_app: Flask, monkeypatch: pytest.MonkeyPatch
) -> None:
    rt = flask_app.config["REFRESH_TASK"]

    def _boom() -> dict[str, Any]:
        raise RuntimeError(_SECRET)

    monkeypatch.setattr(rt, "get_health_snapshot", _boom)

    _assert_no_leak(client.get("/api/health/plugins"), "health plugins")


def test_shutdown_error_does_not_leak_exception_text(
    client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import blueprints.settings as settings_mod

    settings_mod._shutdown_limiter.reset()
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: (_ for _ in ()).throw(
            subprocess.CalledProcessError(1, ["sudo", _SECRET])
        ),
    )

    _assert_no_leak(client.post("/shutdown", json={}), "shutdown")
