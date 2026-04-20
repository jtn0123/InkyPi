# pyright: reportMissingImports=false
"""Tests for /api/version/info and /api/uptime endpoints (JTN-360)."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

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


# ---------------------------------------------------------------------------
# Unit tests for helper functions (coverage of exception / Linux paths)
# ---------------------------------------------------------------------------


def test_read_app_version_fallback_on_missing_file():
    """_read_app_version returns 'unknown' only when VERSION and pyproject both fail.

    JTN-624: when VERSION is missing, the function now falls back to reading
    ``[project].version`` from pyproject.toml. Only if both sources fail do
    we surface 'unknown' to the UI.
    """
    from blueprints.version_info import _read_app_version

    with patch("pathlib.Path.read_text", side_effect=FileNotFoundError("no file")):
        with patch("pathlib.Path.open", side_effect=FileNotFoundError("no file")):
            result = _read_app_version()

    assert result == "unknown"


def test_read_app_version_falls_back_to_pyproject_when_version_missing():
    """_read_app_version reads pyproject.toml when VERSION is unavailable (JTN-624)."""
    from blueprints.version_info import _read_app_version

    # Simulate VERSION file read failure; pyproject.toml open should succeed
    # and yield a real version string.
    with patch("pathlib.Path.read_text", side_effect=FileNotFoundError("no file")):
        result = _read_app_version()

    assert result != "unknown"
    assert result != "{version}"
    assert result


def test_read_app_version_rejects_unexpanded_placeholder():
    """VERSION containing the literal '{version}' placeholder falls back (JTN-595).

    mutmut triage: kills a surviving mutant where
    ``value != "{version}"`` is removed from the guard, letting a broken
    release pipeline leak the raw Jinja-style placeholder into the UI.
    The function must always ignore that value and fall through to
    pyproject.toml.

    The pyproject fallback is also stubbed so the assertion verifies only
    the VERSION guard, independent of the repo's current
    ``[project].version`` value.
    """
    import tomllib

    from blueprints.version_info import _read_app_version

    with (
        patch("pathlib.Path.read_text", return_value="{version}\n"),
        patch.object(tomllib, "load", return_value={"project": {"version": "7.7.7"}}),
    ):
        result = _read_app_version()

    assert result == "7.7.7"


def test_read_app_version_rejects_bootstrap_placeholder():
    """VERSION containing the bootstrap '0.1.0' placeholder falls back (JTN-595).

    mutmut triage: kills a surviving mutant where
    ``value != "0.1.0"`` is removed. ``0.1.0`` is the project's pre-release
    bootstrap value that must never be surfaced as a real shipped version.

    The pyproject fallback is also stubbed so the assertion verifies only
    the VERSION guard, independent of the repo's current
    ``[project].version`` value.
    """
    import tomllib

    from blueprints.version_info import _read_app_version

    with (
        patch("pathlib.Path.read_text", return_value="0.1.0\n"),
        patch.object(tomllib, "load", return_value={"project": {"version": "7.7.7"}}),
    ):
        result = _read_app_version()

    assert result == "7.7.7"


def test_read_app_version_accepts_real_version_string():
    """A real semver value in VERSION must be returned verbatim (JTN-595).

    mutmut triage: kills surviving mutants where the positive branch is
    replaced (e.g. ``return value`` → ``return "unknown"`` or the ``if
    value`` guard is inverted). Without this test the happy path is only
    covered indirectly by the ``/api/version/info`` integration test that
    reads the checked-in VERSION.
    """
    from blueprints.version_info import _read_app_version

    with patch("pathlib.Path.read_text", return_value="9.9.9\n"):
        result = _read_app_version()

    assert result == "9.9.9"


def test_run_git_returns_unknown_on_nonzero_returncode():
    """_run_git returns 'unknown' when git exits with non-zero."""
    from blueprints.version_info import _run_git

    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stdout = "some error"
    with patch("blueprints.version_info.subprocess.run", return_value=mock_result):
        result = _run_git("rev-parse", "--short", "HEAD")

    assert result == "unknown"


def test_run_git_returns_unknown_on_exception():
    """_run_git returns 'unknown' when subprocess.run raises."""
    from blueprints.version_info import _run_git

    with patch(
        "blueprints.version_info.subprocess.run",
        side_effect=subprocess.TimeoutExpired(["git"], 1),
    ):
        result = _run_git("rev-parse", "--short", "HEAD")

    assert result == "unknown"


def test_read_build_time_uses_file_when_present(tmp_path):
    """_read_build_time returns file content when build_time.txt exists."""
    from blueprints.version_info import _read_build_time

    build_time_content = "2024-01-15T10:30:00+00:00"
    build_file = tmp_path / "build_time.txt"
    build_file.write_text(build_time_content)

    with patch("blueprints.version_info.Path") as mock_path_cls:
        # Make Path(__file__) chain work: Path(...).parent.parent.parent / "build_time.txt"
        mock_path = MagicMock(spec=Path)
        # Each .parent returns a new mock; final / returns our real file
        mock_parent = MagicMock(spec=Path)
        mock_path.parent = mock_parent
        mock_parent.parent = mock_parent
        mock_parent.__truediv__ = lambda self, other: build_file
        mock_path_cls.return_value = mock_path
        result = _read_build_time()

    assert result == build_time_content


def test_system_uptime_seconds_on_linux(tmp_path):
    """_system_uptime_seconds returns int when /proc/uptime is readable."""
    from blueprints.version_info import _system_uptime_seconds

    fake_uptime = tmp_path / "uptime"
    fake_uptime.write_text("12345.67 98765.43\n")

    with patch("blueprints.version_info.Path", return_value=fake_uptime):
        result = _system_uptime_seconds()

    assert result == 12345


def test_system_uptime_seconds_returns_none_on_error():
    """_system_uptime_seconds returns None when /proc/uptime is unreadable."""
    from blueprints.version_info import _system_uptime_seconds

    with patch(
        "blueprints.version_info.Path",
        side_effect=OSError("no such file"),
    ):
        result = _system_uptime_seconds()

    assert result is None
