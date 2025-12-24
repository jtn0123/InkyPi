"""Tests for benchmarks/benchmark_storage.py module."""

import os
import sqlite3
import time

import pytest


class MockDeviceConfig:
    """Mock device config for testing benchmark storage."""

    def __init__(self, config=None, base_dir=None):
        self._config = config or {}
        self.BASE_DIR = base_dir or os.path.dirname(__file__)

    def get_config(self, key, default=None):
        return self._config.get(key, default)


# --- _get_db_path tests ---


def test_get_db_path_defaults(tmp_path, monkeypatch):
    """Verify default path uses BASE_DIR when no config specified."""
    from benchmarks.benchmark_storage import _get_db_path

    config = MockDeviceConfig(base_dir=str(tmp_path))
    result = _get_db_path(config)
    assert result == os.path.join(str(tmp_path), "benchmarks.db")


def test_get_db_path_from_config(tmp_path):
    """Custom path from config is used when specified."""
    from benchmarks.benchmark_storage import _get_db_path

    custom_path = str(tmp_path / "custom" / "metrics.db")
    config = MockDeviceConfig(config={"benchmarks_db_path": custom_path})
    result = _get_db_path(config)
    assert result == custom_path


def test_get_db_path_handles_empty_config_value(tmp_path):
    """Empty config value falls back to default path."""
    from benchmarks.benchmark_storage import _get_db_path

    config = MockDeviceConfig(
        config={"benchmarks_db_path": ""}, base_dir=str(tmp_path)
    )
    result = _get_db_path(config)
    assert result == os.path.join(str(tmp_path), "benchmarks.db")


def test_get_db_path_handles_exception():
    """Handles exception when get_config fails."""
    from benchmarks.benchmark_storage import _get_db_path

    class BrokenConfig:
        BASE_DIR = "/tmp"

        def get_config(self, key, default=None):
            raise RuntimeError("Config error")

    result = _get_db_path(BrokenConfig())
    assert result.endswith("benchmarks.db")


# --- _is_enabled tests ---


def test_is_enabled_respects_config_false(monkeypatch):
    """Benchmarks disabled when enable_benchmarks is False."""
    from benchmarks.benchmark_storage import _is_enabled

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    config = MockDeviceConfig(config={"enable_benchmarks": False})
    assert _is_enabled(config) is False


def test_is_enabled_respects_config_true(monkeypatch):
    """Benchmarks enabled when enable_benchmarks is True."""
    from benchmarks.benchmark_storage import _is_enabled

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    config = MockDeviceConfig(config={"enable_benchmarks": True})
    # With sample_rate=1.0 (default), should always be enabled
    assert _is_enabled(config) is True


def test_is_enabled_skips_pytest(monkeypatch):
    """Benchmarks disabled when PYTEST_CURRENT_TEST is set."""
    from benchmarks.benchmark_storage import _is_enabled

    monkeypatch.setenv("PYTEST_CURRENT_TEST", "test_something.py::test_func")
    config = MockDeviceConfig(config={"enable_benchmarks": True})
    assert _is_enabled(config) is False


def test_sample_rate_filtering_zero(monkeypatch):
    """Sample rate of 0 always returns False."""
    from benchmarks.benchmark_storage import _is_enabled

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    config = MockDeviceConfig(
        config={"enable_benchmarks": True, "benchmark_sample_rate": 0.0}
    )
    # With sample_rate=0, should never be enabled
    for _ in range(10):
        assert _is_enabled(config) is False


def test_sample_rate_filtering_one(monkeypatch):
    """Sample rate of 1.0 always returns True."""
    from benchmarks.benchmark_storage import _is_enabled

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    config = MockDeviceConfig(
        config={"enable_benchmarks": True, "benchmark_sample_rate": 1.0}
    )
    # With sample_rate=1.0, should always be enabled
    for _ in range(10):
        assert _is_enabled(config) is True


def test_sample_rate_clamped_to_valid_range(monkeypatch):
    """Sample rate values outside 0-1 are clamped."""
    from benchmarks.benchmark_storage import _is_enabled

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    # > 1.0 should be clamped to 1.0 (always enabled)
    config = MockDeviceConfig(
        config={"enable_benchmarks": True, "benchmark_sample_rate": 2.0}
    )
    assert _is_enabled(config) is True

    # < 0 should be clamped to 0 (never enabled)
    config = MockDeviceConfig(
        config={"enable_benchmarks": True, "benchmark_sample_rate": -1.0}
    )
    assert _is_enabled(config) is False


