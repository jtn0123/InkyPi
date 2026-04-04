import json
import os
import random
import sqlite3
import time
from typing import Any


def _get_db_path(device_config) -> str:
    # BASE_DIR is src/; fallback from __file__ (src/benchmarks/) goes up one level
    fallback = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    try:
        base_dir = getattr(device_config, "BASE_DIR", fallback) or fallback
    except Exception:
        base_dir = fallback
    project_root = os.path.abspath(os.path.join(base_dir, ".."))
    default_path = os.path.join(project_root, "runtime", "benchmarks.db")
    try:
        value = device_config.get_config("benchmarks_db_path", default=default_path)
        if not value:
            return default_path
        return str(value)
    except Exception:
        return default_path


def _is_enabled(device_config) -> bool:
    try:
        enabled = device_config.get_config("enable_benchmarks", default=True)
    except Exception:
        enabled = True
    if not enabled:
        return False
    # Skip entirely when running under pytest to avoid polluting metrics
    if os.getenv("PYTEST_CURRENT_TEST"):
        return False
    try:
        sample_rate = float(
            device_config.get_config("benchmark_sample_rate", default=1.0)
        )
    except Exception:
        sample_rate = 1.0
    sample_rate = max(0.0, min(1.0, sample_rate))
    return random.random() < sample_rate


def _should_record_event(device_config, refresh_event: dict[str, Any]) -> bool:
    if not _is_enabled(device_config):
        return False
    # Optional include/exclude plugin filters
    try:
        include_list = device_config.get_config(
            "benchmark_include_plugins", default=None
        )
    except Exception:
        include_list = None
    try:
        exclude_list = device_config.get_config(
            "benchmark_exclude_plugins", default=None
        )
    except Exception:
        exclude_list = None

    plugin_id = refresh_event.get("plugin_id")
    if (
        include_list
        and isinstance(include_list, list)
        and plugin_id not in include_list
    ):
        return False
    return not (
        exclude_list and isinstance(exclude_list, list) and plugin_id in exclude_list
    )


def _ensure_schema(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS refresh_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            refresh_id TEXT NOT NULL,
            ts REAL NOT NULL,
            plugin_id TEXT,
            instance TEXT,
            playlist TEXT,
            used_cached INTEGER,
            request_ms INTEGER,
            generate_ms INTEGER,
            preprocess_ms INTEGER,
            display_ms INTEGER,
            cpu_percent REAL,
            memory_percent REAL,
            notes TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS stage_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            refresh_id TEXT NOT NULL,
            ts REAL NOT NULL,
            stage TEXT NOT NULL,
            duration_ms INTEGER,
            extra_json TEXT
        )
        """
    )
    _ensure_optional_columns(
        conn,
        "refresh_events",
        {
            "instance": "TEXT",
            "playlist": "TEXT",
            "used_cached": "INTEGER",
            "request_ms": "INTEGER",
            "generate_ms": "INTEGER",
            "preprocess_ms": "INTEGER",
            "display_ms": "INTEGER",
            "cpu_percent": "REAL",
            "memory_percent": "REAL",
            "notes": "TEXT",
        },
    )
    _ensure_optional_columns(
        conn,
        "stage_events",
        {
            "duration_ms": "INTEGER",
            "extra_json": "TEXT",
        },
    )
    conn.commit()


def _ensure_optional_columns(
    conn: sqlite3.Connection,
    table_name: str,
    expected_columns: dict[str, str],
) -> None:
    existing = {
        row[1] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    }
    for column_name, column_type in expected_columns.items():
        if column_name in existing:
            continue
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")


def save_refresh_event(device_config, refresh_event: dict[str, Any]) -> None:
    """Persist a single refresh event. Best-effort; never raises upstream.

    Expected keys in refresh_event: refresh_id, plugin_id, instance, playlist,
    used_cached, request_ms, generate_ms, preprocess_ms, display_ms,
    cpu_percent, memory_percent, notes
    """
    try:
        if not _should_record_event(device_config, refresh_event):
            return
        db_path = _get_db_path(device_config)
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        conn = sqlite3.connect(db_path)
        try:
            _ensure_schema(conn)
            cur = conn.cursor()
            # Resolve timestamp safely
            ts_raw = refresh_event.get("ts")
            try:
                ts_value = float(ts_raw) if ts_raw is not None else time.time()
            except Exception:
                ts_value = time.time()

            cur.execute(
                """
                INSERT INTO refresh_events (
                    refresh_id, ts, plugin_id, instance, playlist, used_cached,
                    request_ms, generate_ms, preprocess_ms, display_ms,
                    cpu_percent, memory_percent, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    refresh_event.get("refresh_id"),
                    ts_value,
                    refresh_event.get("plugin_id"),
                    refresh_event.get("instance"),
                    refresh_event.get("playlist"),
                    1 if refresh_event.get("used_cached") else 0,
                    refresh_event.get("request_ms"),
                    refresh_event.get("generate_ms"),
                    refresh_event.get("preprocess_ms"),
                    refresh_event.get("display_ms"),
                    refresh_event.get("cpu_percent"),
                    refresh_event.get("memory_percent"),
                    refresh_event.get("notes"),
                ),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        # Swallow all exceptions to avoid impacting production path
        pass


def save_stage_event(
    device_config,
    refresh_id: str,
    stage: str,
    duration_ms: int | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Persist a stage event tied to a refresh id. Best-effort; never raises upstream."""
    try:
        if not _is_enabled(device_config):
            return
        db_path = _get_db_path(device_config)
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        conn = sqlite3.connect(db_path)
        try:
            _ensure_schema(conn)
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO stage_events (refresh_id, ts, stage, duration_ms, extra_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    refresh_id,
                    float(time.time()),
                    stage,
                    int(duration_ms) if duration_ms is not None else None,
                    (
                        json.dumps(extra, ensure_ascii=False)
                        if extra is not None
                        else None
                    ),
                ),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass
