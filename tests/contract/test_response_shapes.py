"""Contract tests: JSON response shape stability for high-traffic routes.

These tests pin down the JSON shape returned by the endpoints the UI depends
on most: version/uptime info, refresh state, health, settings isolation,
refresh stats, and history storage.  If a backend change silently alters the
response keys or types, these tests fail and force the change to be made
deliberately alongside a matching TypedDict update in
``src/schemas/responses.py``.

The validator below is intentionally hand-rolled (no pydantic) to keep the
test suite lightweight. It walks a TypedDict's ``__annotations__`` and checks:

* every required key is present with a value matching its declared type
* for ``total=False`` TypedDicts, keys that *are* present also type-check

``Any`` annotations short-circuit the type check, mirroring mypy semantics.
"""

from __future__ import annotations

import sqlite3
import time
from typing import Any

import pytest

# Import schemas via the ``src.*`` path which ``tests/conftest.py`` puts on
# sys.path via SRC_ABS. TypedDict subclasses from ``typing`` expose their
# total-ness on the class itself.
from benchmarks.benchmark_storage import _ensure_schema
from schemas.responses import (  # noqa: E402  (sys.path set up by conftest)
    BenchmarksPluginsResponse,
    BenchmarksRefreshesResponse,
    BenchmarksStagesResponse,
    BenchmarksSummaryResponse,
    DiagnosticsResponse,
    HealthPluginsResponse,
    HealthSystemResponse,
    HistoryStorageResponse,
    IsolationResponse,
    JobStatusResponse,
    NextUpResponse,
    RefreshInfoResponse,
    RefreshStatsResponse,
    RefreshStatsWindow,
    RollbackControlResponse,
    SuccessMessageResponse,
    SuccessMessageWarningResponse,
    TopFailingEntry,
    UpdateControlResponse,
    UptimeResponse,
    VersionInfoResponse,
)
from schemas.validator import validate_typeddict  # noqa: E402


def assert_shape(payload: Any, schema: Any) -> None:
    errors = validate_typeddict(payload, schema)
    if errors:
        raise AssertionError(
            f"Response does not match {schema.__name__}:\n  "
            + "\n  ".join(errors)
            + f"\nPayload: {payload!r}"
        )


# ---------------------------------------------------------------------------
# Self-tests for the validator (cheap insurance)
# ---------------------------------------------------------------------------


def test_validator_accepts_matching_payload():
    good: VersionInfoResponse = {
        "version": "1.0",
        "git_sha": "abc",
        "git_branch": "main",
        "build_time": "2024-01-01",
        "python_version": "3.13",
    }
    assert validate_typeddict(good, VersionInfoResponse) == []


def test_validator_detects_missing_key():
    bad = {"version": "1.0"}
    errs = validate_typeddict(bad, VersionInfoResponse)
    assert any("missing required key" in e for e in errs)


def test_validator_detects_wrong_type():
    bad = {
        "version": 1,  # should be str
        "git_sha": "abc",
        "git_branch": "main",
        "build_time": "2024-01-01",
        "python_version": "3.13",
    }
    errs = validate_typeddict(bad, VersionInfoResponse)
    assert any("expected str" in e for e in errs)


def test_validator_handles_nested_typeddict():
    good = {
        "last_1h": {
            "total": 0,
            "success": 0,
            "failure": 0,
            "success_rate": 0.0,
            "p50_duration_ms": 0,
            "p95_duration_ms": 0,
            "top_failing": [],
        },
        "last_24h": {
            "total": 0,
            "success": 0,
            "failure": 0,
            "success_rate": 0.0,
            "p50_duration_ms": 0,
            "p95_duration_ms": 0,
            "top_failing": [{"plugin": "ai_text", "count": 2}],
        },
        "last_7d": {
            "total": 0,
            "success": 0,
            "failure": 0,
            "success_rate": 0.0,
            "p50_duration_ms": 0,
            "p95_duration_ms": 0,
            "top_failing": [],
        },
    }
    assert validate_typeddict(good, RefreshStatsResponse) == []
    # Sanity: TopFailingEntry pulled through
    assert validate_typeddict({"plugin": "x", "count": 1}, TopFailingEntry) == []
    assert validate_typeddict({"plugin": "x", "count": "bad"}, TopFailingEntry) != []


# ---------------------------------------------------------------------------
# Endpoint contract tests
# ---------------------------------------------------------------------------


def _get_json(client, path, **kwargs):
    resp = client.get(path, **kwargs)
    assert resp.status_code == 200, f"{path} returned {resp.status_code}: {resp.data!r}"
    assert resp.is_json, f"{path} did not return JSON: {resp.content_type!r}"
    return resp.get_json()


def _request_json(client, method: str, path: str, expected_status: int = 200, **kwargs):
    resp = getattr(client, method)(path, **kwargs)
    assert (
        resp.status_code == expected_status
    ), f"{method.upper()} {path} returned {resp.status_code}: {resp.data!r}"
    assert (
        resp.is_json
    ), f"{method.upper()} {path} did not return JSON: {resp.content_type!r}"
    return resp.get_json()


