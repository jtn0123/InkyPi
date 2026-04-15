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


def test_access_denied_for_unparseable_remote_addr(flask_app, monkeypatch):
    """An unparseable REMOTE_ADDR fails closed (403), not open."""
    monkeypatch.delenv("INKYPI_ENV", raising=False)
    flask_app.config["AUTH_ENABLED"] = False
    client = flask_app.test_client()
    resp = client.get(
        "/api/diagnostics", environ_overrides={"REMOTE_ADDR": "not-an-ip"}
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# System metric helpers — fallback branches
# ---------------------------------------------------------------------------


def test_uptime_seconds_falls_back_to_proc_uptime(monkeypatch, tmp_path):
    """When psutil.boot_time raises, _uptime_seconds reads /proc/uptime."""
    import blueprints.diagnostics as diag

    fake = tmp_path / "uptime"
    fake.write_text("54321.42 12345.67\n")

    class _BoomPsutil:
        @staticmethod
        def boot_time():
            raise RuntimeError("no psutil on this host")

    monkeypatch.setitem(__import__("sys").modules, "psutil", _BoomPsutil)
    monkeypatch.setattr(
        diag, "Path", lambda p="": fake if p == "/proc/uptime" else Path(p)
    )
    assert diag._uptime_seconds() == 54321


def test_uptime_seconds_returns_none_on_total_failure(monkeypatch):
    """Both psutil and /proc/uptime failing yields None instead of raising."""
    import blueprints.diagnostics as diag

    class _BoomPsutil:
        @staticmethod
        def boot_time():
            raise RuntimeError("x")

    monkeypatch.setitem(__import__("sys").modules, "psutil", _BoomPsutil)

    class _NoFile:
        def __init__(self, *_args, **_kw):
            pass

        def read_text(self):
            raise FileNotFoundError

    monkeypatch.setattr(diag, "Path", _NoFile)
    assert diag._uptime_seconds() is None


def test_memory_info_falls_back_to_proc_meminfo(monkeypatch, tmp_path):
    """When psutil raises, _memory_info parses /proc/meminfo in kB."""
    import blueprints.diagnostics as diag

    fake = tmp_path / "meminfo"
    fake.write_text(
        "MemTotal:         512000 kB\n"
        "MemFree:          100000 kB\n"
        "MemAvailable:     200000 kB\n"
    )

    class _BoomPsutil:
        @staticmethod
        def virtual_memory():
            raise RuntimeError("no psutil")

    monkeypatch.setitem(__import__("sys").modules, "psutil", _BoomPsutil)

    # Patch Path("/proc/meminfo") to our temp file while leaving others alone.
    real_path = diag.Path

    def _path(p=""):
        if p == "/proc/meminfo":
            return fake
        return real_path(p)

    monkeypatch.setattr(diag, "Path", _path)
    info = diag._memory_info()
    # Total = 512000 kB ~ 500 MB, used = 512000 - 200000 = 312000 kB ~ 304 MB
    assert info["total_mb"] == 500
    assert info["used_mb"] == 304
    # pct = 100 * (512000-200000)/512000 ~= 60.9
    assert info["pct"] == pytest.approx(60.9, abs=0.2)


def test_memory_info_returns_nulls_on_total_failure(monkeypatch):
    """When every source raises, _memory_info returns a null-shaped dict."""
    import blueprints.diagnostics as diag

    class _BoomPsutil:
        @staticmethod
        def virtual_memory():
            raise RuntimeError("x")

    monkeypatch.setitem(__import__("sys").modules, "psutil", _BoomPsutil)

    class _NoFile:
        def __init__(self, *_args, **_kw):
            pass

        def open(self, *_a, **_kw):
            raise FileNotFoundError

    monkeypatch.setattr(diag, "Path", _NoFile)
    info = diag._memory_info()
    assert info == {"total_mb": None, "used_mb": None, "pct": None}


def test_disk_info_returns_nulls_on_oserror(monkeypatch):
    """shutil.disk_usage raising gives a null-shaped disk entry (no 500)."""
    import blueprints.diagnostics as diag

    def _boom(_path):
        raise OSError("read-only")

    monkeypatch.setattr(diag.shutil, "disk_usage", _boom)
    info = diag._disk_info("/nope")
    assert info["path"] == "/nope"
    assert info["total_mb"] is None
    assert info["used_mb"] is None
    assert info["pct"] is None


# ---------------------------------------------------------------------------
# Version resolution
# ---------------------------------------------------------------------------


def test_read_version_falls_back_to_app_config(flask_app, monkeypatch):
    """When the VERSION file is unreadable, APP_VERSION from flask config is used."""
    import blueprints.diagnostics as diag

    flask_app.config["APP_VERSION"] = "9.9.9-test"

    class _NoFile:
        def __init__(self, *_args, **_kw):
            pass

        def resolve(self):
            return self

        @property
        def parent(self):
            return self

        def __truediv__(self, _other):
            return self

        def read_text(self, *_a, **_kw):
            raise FileNotFoundError

    monkeypatch.setattr(diag, "Path", _NoFile)
    with flask_app.test_request_context("/api/diagnostics"):
        assert diag._read_version() == "9.9.9-test"


def test_read_version_unknown_when_no_source(flask_app, monkeypatch):
    """Returns the literal 'unknown' when VERSION and APP_VERSION are both missing."""
    import blueprints.diagnostics as diag

    flask_app.config.pop("APP_VERSION", None)

    class _NoFile:
        def __init__(self, *_args, **_kw):
            pass

        def resolve(self):
            return self

        @property
        def parent(self):
            return self

        def __truediv__(self, _other):
            return self

        def read_text(self, *_a, **_kw):
            raise FileNotFoundError

    monkeypatch.setattr(diag, "Path", _NoFile)
    with flask_app.test_request_context("/api/diagnostics"):
        assert diag._read_version() == "unknown"


# ---------------------------------------------------------------------------
# Refresh task + plugin registry edge cases
# ---------------------------------------------------------------------------


def test_refresh_task_snapshot_no_refresh_task(flask_app):
    """Missing REFRESH_TASK yields a benign null-shaped snapshot."""
    import blueprints.diagnostics as diag

    flask_app.config["REFRESH_TASK"] = None
    with flask_app.test_request_context("/api/diagnostics"):
        snap = diag._refresh_task_snapshot()
    assert snap == {"running": False, "last_run_ts": None, "last_error": None}


def test_refresh_task_snapshot_picks_most_recent_failure(client, flask_app):
    """When multiple plugins have errors, the most recent failure wins."""
    import blueprints.diagnostics as diag

    rt = flask_app.config["REFRESH_TASK"]
    with patch.object(
        rt,
        "get_health_snapshot",
        return_value={
            "a": {
                "last_error": "older",
                "last_failure_at": "2026-01-01T00:00:00+00:00",
            },
            "b": {
                "last_error": "newer",
                "last_failure_at": "2026-04-01T00:00:00+00:00",
            },
        },
    ):
        with flask_app.test_request_context("/api/diagnostics"):
            snap = diag._refresh_task_snapshot()
    assert snap["last_error"] == "newer"


def test_refresh_task_snapshot_handles_health_method_raising(client, flask_app):
    """A health-snapshot method that raises doesn't leak past the endpoint."""
    import blueprints.diagnostics as diag

    rt = flask_app.config["REFRESH_TASK"]
    with patch.object(rt, "get_health_snapshot", side_effect=RuntimeError("broken")):
        with flask_app.test_request_context("/api/diagnostics"):
            snap = diag._refresh_task_snapshot()
    assert snap["last_error"] is None


def test_plugin_health_registry_failure_still_returns_dict(client, monkeypatch):
    """A broken plugin registry still yields a dict (possibly empty)."""

    def _boom():
        raise RuntimeError("registry broken")

    monkeypatch.setattr("plugins.plugin_registry.get_registered_plugin_ids", _boom)
    resp = client.get("/api/diagnostics")
    assert resp.status_code == 200
    ph = resp.get_json()["plugin_health"]
    assert isinstance(ph, dict)


# ---------------------------------------------------------------------------
# Private-address classifier
# ---------------------------------------------------------------------------


def test_is_private_address_classifier():
    """_is_private_address covers loopback, RFC1918, link-local, and public IPs."""
    import blueprints.diagnostics as diag

    assert diag._is_private_address("127.0.0.1") is True
    assert diag._is_private_address("10.0.0.1") is True
    assert diag._is_private_address("192.168.5.5") is True
    assert diag._is_private_address("169.254.1.1") is True
    assert diag._is_private_address("::1") is True
    assert diag._is_private_address("fc00::1") is True
    assert diag._is_private_address("8.8.8.8") is False
    assert diag._is_private_address("1.2.3.4") is False
    assert diag._is_private_address("") is False
    assert diag._is_private_address(None) is False
    assert diag._is_private_address("not-an-ip") is False
