# pyright: reportMissingImports=false
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image


@pytest.fixture()
def plugin_config():
    return {"id": "github", "class": "GitHub", "name": "GitHub"}


# ---- Router (github.py) ----

def test_github_routes_to_contributions(monkeypatch, plugin_config, device_config_dev):
    from plugins.github.github import GitHub

    monkeypatch.setattr(device_config_dev, "load_env_key", lambda k: "ghp_fake")

    with patch("plugins.github.github.contributions_generate_image") as mock_fn:
        mock_fn.return_value = Image.new("RGB", (800, 480))
        p = GitHub(plugin_config)
        result = p.generate_image(
            {"githubType": "contributions", "githubUsername": "octocat"},
            device_config_dev,
        )
    mock_fn.assert_called_once()
    assert result is not None


def test_github_routes_to_stars(monkeypatch, plugin_config, device_config_dev):
    from plugins.github.github import GitHub

    with patch("plugins.github.github.stars_generate_image") as mock_fn:
        mock_fn.return_value = Image.new("RGB", (800, 480))
        p = GitHub(plugin_config)
        result = p.generate_image(
            {"githubType": "stars", "githubUsername": "octocat", "githubRepository": "Hello-World"},
            device_config_dev,
        )
    mock_fn.assert_called_once()
    assert result is not None


def test_github_routes_to_sponsors(monkeypatch, plugin_config, device_config_dev):
    from plugins.github.github import GitHub

    with patch("plugins.github.github.sponsors_generate_image") as mock_fn:
        mock_fn.return_value = Image.new("RGB", (800, 480))
        p = GitHub(plugin_config)
        result = p.generate_image(
            {"githubType": "sponsors", "githubUsername": "octocat"},
            device_config_dev,
        )
    mock_fn.assert_called_once()
    assert result is not None


def test_github_unknown_type(plugin_config, device_config_dev):
    from plugins.github.github import GitHub

    p = GitHub(plugin_config)
    with pytest.raises(ValueError, match="Unknown GitHub type"):
        p.generate_image({"githubType": "unknown"}, device_config_dev)


# ---- Contributions (github_contributions.py) ----

def _graphql_contributions_response(count=5):
    days = [{"contributionCount": count, "date": f"2025-01-{d:02d}"} for d in range(1, 8)]
    return {
        "data": {
            "user": {
                "contributionsCollection": {
                    "contributionCalendar": {
                        "totalContributions": count * 7,
                        "weeks": [{"contributionDays": days}],
                    }
                }
            }
        }
    }


def test_contributions_success(monkeypatch, plugin_config, device_config_dev):
    from plugins.github.github import GitHub

    monkeypatch.setattr(device_config_dev, "load_env_key", lambda k: "ghp_fake")

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = _graphql_contributions_response()

    with patch("plugins.github.github_contributions.get_http_session") as mock_session_fn:
        mock_session_fn.return_value.post.return_value = mock_resp
        p = GitHub(plugin_config)
        result = p.generate_image(
            {
                "githubType": "contributions",
                "githubUsername": "octocat",
                "contributionColor[]": ["#eee", "#9be9a8", "#40c463", "#30a14e", "#216e39"],
            },
            device_config_dev,
        )
    assert isinstance(result, Image.Image)


def test_contributions_missing_colors_uses_defaults(monkeypatch, plugin_config, device_config_dev):
    """Bug 8: Missing contributionColor[] should use default palette, not crash."""
    from plugins.github.github import GitHub

    monkeypatch.setattr(device_config_dev, "load_env_key", lambda k: "ghp_fake")

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = _graphql_contributions_response()

    with patch("plugins.github.github_contributions.get_http_session") as mock_session_fn:
        mock_session_fn.return_value.post.return_value = mock_resp
        p = GitHub(plugin_config)
        result = p.generate_image(
            {
                "githubType": "contributions",
                "githubUsername": "octocat",
                # No contributionColor[] provided
            },
            device_config_dev,
        )
    assert isinstance(result, Image.Image)


def test_contributions_missing_key(monkeypatch, plugin_config, device_config_dev):
    from plugins.github.github import GitHub

    monkeypatch.setattr(device_config_dev, "load_env_key", lambda k: None)

    p = GitHub(plugin_config)
    with pytest.raises(RuntimeError, match="GitHub API Key not configured"):
        p.generate_image(
            {"githubType": "contributions", "githubUsername": "octocat"},
            device_config_dev,
        )


def test_contributions_missing_username(monkeypatch, plugin_config, device_config_dev):
    from plugins.github.github import GitHub

    monkeypatch.setattr(device_config_dev, "load_env_key", lambda k: "ghp_fake")

    p = GitHub(plugin_config)
    with pytest.raises(RuntimeError, match="username is required"):
        p.generate_image(
            {"githubType": "contributions", "githubUsername": ""},
            device_config_dev,
        )


def test_contributions_api_error(monkeypatch, plugin_config, device_config_dev):
    from plugins.github.github import GitHub
    import requests as req_mod

    monkeypatch.setattr(device_config_dev, "load_env_key", lambda k: "ghp_fake")

    with patch("plugins.github.github_contributions.get_http_session") as mock_session_fn:
        mock_session_fn.return_value.post.side_effect = req_mod.exceptions.HTTPError("Server error")
        p = GitHub(plugin_config)
        with pytest.raises(Exception):
            p.generate_image(
                {
                    "githubType": "contributions",
                    "githubUsername": "octocat",
                    "contributionColor[]": ["#eee", "#aaa", "#888", "#666", "#444"],
                },
                device_config_dev,
            )