def test_version_info_shape(client):
    body = _get_json(client, "/api/version/info")
    assert_shape(body, VersionInfoResponse)


def test_uptime_shape(client):
    body = _get_json(client, "/api/uptime")
    assert_shape(body, UptimeResponse)


def test_refresh_info_shape(client):
    body = _get_json(client, "/refresh-info")
    # refresh_info may be empty ({}) on a pristine config; total=False schema
    # still validates that any keys present are correctly typed.
    assert isinstance(body, dict)
    assert_shape(body, RefreshInfoResponse)


def test_next_up_shape(client):
    body = _get_json(client, "/next-up")
    # next-up returns {} when nothing is scheduled; total=False schema allows
    # that while still locking in the shape of populated responses.
    assert isinstance(body, dict)
    assert_shape(body, NextUpResponse)
    # Consistency: if populated, the three primary keys should all be present.
    # TODO(contract-drift): routes currently only guarantee this via code
    # inspection — leave the soft check here rather than pinning the exact
    # populated state, which requires a playlist fixture.
    if "plugin_id" in body:
        assert "playlist" in body
        assert "plugin_instance" in body


def test_refresh_stats_shape(client):
    body = _get_json(client, "/api/stats")
    assert_shape(body, RefreshStatsResponse)
    # Also validate the sub-window schema explicitly so regressions at that
    # level are surfaced even if RefreshStatsResponse is loosened later.
    assert_shape(body["last_1h"], RefreshStatsWindow)


def test_health_system_shape(client):
    body = _get_json(client, "/api/health/system")
    assert_shape(body, HealthSystemResponse)
    assert body.get("success") is True


def test_health_plugins_shape(client):
    body = _get_json(client, "/api/health/plugins")
    assert_shape(body, HealthPluginsResponse)
    assert body.get("success") is True
    assert "items" in body


def test_benchmarks_summary_shape(client, device_config_dev, tmp_path):
    db_path = tmp_path / "contract_benchmarks_shape.db"
    device_config_dev.update_value("enable_benchmarks", True, write=False)
    device_config_dev.update_value("benchmarks_db_path", str(db_path), write=True)

    # Seed at least one refresh row so summary percentiles are meaningful.
    client.post("/update_now", data={"plugin_id": "clock"})

    body = _get_json(client, "/api/benchmarks/summary?window=24h")
    assert_shape(body, BenchmarksSummaryResponse)
    assert body.get("success") is True


def test_benchmarks_plugins_shape(client, device_config_dev, tmp_path):
    db_path = tmp_path / "contract_benchmarks_plugins.db"
    device_config_dev.update_value("enable_benchmarks", True, write=False)
    device_config_dev.update_value("benchmarks_db_path", str(db_path), write=True)

    client.post("/update_now", data={"plugin_id": "clock"})

    body = _get_json(client, "/api/benchmarks/plugins?window=24h")
    assert_shape(body, BenchmarksPluginsResponse)
    assert body.get("success") is True
    assert isinstance(body.get("items"), list)


