"""The benchmark database checks its schema once, is indexed, and is pruned.

Every saved event used to re-run the schema check (two ``PRAGMA table_info``
scans plus the CREATE statements), the route queries scanned whole tables,
and nothing ever deleted a row, so the database grew for as long as the
device ran.
"""

from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path
from typing import Any

import pytest

import benchmarks.benchmark_storage as storage


class _Config:
    def __init__(self, db_path: str) -> None:
        self.BASE_DIR = os.path.dirname(db_path)
        self._config = {"enable_benchmarks": True, "benchmarks_db_path": db_path}

    def get_config(self, key: str, default: Any = None) -> Any:
        return self._config.get(key, default)


@pytest.fixture
def config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _Config:
    # Benchmarks are switched off under pytest (and pytest resets
    # PYTEST_CURRENT_TEST for each phase); these tests are about saving.
    monkeypatch.setattr(storage, "_is_enabled", lambda _config: True)
    return _Config(str(tmp_path / "runtime" / "benchmarks.db"))


def _db(config: _Config) -> str:
    return str(config.get_config("benchmarks_db_path"))


def test_schema_is_checked_once_per_database(
    config: _Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []
    real = storage._ensure_schema

    def _counting(conn: sqlite3.Connection) -> None:
        calls.append(1)
        real(conn)

    monkeypatch.setattr(storage, "_ensure_schema", _counting)

    for n in range(3):
        storage.save_refresh_event(config, {"refresh_id": f"r{n}", "plugin_id": "p"})
        storage.save_stage_event(config, f"r{n}", "generate_image", 10)
    assert len(calls) == 1

    # A deleted and recreated database is set up again, not written blind.
    os.remove(_db(config))
    storage.save_refresh_event(config, {"refresh_id": "again", "plugin_id": "p"})
    assert len(calls) == 2
    with sqlite3.connect(_db(config)) as conn:
        assert conn.execute("SELECT refresh_id FROM refresh_events").fetchall() == [
            ("again",)
        ]


def test_route_queries_use_indexes(config: _Config) -> None:
    storage.save_refresh_event(config, {"refresh_id": "r1", "plugin_id": "p"})
    storage.save_stage_event(config, "r1", "generate_image", 10)

    with sqlite3.connect(_db(config)) as conn:
        by_ts = " ".join(
            str(row[-1])
            for row in conn.execute(
                "EXPLAIN QUERY PLAN SELECT request_ms FROM refresh_events "
                "WHERE ts >= ? ORDER BY ts DESC",
                (0,),
            )
        )
        by_refresh = " ".join(
            str(row[-1])
            for row in conn.execute(
                "EXPLAIN QUERY PLAN SELECT id FROM stage_events "
                "WHERE refresh_id = ? ORDER BY id ASC",
                ("r1",),
            )
        )
    assert "idx_refresh_events_ts" in by_ts
    assert "idx_stage_events_refresh_id" in by_refresh


def test_prune_deletes_only_rows_past_the_retention(config: _Config) -> None:
    now = time.time()
    day = 86400
    storage.save_refresh_event(
        config, {"refresh_id": "old", "plugin_id": "p", "ts": now - 40 * day}
    )
    storage.save_refresh_event(
        config, {"refresh_id": "new", "plugin_id": "p", "ts": now - 2 * day}
    )
    storage.save_stage_event(config, "new", "generate_image", 10)
    with sqlite3.connect(_db(config)) as conn:
        conn.execute(
            "INSERT INTO stage_events (refresh_id, ts, stage) VALUES (?, ?, ?)",
            ("old", now - 40 * day, "generate_image"),
        )

    assert storage.prune_benchmarks(config, now=now) == 2

    with sqlite3.connect(_db(config)) as conn:
        assert conn.execute("SELECT refresh_id FROM refresh_events").fetchall() == [
            ("new",)
        ]
        assert conn.execute("SELECT refresh_id FROM stage_events").fetchall() == [
            ("new",)
        ]
    assert storage.BENCHMARK_RETENTION_DAYS == 30


def test_prune_without_a_database_creates_nothing(config: _Config) -> None:
    assert storage.prune_benchmarks(config) == 0
    assert not os.path.exists(_db(config))


def test_housekeeper_prunes_every_n_ticks_and_never_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from refresh_task.housekeeping import RefreshHousekeeper

    calls: list[object] = []

    def _prune(device_config: object) -> int:
        calls.append(device_config)
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(storage, "prune_benchmarks", _prune)
    device_config: Any = object()
    housekeeper = RefreshHousekeeper(device_config, display_manager=None)  # type: ignore[arg-type]

    for tick in range(1, 21):
        housekeeper.maybe_prune_benchmarks(tick_count=tick, cleanup_interval_ticks=10)

    assert calls == [device_config, device_config]


def test_refresh_loop_runs_the_prune_with_history_cleanup(
    device_config_dev: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from display.display_manager import DisplayManager
    from refresh_task import RefreshTask

    task = RefreshTask(device_config_dev, DisplayManager(device_config_dev))
    seen: list[tuple[int, int]] = []
    monkeypatch.setattr(
        task.housekeeper,
        "maybe_prune_benchmarks",
        lambda *, tick_count, cleanup_interval_ticks: seen.append(
            (tick_count, cleanup_interval_ticks)
        ),
    )
    task._tick_count = 10

    task._maybe_run_history_cleanup()

    assert seen == [(10, task._CLEANUP_INTERVAL_TICKS)]
