"""Regression tests for Config.update_atomic (JTN-498).

Ensures that concurrent read-modify-write operations on the playlist are
protected by the config lock so that no edits are silently dropped.
"""

from __future__ import annotations

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
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


def _make_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
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


def test_update_atomic_applies_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """update_atomic calls update_fn and persists the result."""
    cfg = _make_config(tmp_path, monkeypatch)
    cfg.update_atomic(lambda c: c.update({"extra_key": "hello"}))
    assert cfg.config.get("extra_key") == "hello"


def test_update_atomic_writes_to_disk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """update_atomic writes the config to disk after the mutation."""
    cfg = _make_config(tmp_path, monkeypatch)
    cfg.update_atomic(lambda c: c.update({"disk_test": True}))
    with open(cfg.config_file) as fh:
        on_disk = json.load(fh)
    assert on_disk.get("disk_test") is True


def test_update_atomic_exception_does_not_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If update_fn raises, write_config should not be reached."""
    cfg = _make_config(tmp_path, monkeypatch)
    original_hash = cfg._last_written_hash

    def _bad_fn(c: Any) -> None:
        c["should_not_persist"] = "bad"
        raise RuntimeError("intentional failure")

    with pytest.raises(RuntimeError):
        cfg.update_atomic(_bad_fn)

    # The hash should still be None (no write happened)
    assert cfg._last_written_hash == original_hash
    assert "should_not_persist" not in cfg.config


@pytest.mark.parametrize("operation", ["atomic", "config", "value"])
def test_failed_save_restores_live_and_disk_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    from copy import deepcopy

    cfg = _make_config(tmp_path, monkeypatch)
    cfg.write_config()
    before = deepcopy(cfg.config)
    disk_before = Path(cfg.config_file).read_bytes()
    hash_before = cfg._last_written_hash
    manager = cfg.playlist_manager
    playlist = manager.playlists[0]
    refresh = cfg.refresh_info
    cache_before = deepcopy(cfg._config_cache_data)

    def fail_replace(*args: Any) -> None:
        raise OSError("injected disk failure")

    monkeypatch.setattr("config.os.replace", fail_replace)

    def mutate(data: dict[str, Any]) -> None:
        data["name"] = "failed change"
        data["image_settings"]["brightness"] = 9
        playlist.name = "failed playlist"
        manager.add_playlist("failed new playlist")
        refresh.plugin_id = "failed plugin"

    with pytest.raises(OSError):
        if operation == "atomic":
            cfg.update_atomic(mutate)
        elif operation == "config":
            cfg.update_config({"name": "failed change"})
        else:
            cfg.update_value("name", "failed change", write=True)

    assert cfg.config == before
    assert Path(cfg.config_file).read_bytes() == disk_before
    assert cfg._last_written_hash == hash_before
    assert cfg._config_cache_data == cache_before
    assert cfg.playlist_manager is manager
    assert cfg.playlist_manager.playlists[0] is playlist
    assert cfg.refresh_info is refresh
    assert manager.to_dict() == before["playlist_config"]
    assert refresh.to_dict() == before["refresh_info"]


def test_callback_saving_helper_does_not_commit_before_callback_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = _make_config(tmp_path, monkeypatch)
    cfg.write_config()
    disk_before = Path(cfg.config_file).read_bytes()

    def mutate(current: dict[str, Any]) -> None:
        cfg.update_value("name", "partial", write=True)
        cfg.write_config()
        raise RuntimeError("callback failed after nested save")

    with pytest.raises(RuntimeError):
        cfg.update_atomic(mutate)
    assert Path(cfg.config_file).read_bytes() == disk_before
    assert cfg.get_config("name") == "AtomicTest"
    cfg.update_value("name", "successful retry", write=True)
    assert json.loads(Path(cfg.config_file).read_text())["name"] == "successful retry"


def test_direct_model_save_failure_restores_existing_model_references(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = _make_config(tmp_path, monkeypatch)
    manager = cfg.playlist_manager
    manager.add_plugin_to_playlist(
        "Default",
        {
            "plugin_id": "clock",
            "name": "clock",
            "refresh": {"interval": 3600},
            "plugin_settings": {"nested": [1]},
        },
    )
    cfg.write_config()
    playlist = manager.playlists[0]
    plugin = playlist.plugins[0]
    disk_before = Path(cfg.config_file).read_bytes()
    plugin.settings["nested"].append(2)
    manager.delete_playlist("Default")

    def fail(*args: Any) -> None:
        raise OSError("disk failure")

    monkeypatch.setattr("config.os.replace", fail)
    with pytest.raises(OSError):
        cfg.write_config()
    assert manager.playlists[0] is playlist
    assert playlist.plugins[0] is plugin
    assert plugin.settings["nested"] == [1]
    assert Path(cfg.config_file).read_bytes() == disk_before


# ---------------------------------------------------------------------------
# Concurrent regression test: N threads each add a distinct plugin instance
# ---------------------------------------------------------------------------


def test_concurrent_add_to_playlist_no_clobber(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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

        def _do_add(c: Any) -> None:
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
