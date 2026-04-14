# pyright: reportMissingImports=false
"""Tests for the consolidated /api/diagnostics endpoint (JTN-707)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture()
def client(flask_app):
    """Flask test client with the diagnostics blueprint registered."""
    return flask_app.test_client()


@pytest.fixture(autouse=True)
def _patch_diagnostics_paths(tmp_path, monkeypatch):
    """Redirect /var/lib/inkypi paths so tests never touch the real fs.

    The endpoint reads ``/var/lib/inkypi/prev_version`` and
    ``/var/lib/inkypi/.last-update-failure``. Unit tests must never depend on
    those paths existing (or not existing) on the host machine.
    """
    import blueprints.diagnostics as diag

    prev = tmp_path / "prev_version"
    fail = tmp_path / ".last-update-failure"
    monkeypatch.setattr(diag, "_PREV_VERSION_PATH", prev)
    monkeypatch.setattr(diag, "_LAST_UPDATE_FAILURE_PATH", fail)
    # Dev env so unauthenticated local calls are allowed during tests.
    monkeypatch.setenv("INKYPI_ENV", "dev")
    return {"prev": prev, "fail": fail}


# ---------------------------------------------------------------------------
# Shape / required keys
# ---------------------------------------------------------------------------


def test_returns_200_with_required_keys(client):
    """GET /api/diagnostics returns 200 with the documented top-level shape."""
    resp = client.get("/api/diagnostics")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data is not None

    required_keys = {
        "ts",
        "version",
        "prev_version",
        "uptime_s",
        "memory",
        "disk",
        "refresh_task",
        "plugin_health",
        "log_tail_100",
        "last_update_failure",
    }
    assert required_keys.issubset(
        data.keys()
    ), f"missing keys: {required_keys - set(data.keys())}"

    # uptime_s is an integer (or None in exotic environments)
    assert data["uptime_s"] is None or isinstance(data["uptime_s"], int)

    # memory shape
    mem = data["memory"]
    assert isinstance(mem, dict)
    assert set(mem.keys()) >= {"total_mb", "used_mb", "pct"}

    # disk shape
    disk = data["disk"]
    assert isinstance(disk, dict)
    assert set(disk.keys()) >= {"total_mb", "used_mb", "pct", "path"}

    # version must be non-empty string
    assert isinstance(data["version"], str) and data["version"]

    # refresh_task shape
    rt = data["refresh_task"]
    assert isinstance(rt, dict)
    assert {"running", "last_run_ts", "last_error"}.issubset(rt.keys())

    # plugin_health is a flat string-to-string map
    ph = data["plugin_health"]
    assert isinstance(ph, dict)
    for v in ph.values():
        assert v in {"ok", "fail", "unknown"}


def test_version_matches_version_file(client):
    """The `version` field reflects the repo's VERSION file."""
    repo_root = Path(__file__).resolve().parents[2]
    expected = (repo_root / "VERSION").read_text().strip()
    resp = client.get("/api/diagnostics")
    data = resp.get_json()
    assert data["version"] == expected


# ---------------------------------------------------------------------------
# Missing optional files
# ---------------------------------------------------------------------------


def test_handles_missing_prev_version(client, _patch_diagnostics_paths):
    """prev_version is null when /var/lib/inkypi/prev_version is absent."""
    assert not _patch_diagnostics_paths["prev"].exists()
    resp = client.get("/api/diagnostics")
    data = resp.get_json()
    assert data["prev_version"] is None


def test_reads_prev_version_when_present(client, _patch_diagnostics_paths):
    """prev_version is returned verbatim (stripped) when the file exists."""
    _patch_diagnostics_paths["prev"].write_text("0.51.7\n")
    resp = client.get("/api/diagnostics")
    data = resp.get_json()
    assert data["prev_version"] == "0.51.7"


def test_handles_missing_last_update_failure(client, _patch_diagnostics_paths):
    """last_update_failure is null when the sentinel file does not exist."""
    assert not _patch_diagnostics_paths["fail"].exists()
    resp = client.get("/api/diagnostics")
    data = resp.get_json()
    assert data["last_update_failure"] is None


def test_last_update_failure_parses_json_payload(client, _patch_diagnostics_paths):
    """A JSON payload in .last-update-failure is parsed and returned as-is."""
    _patch_diagnostics_paths["fail"].write_text(
        '{"ts": "2026-04-14T00:00:00Z", "reason": "apt update failed"}'
    )
    resp = client.get("/api/diagnostics")
    data = resp.get_json()
    assert isinstance(data["last_update_failure"], dict)
    assert data["last_update_failure"]["reason"] == "apt update failed"


