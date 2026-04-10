"""Regression tests for Config.update_atomic (JTN-498).

Ensures that concurrent read-modify-write operations on the playlist are
protected by the config lock so that no edits are silently dropped.
"""

from __future__ import annotations

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import pytest

_MIN_CFG: dict[str, Any] = {
    "name": "AtomicTest",
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


def _write_config_file(path: str, data: dict | None = None) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(data if data is not None else _MIN_CFG, fh)


def _make_config(tmp_path, monkeypatch):
    """Build a Config instance pointing at a fresh tmp_path device.json."""
    # Ensure src/ is importable
    src_dir = os.path.join(os.path.dirname(__file__), "..", "..", "src")
    src_dir = os.path.abspath(src_dir)
    if src_dir not in sys.path:
        sys.path.insert(0, src_dir)

    import config as config_mod

    config_file = tmp_path / "config" / "device.json"
    _write_config_file(str(config_file))

    monkeypatch.setattr(config_mod.Config, "config_file", str(config_file))
    # Prevent directories from being created in the real src tree
    monkeypatch.setattr(
        config_mod.Config,
        "current_image_file",
        str(tmp_path / "images" / "current_image.png"),
    )
    monkeypatch.setattr(
        config_mod.Config,
        "processed_image_file",
        str(tmp_path / "images" / "processed_image.png"),
    )
    monkeypatch.setattr(
        config_mod.Config,
        "plugin_image_dir",
        str(tmp_path / "images" / "plugins"),
    )
    monkeypatch.setattr(
        config_mod.Config,
        "history_image_dir",
        str(tmp_path / "images" / "history"),
    )
    return config_mod.Config()


# ---------------------------------------------------------------------------
# Unit tests for update_atomic itself
# ---------------------------------------------------------------------------


def test_update_atomic_applies_mutation(tmp_path, monkeypatch):
    """update_atomic calls update_fn and persists the result."""
    cfg = _make_config(tmp_path, monkeypatch)
    cfg.update_atomic(lambda c: c.update({"extra_key": "hello"}))
    assert cfg.config.get("extra_key") == "hello"


def test_update_atomic_writes_to_disk(tmp_path, monkeypatch):
    """update_atomic writes the config to disk after the mutation."""
    cfg = _make_config(tmp_path, monkeypatch)
    cfg.update_atomic(lambda c: c.update({"disk_test": True}))
    with open(cfg.config_file) as fh:
        on_disk = json.load(fh)
    assert on_disk.get("disk_test") is True


def test_update_atomic_exception_does_not_write(tmp_path, monkeypatch):
    """If update_fn raises, write_config should not be reached."""
    cfg = _make_config(tmp_path, monkeypatch)
    original_hash = cfg._last_written_hash

    def _bad_fn(c):
        c["should_not_persist"] = "bad"
        raise RuntimeError("intentional failure")

    with pytest.raises(RuntimeError):
        cfg.update_atomic(_bad_fn)

    # The hash should still be None (no write happened)
    assert cfg._last_written_hash == original_hash


# ---------------------------------------------------------------------------
# Concurrent regression test: N threads each add a distinct plugin instance
# ---------------------------------------------------------------------------


def test_concurrent_add_to_playlist_no_clobber(tmp_path, monkeypatch):
    """Fire N threads each adding a different plugin instance via update_atomic.

    All N instances must survive in the final config without any being silently
    clobbered.
    """
    N = 20
    cfg = _make_config(tmp_path, monkeypatch)
    playlist_manager = cfg.playlist_manager

    # Ensure the Default playlist exists
    if not playlist_manager.get_playlist("Default"):
        playlist_manager.add_playlist("Default")
        cfg.write_config()

    errors: list[Exception] = []

    def _add_plugin(i: int) -> None:
        plugin_dict = {
            "plugin_id": "clock",
            "name": f"instance_{i}",
            "refresh": {"interval": 3600},
            "plugin_settings": {},
        }

        def _do_add(c):
            result = playlist_manager.add_plugin_to_playlist("Default", plugin_dict)
            if not result:
                raise RuntimeError(f"add_plugin_to_playlist failed for instance_{i}")

        cfg.update_atomic(_do_add)

    with ThreadPoolExecutor(max_workers=N) as executor:
        futures = [executor.submit(_add_plugin, i) for i in range(N)]
        for fut in as_completed(futures):
            exc = fut.exception()
            if exc is not None:
                errors.append(exc)

    assert not errors, f"Some threads raised: {errors}"

    # Reload from disk to verify durability
    with open(cfg.config_file) as fh:
        on_disk = json.load(fh)

    playlists = on_disk.get("playlist_config", {}).get("playlists", [])
    default_pl = next((p for p in playlists if p.get("name") == "Default"), None)
    assert default_pl is not None, "Default playlist missing from on-disk config"

    plugin_names = {p["name"] for p in default_pl.get("plugins", [])}
    expected = {f"instance_{i}" for i in range(N)}
    assert plugin_names == expected, (
        f"Missing plugins: {expected - plugin_names}; "
        f"extra: {plugin_names - expected}"
    )
