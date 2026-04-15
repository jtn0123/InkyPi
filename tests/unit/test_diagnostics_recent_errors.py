# pyright: reportMissingImports=false
"""Tests for the /api/diagnostics recent_client_log_errors summary (JTN-709).

The diagnostics endpoint surfaces a small window of recent /api/client-log
entries so the in-app status badge can flip to warning/error without needing
a second round-trip to another endpoint.
"""

from __future__ import annotations

import json

import pytest

import blueprints.client_log as cl_mod
import blueprints.diagnostics as diag


@pytest.fixture()
def client(flask_app):
    # The conftest flask_app fixture does not register the client_log blueprint
    # by default — register it here so the diagnostics integration tests can
    # exercise the real POST -> ring-buffer -> GET pipeline.
    if "client_log" not in flask_app.blueprints:
        flask_app.register_blueprint(cl_mod.client_log_bp)
    return flask_app.test_client()


@pytest.fixture(autouse=True)
def _reset_paths_and_buffer(tmp_path, monkeypatch):
    """Isolate diagnostics paths and the client-log ring buffer per test."""
    monkeypatch.setattr(diag, "_PREV_VERSION_PATH", tmp_path / "prev_version")
    monkeypatch.setattr(
        diag, "_LAST_UPDATE_FAILURE_PATH", tmp_path / ".last-update-failure"
    )
    monkeypatch.setenv("INKYPI_ENV", "dev")
    cl_mod.reset_recent_errors()
    yield
    cl_mod.reset_recent_errors()


def _post_log(client, level: str, message: str = "hi"):
    return client.post(
        "/api/client-log",
        data=json.dumps({"level": level, "message": message}),
        content_type="application/json",
    )


def test_diagnostics_includes_recent_client_log_errors_key(client):
    """The endpoint returns the recent_client_log_errors summary key."""
    resp = client.get("/api/diagnostics")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "recent_client_log_errors" in data
    summary = data["recent_client_log_errors"]
    assert isinstance(summary, dict)
    assert set(summary.keys()) >= {
        "count_5m",
        "warn_count_5m",
        "last_error_ts",
        "window_seconds",
    }
    assert summary["count_5m"] == 0
    assert summary["warn_count_5m"] == 0
    assert summary["last_error_ts"] is None
    assert summary["window_seconds"] == 300


def test_counter_increments_on_client_log_error_post(client):
    """POST /api/client-log with level=error bumps count_5m by 1."""
    assert _post_log(client, "error", "boom").status_code == 204
    data = client.get("/api/diagnostics").get_json()
    summary = data["recent_client_log_errors"]
    assert summary["count_5m"] == 1
    assert summary["warn_count_5m"] == 0
    assert isinstance(summary["last_error_ts"], (int, float))
    assert summary["last_error_ts"] > 0


def test_warn_counter_tracked_separately(client):
    """A warn-level entry updates warn_count_5m but not count_5m."""
    assert _post_log(client, "warn", "careful").status_code == 204
    summary = client.get("/api/diagnostics").get_json()["recent_client_log_errors"]
    assert summary["count_5m"] == 0
    assert summary["warn_count_5m"] == 1
    # warn-only activity leaves last_error_ts at None
    assert summary["last_error_ts"] is None


def test_batch_post_increments_per_entry(client):
    """A batch POST increments the counter once per validated entry."""
    payload = [
        {"level": "error", "message": "a"},
        {"level": "error", "message": "b"},
        {"level": "warn", "message": "c"},
    ]
    resp = client.post(
        "/api/client-log",
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert resp.status_code == 204
    summary = client.get("/api/diagnostics").get_json()["recent_client_log_errors"]
    assert summary["count_5m"] == 2
    assert summary["warn_count_5m"] == 1


def test_five_minute_cutoff_excludes_old_entries():
    """Entries older than the window are excluded from count_5m."""
    cl_mod.reset_recent_errors()
    # Seed one fresh error and one entry well past the 5-minute cutoff.
    now = 1_800_000_000.0
    cl_mod._recent_errors.append((now - 10.0, "error"))  # within window
    cl_mod._recent_errors.append((now - 3600.0, "error"))  # an hour ago

    summary = cl_mod.get_recent_error_summary(now=now, window_seconds=300)
    assert summary["count_5m"] == 1
    # last_error_ts reflects the most recent error regardless of cutoff so
    # the UI can still say "we saw one an hour ago".
    assert summary["last_error_ts"] == now - 10.0


def test_ring_buffer_is_bounded():
    """The ring buffer discards oldest entries when it fills up."""
    cl_mod.reset_recent_errors()
    for i in range(cl_mod._RECENT_BUFFER_MAX + 25):
        cl_mod._record_recent("error")
    assert len(cl_mod._recent_errors) == cl_mod._RECENT_BUFFER_MAX


def test_invalid_entries_do_not_count(client):
    """Validation failures leave the counter untouched."""
    resp = client.post(
        "/api/client-log",
        data=json.dumps({"level": "info", "message": "nope"}),
        content_type="application/json",
    )
    assert resp.status_code == 400
    summary = client.get("/api/diagnostics").get_json()["recent_client_log_errors"]
    assert summary["count_5m"] == 0
    assert summary["warn_count_5m"] == 0
