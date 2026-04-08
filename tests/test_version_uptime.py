# pyright: reportMissingImports=false
"""Tests for /api/version/info and /api/uptime endpoints (JTN-360)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest


@pytest.fixture()
def client(flask_app):
    """Return a Flask test client."""
    return flask_app.test_client()


# ---------------------------------------------------------------------------
# /api/version/info
# ---------------------------------------------------------------------------


def test_version_info_returns_200(client):
    """GET /api/version/info should return HTTP 200."""
    resp = client.get("/api/version/info")
    assert resp.status_code == 200


def test_version_info_has_expected_keys(client):
    """Response must contain all required keys."""
    resp = client.get("/api/version/info")
    data = resp.get_json()
    assert data is not None
    for key in ("version", "git_sha", "git_branch", "build_time", "python_version"):
        assert key in data, f"Missing key: {key}"


def test_version_info_version_non_empty(client):
    """The version field must be a non-empty string."""
    resp = client.get("/api/version/info")
    data = resp.get_json()
    assert isinstance(data["version"], str)
    assert len(data["version"]) > 0


def test_version_info_git_sha_is_string(client):
    """git_sha must be a string (may be 'unknown' in CI without git history)."""
    resp = client.get("/api/version/info")
    data = resp.get_json()
    assert isinstance(data["git_sha"], str)


def test_version_info_git_branch_is_string(client):
    """git_branch must be a string."""
    resp = client.get("/api/version/info")
    data = resp.get_json()
    assert isinstance(data["git_branch"], str)


def test_version_info_python_version_non_empty(client):
    """python_version must be a non-empty string."""
    resp = client.get("/api/version/info")
    data = resp.get_json()
    assert isinstance(data["python_version"], str)
    assert len(data["python_version"]) > 0


def test_version_info_build_time_non_empty(client):
    """build_time must be a non-empty string."""
    resp = client.get("/api/version/info")
    data = resp.get_json()
    assert isinstance(data["build_time"], str)
    assert len(data["build_time"]) > 0


# ---------------------------------------------------------------------------
# /api/uptime
# ---------------------------------------------------------------------------


def test_uptime_returns_200(client):
    """GET /api/uptime should return HTTP 200."""
    resp = client.get("/api/uptime")
    assert resp.status_code == 200


def test_uptime_has_expected_keys(client):
    """Response must contain all required keys."""
    resp = client.get("/api/uptime")
    data = resp.get_json()
    assert data is not None
    for key in (
        "process_uptime_seconds",
        "system_uptime_seconds",
        "process_started_at",
    ):
        assert key in data, f"Missing key: {key}"


def test_uptime_process_uptime_positive(client):
    """process_uptime_seconds must be greater than zero."""
    resp = client.get("/api/uptime")
    data = resp.get_json()
    assert isinstance(data["process_uptime_seconds"], int | float)
    assert data["process_uptime_seconds"] > 0


def test_uptime_system_uptime_int_or_null(client):
    """system_uptime_seconds must be an integer or null (None on macOS/Windows)."""
    resp = client.get("/api/uptime")
    data = resp.get_json()
    value = data["system_uptime_seconds"]
    assert value is None or isinstance(value, int)


def test_uptime_process_started_at_is_valid_iso8601(client):
    """process_started_at must be a parseable ISO 8601 timestamp."""
    resp = client.get("/api/uptime")
    data = resp.get_json()
    ts = data["process_started_at"]
    assert isinstance(ts, str)
    # datetime.fromisoformat raises ValueError on invalid format
    parsed = datetime.fromisoformat(ts)
    assert parsed.tzinfo is not None, "Timestamp must include timezone info"


def test_uptime_process_started_at_in_past(client):
    """process_started_at must be earlier than now."""
    resp = client.get("/api/uptime")
    data = resp.get_json()
    parsed = datetime.fromisoformat(data["process_started_at"])
    assert parsed <= datetime.now(UTC)
