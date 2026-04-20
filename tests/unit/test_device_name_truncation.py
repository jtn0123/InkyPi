"""Tests for JTN-777: oversize legacy device name must be coerced at load.

The server-side `/save_settings` handler caps ``deviceName`` at 64 characters
(JTN-746). But a stale ``device.local.json`` edited before that cap existed
(or restored from an older backup) can contain names longer than 64 chars,
which would leak unbounded into ``<title>``, the ``title=`` tooltip on
``<h1 class="app-title">``, and the ``alt=`` attribute of ``#previewImage`` —
all places CSS cannot truncate.

The fix coerces ``config['name']`` to <=64 chars at config-load time, so every
downstream consumer (templates, screen readers, browser tab) sees the capped
value regardless of what's on disk.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import pytest

import config as config_mod

_BASE_CFG: dict[str, Any] = {
    "name": "OK",
    "display_type": "mock",
    "resolution": [800, 480],
    "orientation": "horizontal",
    "plugin_cycle_interval_seconds": 300,
    "image_settings": {
        "saturation": 1.0,
        "brightness": 1.0,
        "sharpness": 1.0,
        "contrast": 1.0,
    },
    "playlist_config": {"playlists": [], "active_playlist": ""},
    "refresh_info": {
        "refresh_time": None,
        "image_hash": None,
        "refresh_type": "Manual Update",
        "plugin_id": "",
    },
}


def _write_cfg(path, name: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = dict(_BASE_CFG)
    data["name"] = name
    with open(path, "w") as fh:
        json.dump(data, fh)


def _make_config(tmp_path, monkeypatch, name: str) -> config_mod.Config:
    """Build a Config pointed at a fresh tmp_path device.json with *name*."""
    config_file = tmp_path / "config" / "device.json"
    _write_cfg(str(config_file), name=name)

    monkeypatch.setattr(config_mod.Config, "config_file", str(config_file))
    monkeypatch.setattr(
        config_mod.Config, "current_image_file", str(tmp_path / "current_image.png")
    )
    monkeypatch.setattr(
        config_mod.Config,
        "processed_image_file",
        str(tmp_path / "processed_image.png"),
    )
    monkeypatch.setattr(
        config_mod.Config, "plugin_image_dir", str(tmp_path / "plugins")
    )
    monkeypatch.setattr(
        config_mod.Config, "history_image_dir", str(tmp_path / "history")
    )
    monkeypatch.setenv("PROJECT_DIR", str(tmp_path))
    (tmp_path / ".env").write_text("")

    return config_mod.Config()


# ---------------------------------------------------------------------------
# 1. Oversize name is truncated to 64 chars at load
# ---------------------------------------------------------------------------


def test_oversize_name_truncated_on_load(tmp_path, monkeypatch, caplog):
    """A 500-char stored name is exposed as <=64 chars after load."""
    long_name = "A" * 500
    with caplog.at_level(logging.WARNING, logger="config"):
        cfg = _make_config(tmp_path, monkeypatch, long_name)

    stored = cfg.get_config("name")
    assert isinstance(stored, str)
    assert len(stored) == config_mod._DEVICE_NAME_MAX_LEN
    assert stored == "A" * config_mod._DEVICE_NAME_MAX_LEN

    # A warning should be logged so operators know coercion happened.
    assert any(
        "device_name_truncated" in rec.message for rec in caplog.records
    ), "expected a 'device_name_truncated' warning in logs"


def test_oversize_name_persists_coerced_on_write(tmp_path, monkeypatch):
    """After write_config(), on-disk name is the coerced 64-char value.

    The in-memory config is already coerced, so the next natural flush of
    settings will persist the capped value. This is the intended behaviour:
    callers don't have to remember to truncate before saving.
    """
    long_name = "B" * 500
    cfg = _make_config(tmp_path, monkeypatch, long_name)

    # Force a disk write (e.g. triggered by any settings mutation).
    cfg.write_config()

    # Re-read the raw JSON from disk, bypassing the cache, to confirm on-disk
    # state.
    with open(cfg.config_file) as fh:
        on_disk = json.load(fh)
    assert len(on_disk["name"]) == config_mod._DEVICE_NAME_MAX_LEN


# ---------------------------------------------------------------------------
# 2. At-or-under cap names are untouched
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "",  # empty (should not be modified here; validation happens elsewhere)
        "InkyPi",
        "a" * 63,
        "a" * 64,  # exactly at the cap
        "Kitchen Display ☕",  # unicode; <64 chars
    ],
)
def test_name_at_or_under_cap_untouched(tmp_path, monkeypatch, name):
    """Names with <=64 characters round-trip unchanged through read_config."""
    cfg = _make_config(tmp_path, monkeypatch, name)
    assert cfg.get_config("name") == name


def test_exactly_at_cap_does_not_log_warning(tmp_path, monkeypatch, caplog):
    """64-char names must not trigger the truncation warning (no false positives)."""
    name = "c" * config_mod._DEVICE_NAME_MAX_LEN
    with caplog.at_level(logging.WARNING, logger="config"):
        cfg = _make_config(tmp_path, monkeypatch, name)

    assert cfg.get_config("name") == name
    assert not any(
        "device_name_truncated" in rec.message for rec in caplog.records
    ), "no truncation warning should fire for a name exactly at the cap"


# ---------------------------------------------------------------------------
# 3. Rendered main page does not leak the full oversize string
# ---------------------------------------------------------------------------


def _oversize_device_config(tmp_path, monkeypatch, long_name: str):
    """Build a device_config pointing at a tmp device.json with *long_name*.

    Mirrors the ``device_config_dev`` fixture shape so it plugs into the
    flask_app / client fixture chain.
    """
    cfg_data = dict(_BASE_CFG)
    cfg_data["name"] = long_name
    cfg_data["output_dir"] = str(tmp_path / "mock_output")
    cfg_data["timezone"] = "UTC"
    cfg_data["time_format"] = "24h"
    cfg_data["enable_benchmarks"] = False
    cfg_data["benchmarks_db_path"] = str(tmp_path / "benchmarks.sqlite3")
    config_file = tmp_path / "device.json"
    config_file.write_text(json.dumps(cfg_data))
    (tmp_path / ".env").write_text("", encoding="utf-8")

    monkeypatch.setenv("PROJECT_DIR", str(tmp_path))
    monkeypatch.setattr(config_mod.Config, "config_file", str(config_file))
    monkeypatch.setattr(
        config_mod.Config, "current_image_file", str(tmp_path / "current_image.png")
    )
    monkeypatch.setattr(
        config_mod.Config,
        "processed_image_file",
        str(tmp_path / "processed_image.png"),
    )
    monkeypatch.setattr(
        config_mod.Config, "plugin_image_dir", str(tmp_path / "plugins")
    )
    monkeypatch.setattr(
        config_mod.Config, "history_image_dir", str(tmp_path / "history")
    )
    os.makedirs(str(tmp_path / "plugins"), exist_ok=True)
    os.makedirs(str(tmp_path / "history"), exist_ok=True)

    return config_mod.Config()


def test_rendered_main_page_does_not_leak_oversize_name(tmp_path, monkeypatch):
    """<title> and alt= must contain only the coerced 64-char name."""
    import importlib
    import secrets as _secrets

    from flask import session as _session

    import inkypi
    from app_setup import security_middleware
    from display.display_manager import DisplayManager
    from plugins.plugin_registry import load_plugins
    from refresh_task import RefreshTask
    from utils.rate_limiter import SlidingWindowLimiter

    long_name = "Z" * 500
    device_config = _oversize_device_config(tmp_path, monkeypatch, long_name)

    # Sanity: loader already coerced in-memory.
    assert len(device_config.get_config("name")) == config_mod._DEVICE_NAME_MAX_LEN

    monkeypatch.delenv("INKYPI_ENV", raising=False)
    monkeypatch.delenv("FLASK_ENV", raising=False)
    inkypi = importlib.reload(inkypi)

    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-csrf")
    monkeypatch.setenv("INKYPI_RATE_LIMIT_AUTH", "100000/60")
    monkeypatch.setenv("INKYPI_RATE_LIMIT_REFRESH", "100000/60")
    monkeypatch.setenv("INKYPI_RATE_LIMIT_MUTATING", "100000/60")
    security_middleware._mutation_limiter = SlidingWindowLimiter(100000, 60)

    def _fake_init_core_services(app):
        display_manager = DisplayManager(device_config)
        refresh_task = RefreshTask(device_config, display_manager)
        load_plugins(device_config.get_plugins())
        app.config["DEVICE_CONFIG"] = device_config
        app.config["DISPLAY_MANAGER"] = display_manager
        app.config["REFRESH_TASK"] = refresh_task
        app.config["WEB_ONLY"] = False
        return device_config

    def _setup_csrf_token_only(app):
        def _generate_csrf_token() -> str:
            if "_csrf_token" not in _session:
                _session["_csrf_token"] = _secrets.token_hex(32)
            return _session["_csrf_token"]

        @app.context_processor
        def _inject_csrf_token():
            return {"csrf_token": _generate_csrf_token}

    monkeypatch.setattr(inkypi, "_init_core_services", _fake_init_core_services)
    monkeypatch.setattr(inkypi, "setup_csrf_protection", _setup_csrf_token_only)
    monkeypatch.setattr(inkypi, "setup_signal_handlers", lambda app: None)

    app = inkypi.create_app()
    client = app.test_client()

    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)

    # The oversize string must never appear verbatim.
    assert long_name not in body, (
        "rendered main page leaked the full oversize device name — "
        "JTN-777 coercion did not reach templates"
    )

    # The coerced 64-char prefix must appear at least in <title> and alt=.
    coerced = "Z" * config_mod._DEVICE_NAME_MAX_LEN
    # Rough assertions — use presence, not exact position.
    assert f"<title>{coerced}" in body, "expected coerced name in <title>"
    assert (
        f'alt="Current display for {coerced}"' in body
    ), "expected coerced name in previewImage alt="
    assert (
        f'title="{coerced}"' in body
    ), 'expected coerced name in <h1 class="app-title"> title='


# ---------------------------------------------------------------------------
# 4. Valid (<=64) names round-trip through /save_settings unchanged
# ---------------------------------------------------------------------------


def test_valid_name_round_trips_through_save_settings(tmp_path, monkeypatch):
    """A 64-char name saved via /save_settings is stored and read back intact."""
    import importlib
    import secrets as _secrets

    from flask import session as _session

    import inkypi
    from app_setup import security_middleware
    from display.display_manager import DisplayManager
    from plugins.plugin_registry import load_plugins
    from refresh_task import RefreshTask
    from utils.rate_limiter import SlidingWindowLimiter

    # Start with a short name; save a 64-char name via /save_settings; confirm
    # both the in-memory and on-disk config expose the same value.
    device_config = _oversize_device_config(tmp_path, monkeypatch, "start")

    monkeypatch.delenv("INKYPI_ENV", raising=False)
    monkeypatch.delenv("FLASK_ENV", raising=False)
    inkypi = importlib.reload(inkypi)

    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-csrf")
    monkeypatch.setenv("INKYPI_RATE_LIMIT_AUTH", "100000/60")
    monkeypatch.setenv("INKYPI_RATE_LIMIT_REFRESH", "100000/60")
    monkeypatch.setenv("INKYPI_RATE_LIMIT_MUTATING", "100000/60")
    security_middleware._mutation_limiter = SlidingWindowLimiter(100000, 60)

    def _fake_init_core_services(app):
        display_manager = DisplayManager(device_config)
        refresh_task = RefreshTask(device_config, display_manager)
        load_plugins(device_config.get_plugins())
        app.config["DEVICE_CONFIG"] = device_config
        app.config["DISPLAY_MANAGER"] = display_manager
        app.config["REFRESH_TASK"] = refresh_task
        app.config["WEB_ONLY"] = False
        return device_config

    def _setup_csrf_token_only(app):
        def _generate_csrf_token() -> str:
            if "_csrf_token" not in _session:
                _session["_csrf_token"] = _secrets.token_hex(32)
            return _session["_csrf_token"]

        @app.context_processor
        def _inject_csrf_token():
            return {"csrf_token": _generate_csrf_token}

    monkeypatch.setattr(inkypi, "_init_core_services", _fake_init_core_services)
    monkeypatch.setattr(inkypi, "setup_csrf_protection", _setup_csrf_token_only)
    monkeypatch.setattr(inkypi, "setup_signal_handlers", lambda app: None)

    app = inkypi.create_app()
    client = app.test_client()

    # Prime a CSRF token by hitting the main page.
    client.get("/")
    with client.session_transaction() as sess:
        csrf_token = sess.get("_csrf_token")
    assert csrf_token, "test setup should have provisioned a CSRF token"

    valid_name = "L" * config_mod._DEVICE_NAME_MAX_LEN

    # /save_settings expects a full settings form payload; we only care about
    # the name round-trip here, so send the minimum valid payload.
    form = {
        "deviceName": valid_name,
        "orientation": "horizontal",
        "interval": "5",
        "unit": "minute",
        "timezoneName": "UTC",
        "timeFormat": "24h",
    }
    resp = client.post(
        "/save_settings",
        data=form,
        headers={"X-CSRFToken": csrf_token},
    )
    assert resp.status_code in (200, 302), (
        f"save_settings should accept a 64-char name; got {resp.status_code}: "
        f"{resp.get_data(as_text=True)[:200]}"
    )

    # Invalidate cache so read_config re-stats the file after the write.
    device_config.invalidate_config_cache()
    assert device_config.get_config("name") == valid_name
