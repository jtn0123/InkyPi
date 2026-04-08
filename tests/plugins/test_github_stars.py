# pyright: reportMissingImports=false
"""Tests for the GitHub stars plugin repository path resolution (JTN-264)."""

from unittest.mock import MagicMock, patch

import pytest

from plugins.github.github_stars import fetch_stars, stars_generate_image


def _make_plugin_instance(width=800, height=480):
    """Return a minimal plugin instance mock."""
    instance = MagicMock()
    instance.get_oriented_dimensions.return_value = (width, height)
    instance.render_image.return_value = MagicMock()
    return instance


def _make_settings(username, repository):
    return {"githubUsername": username, "githubRepository": repository}


def _make_api_response(stars=42):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"stargazers_count": stars}
    return resp


# ---------------------------------------------------------------------------
# fetch_stars URL construction — captured via the HTTP session mock
# ---------------------------------------------------------------------------


@patch("plugins.github.github_stars.get_http_session")
def test_fetch_stars_plain_repo(mock_session):
    """fetch_stars passes the repository path straight to the API."""
    mock_get = MagicMock(return_value=_make_api_response(100))
    mock_session.return_value.get = mock_get

    result = fetch_stars("octocat/Hello-World")

    assert result == 100
    called_url = mock_get.call_args[0][0]
    assert called_url.endswith("/repos/octocat/Hello-World")


# ---------------------------------------------------------------------------
# stars_generate_image — repository field formats
# ---------------------------------------------------------------------------


@patch("plugins.github.github_stars.get_http_session")
def test_plain_repo_name_prepends_username(mock_session):
    """When repository has no '/', username is prepended as expected."""
    mock_get = MagicMock(return_value=_make_api_response(7))
    mock_session.return_value.get = mock_get

    instance = _make_plugin_instance()
    stars_generate_image(
        instance, _make_settings("octocat", "Hello-World"), MagicMock()
    )

    called_url = mock_get.call_args[0][0]
    assert "/repos/octocat/Hello-World" in called_url


@patch("plugins.github.github_stars.get_http_session")
def test_owner_slash_repo_used_directly(mock_session):
    """When repository contains '/', it is used directly without doubling username."""
    mock_get = MagicMock(return_value=_make_api_response(99))
    mock_session.return_value.get = mock_get

    instance = _make_plugin_instance()
    stars_generate_image(
        instance,
        _make_settings("octocat", "someorg/Hello-World"),
        MagicMock(),
    )

    called_url = mock_get.call_args[0][0]
    # Must NOT contain the doubled path  "octocat/someorg/Hello-World"
    assert "octocat/someorg/Hello-World" not in called_url
    # Must contain the correct path
    assert "/repos/someorg/Hello-World" in called_url


@patch("plugins.github.github_stars.get_http_session")
def test_owner_slash_repo_star_count_returned(mock_session):
    """Star count is correctly read when owner/repo format is used."""
    mock_get = MagicMock(return_value=_make_api_response(512))
    mock_session.return_value.get = mock_get

    instance = _make_plugin_instance()
    stars_generate_image(
        instance,
        _make_settings("myuser", "otherowner/myrepo"),
        MagicMock(),
    )

    instance.render_image.assert_called_once()
    _, _, _, template_params = instance.render_image.call_args[0]
    assert template_params["stars"] == 512
    assert template_params["repository"] == "otherowner/myrepo"


@patch("plugins.github.github_stars.get_http_session")
def test_missing_username_raises(mock_session):
    """RuntimeError is raised when username is missing."""
    with pytest.raises(RuntimeError, match="required"):
        stars_generate_image(
            _make_plugin_instance(),
            {"githubUsername": "", "githubRepository": "repo"},
            MagicMock(),
        )


@patch("plugins.github.github_stars.get_http_session")
def test_missing_repository_raises(mock_session):
    """RuntimeError is raised when repository is missing."""
    with pytest.raises(RuntimeError, match="required"):
        stars_generate_image(
            _make_plugin_instance(),
            {"githubUsername": "octocat", "githubRepository": ""},
            MagicMock(),
        )