def test_contributions_empty_data(monkeypatch, plugin_config, device_config_dev):
    from plugins.github.github import GitHub

    monkeypatch.setattr(device_config_dev, "load_env_key", lambda k: "ghp_fake")

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = _graphql_contributions_response(count=0)

    with patch("plugins.github.github_contributions.get_http_session") as mock_session_fn:
        mock_session_fn.return_value.post.return_value = mock_resp
        p = GitHub(plugin_config)
        result = p.generate_image(
            {
                "githubType": "contributions",
                "githubUsername": "octocat",
                "contributionColor[]": ["#eee", "#9be9a8", "#40c463", "#30a14e", "#216e39"],
            },
            device_config_dev,
        )
    assert isinstance(result, Image.Image)


# ---- Stars (github_stars.py) ----

def test_stars_success(monkeypatch, plugin_config, device_config_dev):
    from plugins.github.github import GitHub

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"stargazers_count": 1234}

    with patch("plugins.github.github_stars.get_http_session") as mock_session_fn:
        mock_session_fn.return_value.get.return_value = mock_resp
        p = GitHub(plugin_config)
        result = p.generate_image(
            {"githubType": "stars", "githubUsername": "octocat", "githubRepository": "Hello-World"},
            device_config_dev,
        )
    assert isinstance(result, Image.Image)


def test_stars_missing_username(plugin_config, device_config_dev):
    from plugins.github.github import GitHub

    p = GitHub(plugin_config)
    with pytest.raises(RuntimeError, match="username and repository are required"):
        p.generate_image(
            {"githubType": "stars", "githubUsername": "", "githubRepository": ""},
            device_config_dev,
        )


def test_stars_http_error(monkeypatch, plugin_config, device_config_dev):
    from plugins.github.github import GitHub

    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_resp.text = "Not Found"

    with patch("plugins.github.github_stars.get_http_session") as mock_session_fn:
        mock_session_fn.return_value.get.return_value = mock_resp
        p = GitHub(plugin_config)
        # fetch_stars returns 0 on error; stars_generate_image still renders
        result = p.generate_image(
            {"githubType": "stars", "githubUsername": "octocat", "githubRepository": "nonexistent"},
            device_config_dev,
        )
    assert isinstance(result, Image.Image)


# ---- Sponsors (github_sponsors.py) ----

def _graphql_sponsors_response():
    return {
        "data": {
            "user": {
                "sponsorshipsAsMaintainer": {
                    "totalCount": 2,
                    "nodes": [
                        {
                            "createdAt": "2024-01-01T00:00:00Z",
                            "sponsorEntity": {"login": "alice", "name": "Alice"},
                            "tier": {"name": "Gold", "monthlyPriceInCents": 1000},
                        },
                        {
                            "createdAt": "2024-06-01T00:00:00Z",
                            "sponsorEntity": {"login": "bob", "name": "Bob"},
                            "tier": {"name": "Silver", "monthlyPriceInCents": 500},
                        },
                    ],
                },
                "estimatedNextSponsorsPayoutInCents": 1500,
            }
        }
    }


def test_sponsors_success(monkeypatch, plugin_config, device_config_dev):
    from plugins.github.github import GitHub

    monkeypatch.setattr(device_config_dev, "load_env_key", lambda k: "ghp_fake")

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = _graphql_sponsors_response()

    with patch("plugins.github.github_sponsors.get_http_session") as mock_session_fn:
        mock_session_fn.return_value.post.return_value = mock_resp
        p = GitHub(plugin_config)
        result = p.generate_image(
            {"githubType": "sponsors", "githubUsername": "octocat"},
            device_config_dev,
        )
    assert isinstance(result, Image.Image)


def test_sponsors_missing_key(monkeypatch, plugin_config, device_config_dev):
    from plugins.github.github import GitHub

    monkeypatch.setattr(device_config_dev, "load_env_key", lambda k: None)

    p = GitHub(plugin_config)
    with pytest.raises(RuntimeError, match="GitHub API Key not configured"):
        p.generate_image(
            {"githubType": "sponsors", "githubUsername": "octocat"},
            device_config_dev,
        )


def test_sponsors_missing_username(monkeypatch, plugin_config, device_config_dev):
    from plugins.github.github import GitHub

    monkeypatch.setattr(device_config_dev, "load_env_key", lambda k: "ghp_fake")

    p = GitHub(plugin_config)
    with pytest.raises(RuntimeError, match="username is required"):
        p.generate_image(
            {"githubType": "sponsors", "githubUsername": ""},
            device_config_dev,
        )


def test_sponsors_api_error(monkeypatch, plugin_config, device_config_dev):
    from plugins.github.github import GitHub

    monkeypatch.setattr(device_config_dev, "load_env_key", lambda k: "ghp_fake")

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"errors": [{"message": "Bad credentials"}]}

    with patch("plugins.github.github_sponsors.get_http_session") as mock_session_fn:
        mock_session_fn.return_value.post.return_value = mock_resp
        p = GitHub(plugin_config)
        with pytest.raises(RuntimeError, match="errors"):
            p.generate_image(
                {"githubType": "sponsors", "githubUsername": "octocat"},
                device_config_dev,
            )
