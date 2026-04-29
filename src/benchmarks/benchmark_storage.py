import json
import os
import random
import sqlite3
import time
from typing import Any, Protocol


class DeviceConfigLike(Protocol):
    BASE_DIR: str

    def get_config(self, key: str, default: Any = None) -> Any: ...


def _get_db_path(device_config: DeviceConfigLike) -> str:
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


def _is_enabled(device_config: DeviceConfigLike) -> bool:
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


def _should_record_event(
    device_config: DeviceConfigLike, refresh_event: dict[str, Any]
) -> bool:
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
    cur.execute("""
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
        """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS stage_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            refresh_id TEXT NOT NULL,
            ts REAL NOT NULL,
            stage TEXT NOT NULL,
            duration_ms INTEGER,
            extra_json TEXT
        )
        """)
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


_ALLOWED_TABLES = frozenset({"refresh_events", "stage_events"})
_ALLOWED_COLUMN_TYPES = frozenset({"TEXT", "INTEGER", "REAL", "BLOB", "NUMERIC"})
_IDENTIFIER_RE = __import__("re").compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_TABLE_INFO_QUERIES = {
    "refresh_events": "PRAGMA table_info(refresh_events)",
    "stage_events": "PRAGMA table_info(stage_events)",
}
_ALTER_COLUMN_QUERIES = {
    ("refresh_events", "instance", "TEXT"): (
        "ALTER TABLE refresh_events ADD COLUMN instance TEXT"
    ),
    ("refresh_events", "playlist", "TEXT"): (
        "ALTER TABLE refresh_events ADD COLUMN playlist TEXT"
    ),
    ("refresh_events", "used_cached", "INTEGER"): (
        "ALTER TABLE refresh_events ADD COLUMN used_cached INTEGER"
    ),
    ("refresh_events", "request_ms", "INTEGER"): (
        "ALTER TABLE refresh_events ADD COLUMN request_ms INTEGER"
    ),
    ("refresh_events", "generate_ms", "INTEGER"): (
        "ALTER TABLE refresh_events ADD COLUMN generate_ms INTEGER"
    ),
    ("refresh_events", "preprocess_ms", "INTEGER"): (
        "ALTER TABLE refresh_events ADD COLUMN preprocess_ms INTEGER"
    ),
    ("refresh_events", "display_ms", "INTEGER"): (
        "ALTER TABLE refresh_events ADD COLUMN display_ms INTEGER"
    ),
    ("refresh_events", "cpu_percent", "REAL"): (
        "ALTER TABLE refresh_events ADD COLUMN cpu_percent REAL"
    ),
    ("refresh_events", "memory_percent", "REAL"): (
        "ALTER TABLE refresh_events ADD COLUMN memory_percent REAL"
    ),
    ("refresh_events", "notes", "TEXT"): (
        "ALTER TABLE refresh_events ADD COLUMN notes TEXT"
    ),
    ("stage_events", "duration_ms", "INTEGER"): (
        "ALTER TABLE stage_events ADD COLUMN duration_ms INTEGER"
    ),
    ("stage_events", "extra_json", "TEXT"): (
        "ALTER TABLE stage_events ADD COLUMN extra_json TEXT"
    ),
}


def _validate_identifier(value: str, label: str) -> str:
    """Return *value* unchanged after confirming it is a safe SQL identifier.

    SQL identifiers (table/column names) cannot be bound via parameterised
    queries, so we validate against an explicit allow-list (tables) or a strict
    regex (columns/types) before interpolating into the statement.  Any value
    that fails validation raises ValueError so callers surface the bug at
    development time rather than silently executing unsafe SQL.
    """
    if not _IDENTIFIER_RE.match(value):
        raise ValueError(
            f"Unsafe SQL identifier for {label!r}: {value!r} "
            "(must match ^[A-Za-z_][A-Za-z0-9_]*$)"
        )
    return value


def _ensure_optional_columns(
    conn: sqlite3.Connection,
    table_name: str,
    expected_columns: dict[str, str],
) -> None:
    # table_name and column names are SQL identifiers that cannot be bound via
    # query parameters.  Validate against an allow-list / strict regex before
    # interpolating so that callers can never inject arbitrary SQL.
    if table_name not in _ALLOWED_TABLES:
        raise ValueError(f"Unknown benchmark table: {table_name!r}")
    safe_table = _validate_identifier(table_name, "table_name")
    table_info_query = _TABLE_INFO_QUERIES[safe_table]

    existing = {row[1] for row in conn.execute(table_info_query).fetchall()}
    for column_name, column_type in expected_columns.items():
        if column_name in existing:
            continue
        safe_col = _validate_identifier(column_name, "column_name")
        if column_type not in _ALLOWED_COLUMN_TYPES:
            raise ValueError(f"Unknown column type: {column_type!r}")
        try:
            alter_query = _ALTER_COLUMN_QUERIES[(safe_table, safe_col, column_type)]
        except KeyError as exc:
            raise ValueError(
                f"Unexpected benchmark column for {safe_table!r}: "
                f"{safe_col!r} {column_type!r}"
            ) from exc
        conn.execute(alter_query)


def save_refresh_event(
    device_config: DeviceConfigLike, refresh_event: dict[str, Any]
) -> None:
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
    device_config: DeviceConfigLike,
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
