"""Benchmark API route handlers."""

import sqlite3

from flask import Response, request

import blueprints.settings as _mod
from utils.http_utils import json_error, json_internal_error, json_success
from utils.messages import BENCHMARKS_API_DISABLED_ERROR


def _clamp_benchmark_limit(raw_limit: str | None) -> int:
    try:
        return max(1, min(200, int(raw_limit or "50")))
    except (TypeError, ValueError):
        return 50


def _parse_benchmark_cursor(raw_cursor: str | None) -> int | None:
    if not raw_cursor:
        return None
    try:
        cursor = int(raw_cursor)
    except (TypeError, ValueError):
        return None
    return cursor if cursor > 0 else None


@_mod.settings_bp.route("/api/benchmarks/summary", methods=["GET"])  # type: ignore
def benchmarks_summary() -> tuple[object, int] | Response:
    if not _mod._benchmarks_enabled():
        return json_error(BENCHMARKS_API_DISABLED_ERROR, status=404)
    conn = None
    try:
        since = _mod._window_since_seconds(request.args.get("window", "24h"))
        conn = sqlite3.connect(_mod._get_bench_db_path())
        conn.row_factory = sqlite3.Row
        _mod._ensure_bench_schema(conn)
        rows = conn.execute(
            """
            SELECT request_ms, generate_ms, preprocess_ms, display_ms
            FROM refresh_events
            WHERE ts >= ?
            ORDER BY ts DESC
            """,
            (since,),
        ).fetchall()
        req = [int(r["request_ms"]) for r in rows if r["request_ms"] is not None]
        gen = [int(r["generate_ms"]) for r in rows if r["generate_ms"] is not None]
        pre = [int(r["preprocess_ms"]) for r in rows if r["preprocess_ms"] is not None]
        dsp = [int(r["display_ms"]) for r in rows if r["display_ms"] is not None]
        return json_success(
            count=len(rows),
            summary={
                "request_ms": {
                    "p50": _mod._pct(req, 0.5),
                    "p95": _mod._pct(req, 0.95),
                },
                "generate_ms": {
                    "p50": _mod._pct(gen, 0.5),
                    "p95": _mod._pct(gen, 0.95),
                },
                "preprocess_ms": {
                    "p50": _mod._pct(pre, 0.5),
                    "p95": _mod._pct(pre, 0.95),
                },
                "display_ms": {
                    "p50": _mod._pct(dsp, 0.5),
                    "p95": _mod._pct(dsp, 0.95),
                },
            },
        )
    except Exception as e:
        return json_internal_error("benchmarks summary", details={"error": str(e)})
    finally:
        if conn:
            conn.close()


@_mod.settings_bp.route("/api/benchmarks/refreshes", methods=["GET"])  # type: ignore
def benchmarks_refreshes() -> tuple[object, int] | Response:
    if not _mod._benchmarks_enabled():
        return json_error(BENCHMARKS_API_DISABLED_ERROR, status=404)
    conn = None
    try:
        limit = _clamp_benchmark_limit(request.args.get("limit"))
        cursor = _parse_benchmark_cursor(request.args.get("cursor"))
        since = _mod._window_since_seconds(request.args.get("window", "24h"))
        conn = sqlite3.connect(_mod._get_bench_db_path())
        conn.row_factory = sqlite3.Row
        _mod._ensure_bench_schema(conn)
        if cursor:
            rows = conn.execute(
                """
                SELECT id, ts, refresh_id, plugin_id, instance, playlist, used_cached,
                       request_ms, generate_ms, preprocess_ms, display_ms
                FROM refresh_events
                WHERE ts >= ? AND id < ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (since, cursor, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT id, ts, refresh_id, plugin_id, instance, playlist, used_cached,
                       request_ms, generate_ms, preprocess_ms, display_ms
                FROM refresh_events
                WHERE ts >= ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (since, limit),
            ).fetchall()
        next_cursor = str(rows[-1]["id"]) if rows else None
        return json_success(
            items=[dict(r) for r in rows],
            next_cursor=next_cursor,
        )
    except Exception as e:
        return json_internal_error("benchmarks refreshes", details={"error": str(e)})
    finally:
        if conn:
            conn.close()


@_mod.settings_bp.route("/api/benchmarks/plugins", methods=["GET"])  # type: ignore
def benchmarks_plugins() -> tuple[object, int] | Response:
    if not _mod._benchmarks_enabled():
        return json_error(BENCHMARKS_API_DISABLED_ERROR, status=404)
    conn = None
    try:
        since = _mod._window_since_seconds(request.args.get("window", "24h"))
        conn = sqlite3.connect(_mod._get_bench_db_path())
        conn.row_factory = sqlite3.Row
        _mod._ensure_bench_schema(conn)
        rows = conn.execute(
            """
            SELECT plugin_id,
                   COUNT(*) AS runs,
                   AVG(request_ms) AS request_avg,
                   AVG(generate_ms) AS generate_avg,
                   AVG(display_ms) AS display_avg
            FROM refresh_events
            WHERE ts >= ?
            GROUP BY plugin_id
            ORDER BY runs DESC
            """,
            (since,),
        ).fetchall()
        items = [
            {
                "plugin_id": r["plugin_id"],
                "runs": int(r["runs"] or 0),
                "request_avg": (
                    int(round(r["request_avg"]))
                    if r["request_avg"] is not None
                    else None
                ),
                "generate_avg": (
                    int(round(r["generate_avg"]))
                    if r["generate_avg"] is not None
                    else None
                ),
                "display_avg": (
                    int(round(r["display_avg"]))
                    if r["display_avg"] is not None
                    else None
                ),
            }
            for r in rows
        ]
        return json_success(items=items)
    except Exception as e:
        return json_internal_error("benchmarks plugins", details={"error": str(e)})
    finally:
        if conn:
            conn.close()


@_mod.settings_bp.route("/api/benchmarks/stages", methods=["GET"])  # type: ignore
def benchmarks_stages() -> tuple[object, int] | Response:
    if not _mod._benchmarks_enabled():
        return json_error(BENCHMARKS_API_DISABLED_ERROR, status=404)
    refresh_id = request.args.get("refresh_id")
    if not refresh_id:
        return json_error(
            "refresh_id is required",
            status=422,
            code="validation_error",
            details={"field": "refresh_id"},
        )
    conn = None
    try:
        conn = sqlite3.connect(_mod._get_bench_db_path())
        conn.row_factory = sqlite3.Row
        _mod._ensure_bench_schema(conn)
        rows = conn.execute(
            """
            SELECT id, ts, stage, duration_ms, extra_json
            FROM stage_events
            WHERE refresh_id = ?
            ORDER BY id ASC
            """,
            (refresh_id,),
        ).fetchall()
        return json_success(items=[dict(r) for r in rows])
    except Exception as e:
        return json_internal_error("benchmarks stages", details={"error": str(e)})
    finally:
        if conn:
            conn.close()