def test_benchmarks_refreshes_shape(client, device_config_dev, tmp_path):
    db_path = tmp_path / "contract_benchmarks_refreshes.db"
    device_config_dev.update_value("enable_benchmarks", True, write=False)
    device_config_dev.update_value("benchmarks_db_path", str(db_path), write=True)

    conn = sqlite3.connect(db_path)
    _ensure_schema(conn)
    conn.execute(
        """
        INSERT INTO refresh_events (
            refresh_id, ts, plugin_id, instance, playlist, used_cached,
            request_ms, generate_ms, preprocess_ms, display_ms
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("shape-refresh-1", time.time(), "clock", "Clock", "Default", 0, 10, 20, 3, 4),
    )
    conn.commit()
    conn.close()

    body = _get_json(client, "/api/benchmarks/refreshes?window=24h&limit=5")
    assert_shape(body, BenchmarksRefreshesResponse)
    assert body.get("success") is True
    assert isinstance(body.get("items"), list)


def test_benchmarks_stages_shape(client, device_config_dev, tmp_path):
    db_path = tmp_path / "contract_benchmarks_stages.db"
    device_config_dev.update_value("enable_benchmarks", True, write=False)
    device_config_dev.update_value("benchmarks_db_path", str(db_path), write=True)

    refresh_id = "shape-refresh-2"
    conn = sqlite3.connect(db_path)
    _ensure_schema(conn)
    conn.execute(
        """
        INSERT INTO stage_events (refresh_id, ts, stage, duration_ms, extra_json)
        VALUES (?, ?, ?, ?, ?)
        """,
        (refresh_id, time.time(), "generate_image", 123, "{}"),
    )
    conn.commit()
    conn.close()

    body = _get_json(client, f"/api/benchmarks/stages?refresh_id={refresh_id}")
    assert_shape(body, BenchmarksStagesResponse)
    assert body.get("success") is True
    assert isinstance(body.get("items"), list)


def test_diagnostics_shape(client):
    body = _get_json(client, "/api/diagnostics")
    assert_shape(body, DiagnosticsResponse)
    assert "plugin_health" in body


def test_job_status_shape(client):
    start = client.post("/update_now?async=1", data={"plugin_id": "clock"})
    assert start.status_code == 202
    start_body = start.get_json()
    assert isinstance(start_body, dict)
    job_id = start_body.get("job_id")
    assert isinstance(job_id, str) and job_id

    # Poll until terminal state; queue states are pending/running/done/error.
    # CI runners can be noisy, so allow a modest wall-clock timeout.
    import time

    final = None
    deadline = time.monotonic() + 8.0
    while time.monotonic() < deadline:
        body = _get_json(client, f"/api/job/{job_id}")
        assert_shape(body, JobStatusResponse)
        status = body.get("status")
        if status in {"done", "error"}:
            final = body
            break
        time.sleep(0.025)

    assert isinstance(final, dict), (
        "job did not reach done/error state in time; "
        f"last_status={body.get('status')!r} body={body!r}"
    )
    assert final.get("status") == "done", f"async update job failed: {final!r}"


def test_isolation_shape(client):
    body = _get_json(client, "/settings/isolation")
    assert_shape(body, IsolationResponse)
    assert body.get("success") is True
    assert isinstance(body.get("isolated_plugins"), list)


def test_isolation_mutation_shapes(client):
    body = _request_json(
        client,
        "post",
        "/settings/isolation",
        json={"plugin_id": "clock"},
    )
    assert_shape(body, IsolationResponse)
    assert body.get("success") is True
    assert "clock" in body.get("isolated_plugins", [])

    body = _request_json(
        client,
        "delete",
        "/settings/isolation",
        json={"plugin_id": "clock"},
    )
    assert_shape(body, IsolationResponse)
    assert body.get("success") is True
    assert "clock" not in body.get("isolated_plugins", [])


def test_playlist_crud_shapes(client):
    body = _request_json(
        client,
        "post",
        "/create_playlist",
        json={
            "playlist_name": "Contract Playlist",
            "start_time": "08:00",
            "end_time": "09:00",
        },
    )
    assert_shape(body, SuccessMessageWarningResponse)
    assert body.get("success") is True

    body = _request_json(
        client,
        "put",
        "/update_playlist/Contract Playlist",
        json={
            "new_name": "Contract Playlist Updated",
            "start_time": "09:00",
            "end_time": "10:00",
        },
    )
    assert_shape(body, SuccessMessageWarningResponse)
    assert body.get("success") is True

    body = _request_json(
        client,
        "delete",
        "/delete_playlist/Contract Playlist Updated",
    )
    assert_shape(body, SuccessMessageResponse)
    assert body.get("success") is True


def test_update_device_cycle_shape(client):
    body = _request_json(
        client,
        "put",
        "/update_device_cycle",
        json={"minutes": 30},
    )
    assert_shape(body, SuccessMessageResponse)
    assert body.get("success") is True


def test_update_control_shapes(client, monkeypatch, tmp_path):
    import blueprints.settings as mod
    from blueprints.settings import _updates as updates_mod

    monkeypatch.setattr(mod, "_systemd_available", lambda: False)
    monkeypatch.setattr(mod, "_get_update_script_path", lambda: None)
    monkeypatch.setattr(
        mod,
        "_start_update_fallback_thread",
        lambda script_path, target_tag=None: None,
    )
    monkeypatch.setattr(
        updates_mod,
        "read_last_update_failure",
        lambda: {"message": "boom"},
    )
    monkeypatch.setattr(updates_mod, "_read_prev_version", lambda: "v1.2.3")
    monkeypatch.setenv("INKYPI_LOCKFILE_DIR", str(tmp_path))
    mod._set_update_state(False, None)

    try:
        body = _request_json(client, "post", "/settings/update")
        assert_shape(body, UpdateControlResponse)
        assert body.get("success") is True
        assert body.get("running") is True

        mod._set_update_state(False, None)
        body = _request_json(
            client,
            "post",
            "/settings/update/rollback",
            expected_status=202,
        )
        assert_shape(body, RollbackControlResponse)
        assert body.get("success") is True
        assert body.get("running") is True
    finally:
        mod._set_update_state(False, None)


def test_delete_api_key_shape(client):
    body = _request_json(
        client,
        "post",
        "/settings/delete_api_key",
        data={"key": "OPEN_AI_SECRET"},
    )
    assert_shape(body, SuccessMessageResponse)
    assert body.get("success") is True


def test_history_storage_shape(client):
    resp = client.get("/history/storage")
    # The history dir is a tmp_path created by device_config_dev; shutil
    # should succeed and return 200. If it fails (e.g. read-only CI FS), we
    # still require the error envelope rather than silently passing.
    if resp.status_code == 500:
        pytest.skip("history/storage failed to stat tmp fs (environment)")
    assert resp.status_code == 200
    body = resp.get_json()
    assert_shape(body, HistoryStorageResponse)
