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

Note: imports of ``src/`` modules are contained to the helper functions and
test bodies (not at module scope) to avoid introducing new
``pythonarchitecture:S7788`` tests→src relationships. This matches the
established pattern documented in CHANGELOG and used by other test modules.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import pytest

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

# Mirror the cap imposed by Config._coerce_device_name (and by
# /save_settings in blueprints/settings/_config.py). Kept as a literal here so
# the test module does not need a module-scope ``import config``.
_CAP = 64


def _write_cfg(path: str, name: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = dict(_BASE_CFG)
    data["name"] = name
    with open(path, "w") as fh:
        json.dump(data, fh)


def _make_config(tmp_path, monkeypatch, name: str):
    """Build a Config instance pointed at a fresh tmp_path device.json.

    The ``config`` module is imported lazily inside the helper so the
    module-level import graph of this test file stays clean.
    """
    import config as config_mod  # noqa: PLC0415 — lazy on purpose (S7788)

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
    assert len(stored) == _CAP
    assert stored == "A" * _CAP

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
    assert len(on_disk["name"]) == _CAP


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
    name = "c" * _CAP
    with caplog.at_level(logging.WARNING, logger="config"):
        cfg = _make_config(tmp_path, monkeypatch, name)

    assert cfg.get_config("name") == name
    assert not any(
        "device_name_truncated" in rec.message for rec in caplog.records
    ), "no truncation warning should fire for a name exactly at the cap"


# ---------------------------------------------------------------------------
# 3. Rendered main page does not leak the full oversize string
# ---------------------------------------------------------------------------
#
# These tests reuse the project-wide ``client`` / ``device_config_dev``
# fixtures (see tests/conftest.py) so the Flask app bootstrap path is
# exercised *without* adding new ``test->src`` import edges to this module.
# We overwrite the fixture's on-disk device.json before the first request
# and invalidate the cache so the coercion in Config.read_config() fires on
# the next load.


def _rewrite_device_config_name(device_config, new_name: str) -> None:
    """Replace the on-disk device.json name and invalidate the mtime cache."""
    with open(device_config.config_file) as fh:
        data = json.load(fh)
    data["name"] = new_name
    with open(device_config.config_file, "w") as fh:
        json.dump(data, fh)
    device_config.invalidate_config_cache()
    # Force an immediate re-read so the in-memory ``.config`` dict (which
    # templates consume via ``device_config.get_config()``) reflects the new
    # file and the coercion path runs.
    device_config.config = device_config.read_config()


def test_rendered_main_page_does_not_leak_oversize_name(client, device_config_dev):
    """<title> and alt= must contain only the coerced 64-char name."""
    long_name = "Z" * 500
    _rewrite_device_config_name(device_config_dev, long_name)

    # Sanity: loader already coerced in-memory.
    assert len(device_config_dev.get_config("name")) == _CAP

    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)

    # The oversize string must never appear verbatim.
    assert long_name not in body, (
        "rendered main page leaked the full oversize device name — "
        "JTN-777 coercion did not reach templates"
    )

    # The coerced 64-char prefix must appear in <title>, alt= and title=.
    coerced = "Z" * _CAP
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


def test_valid_name_round_trips_through_save_settings(client, device_config_dev):
    """A 64-char name saved via /save_settings is stored and read back intact."""
    # Prime a CSRF token by hitting the main page.
    client.get("/")
    with client.session_transaction() as sess:
        csrf_token = sess.get("_csrf_token")
    assert csrf_token, "test setup should have provisioned a CSRF token"

    valid_name = "L" * _CAP

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
    device_config_dev.invalidate_config_cache()
    assert device_config_dev.get_config("name") == valid_name