# --- _should_record_event tests ---


def test_should_record_event_include_filter(monkeypatch):
    """Include filter only allows specified plugins."""
    from benchmarks.benchmark_storage import _should_record_event

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    config = MockDeviceConfig(
        config={
            "enable_benchmarks": True,
            "benchmark_include_plugins": ["weather", "clock"],
        }
    )

    assert _should_record_event(config, {"plugin_id": "weather"}) is True
    assert _should_record_event(config, {"plugin_id": "clock"}) is True
    assert _should_record_event(config, {"plugin_id": "calendar"}) is False


def test_should_record_event_exclude_filter(monkeypatch):
    """Exclude filter blocks specified plugins."""
    from benchmarks.benchmark_storage import _should_record_event

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    config = MockDeviceConfig(
        config={
            "enable_benchmarks": True,
            "benchmark_exclude_plugins": ["slow_plugin"],
        }
    )

    assert _should_record_event(config, {"plugin_id": "weather"}) is True
    assert _should_record_event(config, {"plugin_id": "slow_plugin"}) is False


def test_should_record_event_disabled(monkeypatch):
    """Returns False when benchmarks disabled."""
    from benchmarks.benchmark_storage import _should_record_event

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    config = MockDeviceConfig(config={"enable_benchmarks": False})
    assert _should_record_event(config, {"plugin_id": "weather"}) is False


# --- save_refresh_event tests ---


def test_save_refresh_event_creates_db(tmp_path, monkeypatch):
    """Database file is created on first write."""
    from benchmarks.benchmark_storage import save_refresh_event

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    db_path = str(tmp_path / "new_dir" / "test.db")
    config = MockDeviceConfig(
        config={"enable_benchmarks": True, "benchmarks_db_path": db_path}
    )

    event = {
        "refresh_id": "test-123",
        "plugin_id": "weather",
        "instance": "main",
        "playlist": "Default",
        "used_cached": False,
        "request_ms": 100,
        "generate_ms": 200,
        "preprocess_ms": 50,
        "display_ms": 150,
    }

    save_refresh_event(config, event)

    assert os.path.exists(db_path)


def test_save_refresh_event_schema(tmp_path, monkeypatch):
    """Verify table structure is correct."""
    from benchmarks.benchmark_storage import save_refresh_event

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    db_path = str(tmp_path / "test.db")
    config = MockDeviceConfig(
        config={"enable_benchmarks": True, "benchmarks_db_path": db_path}
    )

    save_refresh_event(config, {"refresh_id": "test-1", "plugin_id": "clock"})

    conn = sqlite3.connect(db_path)
    cursor = conn.execute("PRAGMA table_info(refresh_events)")
    columns = {row[1] for row in cursor.fetchall()}
    conn.close()

    expected_columns = {
        "id",
        "refresh_id",
        "ts",
        "plugin_id",
        "instance",
        "playlist",
        "used_cached",
        "request_ms",
        "generate_ms",
        "preprocess_ms",
        "display_ms",
        "cpu_percent",
        "memory_percent",
        "notes",
    }
    assert columns == expected_columns


def test_save_refresh_event_data_integrity(tmp_path, monkeypatch):
    """Round-trip data verification."""
    from benchmarks.benchmark_storage import save_refresh_event

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    db_path = str(tmp_path / "test.db")
    config = MockDeviceConfig(
        config={"enable_benchmarks": True, "benchmarks_db_path": db_path}
    )

    event = {
        "refresh_id": "integrity-test",
        "plugin_id": "weather",
        "instance": "main_instance",
        "playlist": "Morning",
        "used_cached": True,
        "request_ms": 123,
        "generate_ms": 456,
        "preprocess_ms": 78,
        "display_ms": 90,
        "cpu_percent": 45.5,
        "memory_percent": 62.3,
        "notes": "test note",
        "ts": 1700000000.0,
    }

    save_refresh_event(config, event)

    conn = sqlite3.connect(db_path)
    cursor = conn.execute("SELECT * FROM refresh_events WHERE refresh_id = ?", ("integrity-test",))
    row = cursor.fetchone()
    conn.close()

    assert row is not None
    # id, refresh_id, ts, plugin_id, instance, playlist, used_cached, ...
    assert row[1] == "integrity-test"
    assert row[2] == 1700000000.0
    assert row[3] == "weather"
    assert row[4] == "main_instance"
    assert row[5] == "Morning"
    assert row[6] == 1  # used_cached = True
    assert row[7] == 123  # request_ms
    assert row[8] == 456  # generate_ms
    assert row[9] == 78  # preprocess_ms
    assert row[10] == 90  # display_ms
    assert row[11] == 45.5  # cpu_percent
    assert row[12] == 62.3  # memory_percent
    assert row[13] == "test note"