def test_last_update_failure_raw_text_fallback(client, _patch_diagnostics_paths):
    """Non-JSON contents are returned as a plain string so info is never lost."""
    _patch_diagnostics_paths["fail"].write_text("plain text failure note")
    resp = client.get("/api/diagnostics")
    data = resp.get_json()
    assert data["last_update_failure"] == "plain text failure note"


# ---------------------------------------------------------------------------
# Plugin health
# ---------------------------------------------------------------------------


def test_plugin_health_includes_all_registered_plugins(client):
    """Every registered plugin appears in plugin_health, even if never run."""
    from plugins.plugin_registry import get_registered_plugin_ids

    registered = set(get_registered_plugin_ids())
    # The test fixture loads at least one plugin; if not, skip rather than fail
    # the shape contract.
    if not registered:
        pytest.skip("no plugins registered in this test environment")

    resp = client.get("/api/diagnostics")
    data = resp.get_json()
    ph = data["plugin_health"]
    assert isinstance(ph, dict)
    assert registered.issubset(
        set(ph.keys())
    ), f"missing plugins: {registered - set(ph.keys())}"
    # All values are one of the documented statuses
    for pid, status in ph.items():
        assert status in {"ok", "fail", "unknown"}, (pid, status)


def test_plugin_health_reflects_snapshot_status(client, flask_app):
    """A green/red entry in the refresh-task snapshot maps to ok/fail."""
    rt = flask_app.config["REFRESH_TASK"]
    with patch.object(
        rt,
        "get_health_snapshot",
        return_value={
            "clock": {"status": "green"},
            "weather": {"status": "red", "last_error": "timeout"},
        },
    ):
        resp = client.get("/api/diagnostics")
    data = resp.get_json()
    ph = data["plugin_health"]
    assert ph.get("clock") == "ok"
    assert ph.get("weather") == "fail"
    # last_error should also bubble into refresh_task.last_error
    assert data["refresh_task"]["last_error"] == "timeout"


# ---------------------------------------------------------------------------
# Log tail
# ---------------------------------------------------------------------------


def test_log_tail_respects_100_line_cap(client, monkeypatch):
    """log_tail_100 is capped to the most recent 100 entries, even if more exist."""
    import blueprints.settings as settings_mod

    huge = [f"line-{i}" for i in range(500)]
    monkeypatch.setattr(settings_mod, "_read_log_lines", lambda hours: huge)

    resp = client.get("/api/diagnostics")
    data = resp.get_json()
    tail = data["log_tail_100"]
    assert isinstance(tail, list)
    assert len(tail) == 100
    # Cap keeps the most-recent entries (end of the list).
    assert tail[0] == "line-400"
    assert tail[-1] == "line-499"


def test_log_tail_handles_reader_error(client, monkeypatch):
    """A failing log reader degrades to an empty list, not a 500."""
    import blueprints.settings as settings_mod

    def boom(hours):  # noqa: ARG001 — signature match
        raise RuntimeError("journalctl unavailable")

    monkeypatch.setattr(settings_mod, "_read_log_lines", boom)
    resp = client.get("/api/diagnostics")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["log_tail_100"] == []


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------


def test_access_denied_for_remote_ip_without_auth(flask_app, monkeypatch):
    """Without PIN auth and outside INKYPI_ENV=dev, non-private IPs get 403."""
    monkeypatch.delenv("INKYPI_ENV", raising=False)
    flask_app.config["AUTH_ENABLED"] = False
    client = flask_app.test_client()
    resp = client.get("/api/diagnostics", environ_overrides={"REMOTE_ADDR": "8.8.8.8"})
    assert resp.status_code == 403


def test_access_allowed_for_private_ip_without_auth(flask_app, monkeypatch):
    """RFC1918 / loopback callers are allowed even without auth."""
    monkeypatch.delenv("INKYPI_ENV", raising=False)
    flask_app.config["AUTH_ENABLED"] = False
    client = flask_app.test_client()
    resp = client.get(
        "/api/diagnostics", environ_overrides={"REMOTE_ADDR": "192.168.1.42"}
    )
    assert resp.status_code == 200


def test_access_allowed_when_auth_enabled(flask_app, monkeypatch):
    """If app-level PIN auth is enabled, the endpoint trusts the gate."""
    monkeypatch.delenv("INKYPI_ENV", raising=False)
    flask_app.config["AUTH_ENABLED"] = True
    client = flask_app.test_client()
    resp = client.get("/api/diagnostics", environ_overrides={"REMOTE_ADDR": "8.8.8.8"})
    assert resp.status_code == 200
