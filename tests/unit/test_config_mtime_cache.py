"""Tests for the mtime-based read cache added to Config.read_config() (JTN-519).

The cache must:
  - Return cached data (no parse) on repeated reads when the file is unchanged.
  - Re-parse when the file mtime advances (file was rewritten).
  - Re-parse when the cache is explicitly invalidated via invalidate_config_cache().
  - Be thread-safe under concurrent reads.
  - Survive a read → modify → write_config() cycle correctly.
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any
from unittest.mock import patch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MIN_CFG: dict[str, Any] = {
    "name": "CacheTest",
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


def _write_config(path: str, data: dict | None = None) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(data if data is not None else _MIN_CFG, fh)


def _make_config(tmp_path, monkeypatch) -> config_mod.Config:  # noqa: F821
    """Build a Config pointing at a fresh tmp_path device.json."""
    import config as config_mod

    config_file = tmp_path / "config" / "device.json"
    _write_config(str(config_file))

    monkeypatch.setattr(config_mod.Config, "config_file", str(config_file))
    monkeypatch.setattr(
        config_mod.Config, "current_image_file", str(tmp_path / "current_image.png")
    )
    monkeypatch.setattr(
        config_mod.Config, "processed_image_file", str(tmp_path / "processed_image.png")
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
# 1. Cache hit — repeated reads skip JSON parse
# ---------------------------------------------------------------------------


def test_repeated_reads_use_cache(tmp_path, monkeypatch):
    """1 000 read_config() calls on an unchanged file produce only 1 json.load."""
    cfg = _make_config(tmp_path, monkeypatch)

    parse_count = {"n": 0}
    original_json_load = json.load

    def counting_load(fp):
        parse_count["n"] += 1
        return original_json_load(fp)

    import config as config_mod

    with patch.object(config_mod.json, "load", side_effect=counting_load):
        for _ in range(1000):
            result = cfg.read_config()

    assert parse_count["n"] == 0, (
        f"Expected 0 json.load calls (all cache hits) but got {parse_count['n']}. "
        "The mtime cache is not working."
    )
    assert result["name"] == "CacheTest"


def test_first_read_after_construction_hits_cache(tmp_path, monkeypatch):
    """After __init__, the cache is warm so read_config() returns cached data."""
    cfg = _make_config(tmp_path, monkeypatch)

    # Cache should be populated from __init__
    assert cfg._config_cache_mtime is not None
    assert cfg._config_cache_data is not None

    # A second call should hit the cache (no json.load)
    parse_count = {"n": 0}

    import config as config_mod

    original_load = json.load

    def counting_load(fp):
        parse_count["n"] += 1
        return original_load(fp)

    with patch.object(config_mod.json, "load", side_effect=counting_load):
        result = cfg.read_config()

    assert parse_count["n"] == 0
    assert isinstance(result, dict)


def test_cache_returns_copy_not_reference(tmp_path, monkeypatch):
    """read_config() must return a copy so callers cannot mutate the cached dict."""
    cfg = _make_config(tmp_path, monkeypatch)

    result1 = cfg.read_config()
    result1["__poison__"] = True  # mutate the returned dict

    result2 = cfg.read_config()
    assert "__poison__" not in result2, (
        "read_config() returned the same dict object (not a copy). "
        "Callers could corrupt the cache."
    )


# ---------------------------------------------------------------------------
# 2. Cache miss — file rewritten (mtime advances)
# ---------------------------------------------------------------------------


def test_cache_invalidates_after_file_rewrite(tmp_path, monkeypatch):
    """After rewriting the file (advancing mtime), read_config() re-parses."""
    cfg = _make_config(tmp_path, monkeypatch)

    # Confirm cache is warm
    assert cfg._config_cache_mtime is not None

    # Wait a tick to guarantee a new mtime on some filesystems
    time.sleep(0.01)

    # Rewrite the file with a different name
    updated = dict(_MIN_CFG, name="UpdatedName")
    _write_config(str(cfg.config_file), data=updated)

    result = cfg.read_config()
    assert (
        result["name"] == "UpdatedName"
    ), "read_config() returned stale cached data after the file was rewritten."


def test_mtime_bump_invalidates_cache(tmp_path, monkeypatch):
    """Manually touching (bumping) the mtime causes re-parse."""
    cfg = _make_config(tmp_path, monkeypatch)

    original_mtime = cfg._config_cache_mtime

    # Sleep briefly then touch the file (update mtime without changing content)
    time.sleep(0.02)
    now = time.time()
    os.utime(cfg.config_file, (now, now))

    parse_count = {"n": 0}
    import config as config_mod

    original_load = json.load

    def counting_load(fp):
        parse_count["n"] += 1
        return original_load(fp)

    with patch.object(config_mod.json, "load", side_effect=counting_load):
        cfg.read_config()

    new_mtime = cfg._config_cache_mtime
    assert new_mtime != original_mtime, "mtime_ns should have changed after utime()"
    assert (
        parse_count["n"] == 1
    ), f"Expected exactly 1 json.load after mtime bump, got {parse_count['n']}"


# ---------------------------------------------------------------------------
# 3. Explicit invalidation via invalidate_config_cache()
# ---------------------------------------------------------------------------


def test_invalidate_config_cache_clears_cache(tmp_path, monkeypatch):
    """invalidate_config_cache() resets the cache so the next read re-parses."""
    cfg = _make_config(tmp_path, monkeypatch)

    assert cfg._config_cache_mtime is not None
    cfg.invalidate_config_cache()
    assert cfg._config_cache_mtime is None
    assert cfg._config_cache_data is None

    # Next read must re-parse (json.load is called)
    parse_count = {"n": 0}
    import config as config_mod

    original_load = json.load

    def counting_load(fp):
        parse_count["n"] += 1
        return original_load(fp)

    with patch.object(config_mod.json, "load", side_effect=counting_load):
        result = cfg.read_config()

    assert (
        parse_count["n"] == 1
    ), f"Expected 1 json.load after invalidation, got {parse_count['n']}"
    assert result["name"] == "CacheTest"


# ---------------------------------------------------------------------------
# 4. write_config() refreshes the cache
# ---------------------------------------------------------------------------


def test_write_config_refreshes_cache(tmp_path, monkeypatch):
    """After write_config(), the cache is warm so the next read_config() is a cache hit."""
    cfg = _make_config(tmp_path, monkeypatch)

    # Mutate the in-memory config and write it
    cfg.config["name"] = "PostWrite"
    cfg.write_config()

    # Cache should be updated by write_config
    assert cfg._config_cache_mtime is not None
    assert cfg._config_cache_data is not None

    # read_config() should return the written data without re-parsing
    parse_count = {"n": 0}
    import config as config_mod

    original_load = json.load

    def counting_load(fp):
        parse_count["n"] += 1
        return original_load(fp)

    with patch.object(config_mod.json, "load", side_effect=counting_load):
        result = cfg.read_config()

    assert (
        parse_count["n"] == 0
    ), "write_config() should refresh the cache so the next read is a hit"
    assert result["name"] == "PostWrite"


def test_read_modify_write_cycle(tmp_path, monkeypatch):
    """A complete read → modify → write_config() round-trip preserves correctness."""
    cfg = _make_config(tmp_path, monkeypatch)

    # Read, modify in memory, write, then read again
    data = cfg.read_config()
    assert data["name"] == "CacheTest"

    cfg.config["plugin_cycle_interval_seconds"] = 999
    cfg.write_config()

    result = cfg.read_config()
    assert result["plugin_cycle_interval_seconds"] == 999


# ---------------------------------------------------------------------------
# 5. Thread safety — concurrent reads
# ---------------------------------------------------------------------------


def test_concurrent_reads_are_thread_safe(tmp_path, monkeypatch):
    """Multiple threads calling read_config() concurrently must not corrupt state."""
    cfg = _make_config(tmp_path, monkeypatch)

    errors: list[Exception] = []
    results: list[dict] = []
    lock = threading.Lock()

    def reader():
        try:
            for _ in range(50):
                r = cfg.read_config()
                assert isinstance(r, dict)
                assert "name" in r
                with lock:
                    results.append(r)
        except Exception as exc:
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=reader) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert not errors, f"Concurrent read errors: {errors}"
    assert len(results) == 8 * 50
    for r in results:
        assert r["name"] == "CacheTest"


def test_concurrent_read_and_write_are_thread_safe(tmp_path, monkeypatch):
    """Concurrent reads and writes must not produce torn or corrupt state."""
    cfg = _make_config(tmp_path, monkeypatch)

    errors: list[Exception] = []
    stop_event = threading.Event()

    def reader():
        while not stop_event.is_set():
            try:
                r = cfg.read_config()
                assert isinstance(r, dict)
            except Exception as exc:
                with threading.Lock():
                    errors.append(exc)
                return

    def writer():
        for i in range(5):
            try:
                cfg.config["plugin_cycle_interval_seconds"] = 300 + i
                cfg.write_config()
                time.sleep(0.005)
            except Exception as exc:
                with threading.Lock():
                    errors.append(exc)
                return

    readers = [threading.Thread(target=reader) for _ in range(4)]
    writer_thread = threading.Thread(target=writer)

    for t in readers:
        t.start()
    writer_thread.start()
    writer_thread.join(timeout=10)
    stop_event.set()
    for t in readers:
        t.join(timeout=5)

    assert not errors, f"Concurrent read/write errors: {errors}"


# ---------------------------------------------------------------------------
# 6. OSError path — stat fails gracefully
# ---------------------------------------------------------------------------


def test_stat_failure_clears_cache_and_falls_back_to_full_read(tmp_path, monkeypatch):
    """If os.stat() raises OSError the cache is cleared and a full parse still succeeds.

    When stat() fails (e.g. transient FS glitch but the file is still readable),
    read_config() must:
      1. Clear the stale cache so we do not serve stale data.
      2. Fall through to the regular open() + parse + validate path.
    """
    cfg = _make_config(tmp_path, monkeypatch)
    assert cfg._config_cache_mtime is not None

    import config as config_mod

    parse_count = {"n": 0}
    original_load = json.load

    def counting_load(fp):
        parse_count["n"] += 1
        return original_load(fp)

    with (
        patch.object(config_mod.os, "stat", side_effect=OSError("simulated")),
        patch.object(config_mod.json, "load", side_effect=counting_load),
    ):
        result = cfg.read_config()

    # mtime is unknown (stat failed), so cache mtime should be None (won't hit cache next call)
    assert cfg._config_cache_mtime is None
    # But the parse should have succeeded (fell through to open())
    assert parse_count["n"] == 1
    assert isinstance(result, dict)
    assert result["name"] == "CacheTest"