def test_save_refresh_event_uses_current_time_if_no_ts(tmp_path, monkeypatch):
    """Uses current time when ts not provided."""
    from benchmarks.benchmark_storage import save_refresh_event

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    db_path = str(tmp_path / "test.db")
    config = MockDeviceConfig(
        config={"enable_benchmarks": True, "benchmarks_db_path": db_path}
    )

    before = time.time()
    save_refresh_event(config, {"refresh_id": "no-ts", "plugin_id": "clock"})
    after = time.time()

    conn = sqlite3.connect(db_path)
    cursor = conn.execute("SELECT ts FROM refresh_events WHERE refresh_id = ?", ("no-ts",))
    row = cursor.fetchone()
    conn.close()

    assert row is not None
    assert before <= row[0] <= after


# --- save_stage_event tests ---


def test_save_stage_event(tmp_path, monkeypatch):
    """Stage events are persisted correctly."""
    from benchmarks.benchmark_storage import save_stage_event

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    db_path = str(tmp_path / "test.db")
    config = MockDeviceConfig(
        config={"enable_benchmarks": True, "benchmarks_db_path": db_path}
    )

    save_stage_event(
        config,
        refresh_id="stage-test",
        stage="generate",
        duration_ms=250,
        extra={"key": "value"},
    )

    conn = sqlite3.connect(db_path)
    cursor = conn.execute("SELECT * FROM stage_events WHERE refresh_id = ?", ("stage-test",))
    row = cursor.fetchone()
    conn.close()

    assert row is not None
    # id, refresh_id, ts, stage, duration_ms, extra_json
    assert row[1] == "stage-test"
    assert row[3] == "generate"
    assert row[4] == 250
    assert '"key": "value"' in row[5]


def test_save_stage_event_without_optional_fields(tmp_path, monkeypatch):
    """Stage events work without duration_ms and extra."""
    from benchmarks.benchmark_storage import save_stage_event

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    db_path = str(tmp_path / "test.db")
    config = MockDeviceConfig(
        config={"enable_benchmarks": True, "benchmarks_db_path": db_path}
    )

    save_stage_event(config, refresh_id="minimal-stage", stage="start")

    conn = sqlite3.connect(db_path)
    cursor = conn.execute("SELECT * FROM stage_events WHERE refresh_id = ?", ("minimal-stage",))
    row = cursor.fetchone()
    conn.close()

    assert row is not None
    assert row[1] == "minimal-stage"
    assert row[3] == "start"
    assert row[4] is None  # duration_ms
    assert row[5] is None  # extra_json


# --- Exception handling tests ---


def test_save_silently_fails_on_error(monkeypatch):
    """save_refresh_event swallows exceptions."""
    from benchmarks.benchmark_storage import save_refresh_event

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    class BadConfig:
        BASE_DIR = "/nonexistent"

        def get_config(self, key, default=None):
            if key == "enable_benchmarks":
                return True
            if key == "benchmarks_db_path":
                return "/root/readonly/nope.db"  # Unwritable path
            return default

    # Should not raise, even with bad path
    save_refresh_event(BadConfig(), {"refresh_id": "fail-test", "plugin_id": "test"})


def test_save_stage_event_silently_fails_on_error(monkeypatch):
    """save_stage_event swallows exceptions."""
    from benchmarks.benchmark_storage import save_stage_event

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    class BadConfig:
        BASE_DIR = "/nonexistent"

        def get_config(self, key, default=None):
            if key == "enable_benchmarks":
                return True
            if key == "benchmarks_db_path":
                return "/root/readonly/nope.db"
            return default

    # Should not raise
    save_stage_event(BadConfig(), refresh_id="fail", stage="test")
