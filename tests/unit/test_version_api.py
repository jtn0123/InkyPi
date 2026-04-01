# pyright: reportMissingImports=false
"""Tests for the /api/version endpoint in blueprints.settings."""

import time
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def client(flask_app):
    """Return a Flask test client."""
    return flask_app.test_client()


@pytest.fixture(autouse=True)
def reset_version_cache():
    """Reset _VERSION_CACHE before each test so tests are independent."""
    import blueprints.settings as settings_mod

    settings_mod._VERSION_CACHE["latest"] = None
    settings_mod._VERSION_CACHE["checked_at"] = 0.0
    settings_mod._VERSION_CACHE["release_notes"] = None
    yield
    settings_mod._VERSION_CACHE["latest"] = None
    settings_mod._VERSION_CACHE["checked_at"] = 0.0
    settings_mod._VERSION_CACHE["release_notes"] = None


@pytest.fixture(autouse=True)
def reset_update_state():
    """Reset _UPDATE_STATE before each test."""
    import blueprints.settings as settings_mod

    original = dict(settings_mod._UPDATE_STATE)
    settings_mod._UPDATE_STATE["running"] = False
    settings_mod._UPDATE_STATE["unit"] = None
    settings_mod._UPDATE_STATE["started_at"] = None
    yield
    settings_mod._UPDATE_STATE.update(original)


def _mock_github_response(tag_name="v2.0.0", body="Release notes", status_code=200):
    """Create a mock requests.Response for the GitHub Releases API."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = {"tag_name": tag_name, "body": body}
    if status_code >= 400:
        resp.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
    else:
        resp.raise_for_status.return_value = None
    return resp


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_api_version_returns_current(client):
    """GET /api/version should return a JSON object with a 'current' key."""
    with patch("blueprints.settings.http_get", return_value=_mock_github_response()):
        resp = client.get("/api/version")

    assert resp.status_code == 200
    data = resp.get_json()
    assert data is not None
    assert "current" in data


def test_api_version_unknown_when_no_version(flask_app, client):
    """When APP_VERSION is 'unknown', the response should reflect that."""
    flask_app.config["APP_VERSION"] = "unknown"

    with patch("blueprints.settings.http_get", return_value=_mock_github_response()):
        resp = client.get("/api/version")

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["current"] == "unknown"
    # update_available must be False when current is "unknown"
    assert data["update_available"] is False


def test_api_version_latest_from_cache(client):
    """When the cache is warm, requests.get should not be called."""
    import blueprints.settings as settings_mod

    # Pre-populate cache with a recent timestamp
    settings_mod._VERSION_CACHE["latest"] = "2.0.0"
    settings_mod._VERSION_CACHE["checked_at"] = time.time()

    with patch("blueprints.settings.http_get") as mock_get:
        resp = client.get("/api/version")
        mock_get.assert_not_called()

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["latest"] == "2.0.0"


def test_api_version_cache_miss_fetches_from_github(flask_app, client):
    """On a cache miss, GitHub API is called and the latest tag is parsed."""
    flask_app.config["APP_VERSION"] = "1.9.0"

    with patch(
        "blueprints.settings.http_get",
        return_value=_mock_github_response("v2.0.0"),
    ):
        resp = client.get("/api/version")

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["latest"] == "2.0.0"


def test_api_version_update_available_true(flask_app, client):
    """update_available should be True when latest > current (semver)."""
    flask_app.config["APP_VERSION"] = "1.9.0"

    with patch(
        "blueprints.settings.http_get",
        return_value=_mock_github_response("v2.0.0"),
    ):
        resp = client.get("/api/version")

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["update_available"] is True


def test_api_version_update_available_false(flask_app, client):
    """update_available should be False when current == latest."""
    flask_app.config["APP_VERSION"] = "2.0.0"

    with patch(
        "blueprints.settings.http_get",
        return_value=_mock_github_response("v2.0.0"),
    ):
        resp = client.get("/api/version")

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["update_available"] is False


def test_api_version_offline_returns_null_latest(client):
    """When the GitHub API request fails, latest should be None."""
    with patch("blueprints.settings.http_get", side_effect=Exception("network error")):
        resp = client.get("/api/version")

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["latest"] is None


def test_api_version_update_running_reflects_state(client):
    """update_running should mirror _UPDATE_STATE['running']."""
    import blueprints.settings as settings_mod

    settings_mod._UPDATE_STATE["running"] = True

    with patch("blueprints.settings.http_get", return_value=_mock_github_response()):
        resp = client.get("/api/version")

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["update_running"] is True


def test_semver_comparison_10_gt_9():
    """1.10.0 should be greater than 1.9.0 (not string comparison)."""
    from blueprints.settings import _semver_gt

    assert _semver_gt("1.10.0", "1.9.0") is True
    assert _semver_gt("1.9.0", "1.10.0") is False
    assert _semver_gt("2.0.0", "1.99.99") is True
    assert _semver_gt("1.0.0", "1.0.0") is False


def test_github_api_404(client):
    """When GitHub returns 404, latest should be None."""
    with patch(
        "blueprints.settings.http_get",
        return_value=_mock_github_response(status_code=404),
    ):
        resp = client.get("/api/version")

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["latest"] is None


def test_github_repo_env_override(client, monkeypatch):
    """INKYPI_GITHUB_REPO env var should change the API URL."""
    import blueprints.settings as settings_mod

    monkeypatch.setattr(settings_mod, "_GITHUB_REPO", "other-org/OtherRepo")

    with patch(
        "blueprints.settings.http_get", return_value=_mock_github_response()
    ) as mock_get:
        client.get("/api/version")
        mock_get.assert_called_once()
        url = mock_get.call_args[0][0]
        assert "other-org/OtherRepo" in url


def test_api_version_includes_release_notes(flask_app, client):
    """Response should include release_notes from the GitHub release."""
    flask_app.config["APP_VERSION"] = "1.0.0"

    with patch(
        "blueprints.settings.http_get",
        return_value=_mock_github_response("v2.0.0", body="## What's new\n- Feature X"),
    ):
        resp = client.get("/api/version")

    assert resp.status_code == 200
    data = resp.get_json()
    assert "release_notes" in data
    assert "Feature X" in data["release_notes"]
