"""Tests for scripts/validate_api_keys.py."""

from __future__ import annotations

import json
import os
import sys

import pytest

# ---------------------------------------------------------------------------
# Import helper — the script lives in scripts/, not on sys.path by default
# ---------------------------------------------------------------------------
_SCRIPTS_DIR = os.path.join(os.path.dirname(__file__), "..", "scripts")
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

import validate_api_keys as vak  # noqa: E402  (import after path manipulation)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def device_json(tmp_path):
    """Create a minimal device.json with weather + ai_image plugins configured."""
    config = {
        "name": "Test Device",
        "display_type": "mock",
        "resolution": [800, 480],
        "orientation": "horizontal",
        "playlist_config": {
            "playlists": [
                {
                    "name": "Default",
                    "plugins": [
                        {"plugin_id": "weather", "plugin_settings": {}},
                        {"plugin_id": "ai_image", "plugin_settings": {}},
                        {"plugin_id": "unsplash", "plugin_settings": {}},
                        {"plugin_id": "apod", "plugin_settings": {}},
                        {"plugin_id": "github", "plugin_settings": {}},
                    ],
                }
            ]
        },
    }
    p = tmp_path / "device.json"
    p.write_text(json.dumps(config))
    return str(p)


@pytest.fixture()
def empty_device_json(tmp_path):
    """A device.json with no plugins configured."""
    config = {
        "name": "Empty",
        "display_type": "mock",
        "resolution": [800, 480],
        "orientation": "horizontal",
        "playlist_config": {"playlists": [{"name": "Default", "plugins": []}]},
    }
    p = tmp_path / "device.json"
    p.write_text(json.dumps(config))
    return str(p)


@pytest.fixture()
def env_file(tmp_path):
    """Create a .env file with keys for all supported plugins."""
    content = (
        "OPENWEATHER_API_KEY=owm_test_key\n"
        "OPEN_AI_SECRET=sk-test-openai\n"
        "GOOGLE_AI_SECRET=gai-test-key\n"
        "UNSPLASH_ACCESS_KEY=unsplash-test\n"
        "NASA_SECRET=nasa-test\n"
        "GITHUB_SECRET=ghp_testtoken\n"
    )
    p = tmp_path / ".env"
    p.write_text(content)
    return str(p)


@pytest.fixture()
def empty_env_file(tmp_path):
    """Empty .env — no keys at all."""
    p = tmp_path / ".env"
    p.write_text("")
    return str(p)


# ---------------------------------------------------------------------------
# Unit tests — _load_env_file
# ---------------------------------------------------------------------------


def test_load_env_file_parses_entries(tmp_path):
    f = tmp_path / ".env"
    f.write_text("KEY1=val1\nKEY2=val2\n")
    result = vak._load_env_file(str(f))
    assert result["KEY1"] == "val1"
    assert result["KEY2"] == "val2"


def test_load_env_file_strips_quotes(tmp_path):
    f = tmp_path / ".env"
    f.write_text('KEY="quoted_value"\n')
    result = vak._load_env_file(str(f))
    assert result["KEY"] == "quoted_value"


def test_load_env_file_ignores_comments(tmp_path):
    f = tmp_path / ".env"
    f.write_text("# comment\nKEY=value\n")
    result = vak._load_env_file(str(f))
    assert "# comment" not in result
    assert result["KEY"] == "value"


def test_load_env_file_missing_returns_empty(tmp_path):
    result = vak._load_env_file(str(tmp_path / "nonexistent.env"))
    assert result == {}


# ---------------------------------------------------------------------------
# Unit tests — _extract_configured_plugin_ids
# ---------------------------------------------------------------------------


def test_extract_configured_plugin_ids():
    config = {
        "playlist_config": {
            "playlists": [
                {
                    "plugins": [
                        {"plugin_id": "weather"},
                        {"plugin_id": "clock"},
                    ]
                }
            ]
        }
    }
    ids = vak._extract_configured_plugin_ids(config)
    assert "weather" in ids
    assert "clock" in ids


def test_extract_configured_plugin_ids_empty():
    config = {"playlist_config": {"playlists": []}}
    assert vak._extract_configured_plugin_ids(config) == set()


# ---------------------------------------------------------------------------
# Probe function tests — using requests_mock
# ---------------------------------------------------------------------------


def test_probe_openweathermap_ok(requests_mock):
    requests_mock.get(
        "https://api.openweathermap.org/geo/1.0/reverse",
        json=[{"name": "London"}],
        status_code=200,
    )
    status, msg = vak._probe_openweathermap("valid_key", timeout=5)
    assert status == vak.STATUS_OK


def test_probe_openweathermap_invalid(requests_mock):
    requests_mock.get(
        "https://api.openweathermap.org/geo/1.0/reverse",
        json={"message": "Invalid API key"},
        status_code=401,
    )
    status, msg = vak._probe_openweathermap("bad_key", timeout=5)
    assert status == vak.STATUS_INVALID


def test_probe_openweathermap_quota(requests_mock):
    requests_mock.get(
        "https://api.openweathermap.org/geo/1.0/reverse",
        status_code=429,
    )
    status, msg = vak._probe_openweathermap("any_key", timeout=5)
    assert status == vak.STATUS_QUOTA


def test_probe_openweathermap_network_error(requests_mock):
    import requests

    requests_mock.get(
        "https://api.openweathermap.org/geo/1.0/reverse",
        exc=requests.exceptions.ConnectionError("connection refused"),
    )
    status, msg = vak._probe_openweathermap("any_key", timeout=5)
    assert status == vak.STATUS_NETWORK_ERROR


def test_probe_openai_ok(requests_mock):
    requests_mock.get(
        "https://api.openai.com/v1/models",
        json={"data": []},
        status_code=200,
    )
    status, _ = vak._probe_openai("sk-valid", timeout=5)
    assert status == vak.STATUS_OK


def test_probe_openai_invalid(requests_mock):
    requests_mock.get(
        "https://api.openai.com/v1/models",
        json={"error": {"message": "Incorrect API key"}},
        status_code=401,
    )
    status, _ = vak._probe_openai("sk-bad", timeout=5)
    assert status == vak.STATUS_INVALID


def test_probe_openai_quota(requests_mock):
    requests_mock.get(
        "https://api.openai.com/v1/models",
        status_code=429,
    )
    status, _ = vak._probe_openai("sk-any", timeout=5)
    assert status == vak.STATUS_QUOTA


def test_probe_openai_network_error(requests_mock):
    import requests

    requests_mock.get(
        "https://api.openai.com/v1/models",
        exc=requests.exceptions.ConnectionError("no internet"),
    )
    status, _ = vak._probe_openai("sk-any", timeout=5)
    assert status == vak.STATUS_NETWORK_ERROR


def test_probe_google_ai_ok(requests_mock):
    requests_mock.get(
        "https://generativelanguage.googleapis.com/v1beta/models",
        json={"models": []},
        status_code=200,
    )
    status, _ = vak._probe_google_ai("gai-valid", timeout=5)
    assert status == vak.STATUS_OK


def test_probe_google_ai_invalid(requests_mock):
    requests_mock.get(
        "https://generativelanguage.googleapis.com/v1beta/models",
        json={"error": {"status": "PERMISSION_DENIED"}},
        status_code=403,
    )
    status, _ = vak._probe_google_ai("gai-bad", timeout=5)
    assert status == vak.STATUS_INVALID


def test_probe_unsplash_ok(requests_mock):
    requests_mock.get(
        "https://api.unsplash.com/photos/random",
        json=[{"id": "abc"}],
        status_code=200,
    )
    status, _ = vak._probe_unsplash("unsplash-valid", timeout=5)
    assert status == vak.STATUS_OK


def test_probe_unsplash_invalid(requests_mock):
    requests_mock.get(
        "https://api.unsplash.com/photos/random",
        json={"errors": ["OAuth error: The access token is invalid."]},
        status_code=401,
    )
    status, _ = vak._probe_unsplash("unsplash-bad", timeout=5)
    assert status == vak.STATUS_INVALID


def test_probe_unsplash_network_error(requests_mock):
    import requests

    requests_mock.get(
        "https://api.unsplash.com/photos/random",
        exc=requests.exceptions.Timeout(),
    )
    status, _ = vak._probe_unsplash("any", timeout=5)
    assert status == vak.STATUS_NETWORK_ERROR


def test_probe_nasa_ok(requests_mock):
    requests_mock.get(
        "https://api.nasa.gov/planetary/apod",
        json={"media_type": "image", "url": "https://example.com/img.jpg"},
        status_code=200,
    )
    status, _ = vak._probe_nasa("nasa-valid", timeout=5)
    assert status == vak.STATUS_OK


def test_probe_nasa_invalid(requests_mock):
    requests_mock.get(
        "https://api.nasa.gov/planetary/apod",
        json={"error": {"code": "API_KEY_INVALID"}},
        status_code=403,
    )
    status, _ = vak._probe_nasa("nasa-bad", timeout=5)
    assert status == vak.STATUS_INVALID


def test_probe_github_ok(requests_mock):
    requests_mock.get(
        "https://api.github.com/user",
        json={"login": "testuser"},
        status_code=200,
    )
    status, _ = vak._probe_github("ghp_valid", timeout=5)
    assert status == vak.STATUS_OK


def test_probe_github_invalid(requests_mock):
    requests_mock.get(
        "https://api.github.com/user",
        json={"message": "Bad credentials"},
        status_code=401,
    )
    status, _ = vak._probe_github("ghp_bad", timeout=5)
    assert status == vak.STATUS_INVALID


def test_probe_github_network_error(requests_mock):
    import requests

    requests_mock.get(
        "https://api.github.com/user",
        exc=requests.exceptions.ConnectionError("DNS failure"),
    )
    status, _ = vak._probe_github("ghp_any", timeout=5)
    assert status == vak.STATUS_NETWORK_ERROR


# ---------------------------------------------------------------------------
# run_probes integration tests
# ---------------------------------------------------------------------------


def test_run_probes_all_ok(requests_mock):
    """All probes return 200 → all results OK."""
    requests_mock.get(
        "https://api.openweathermap.org/geo/1.0/reverse", json=[], status_code=200
    )
    requests_mock.get(
        "https://api.openai.com/v1/models", json={"data": []}, status_code=200
    )
    requests_mock.get(
        "https://generativelanguage.googleapis.com/v1beta/models",
        json={"models": []},
        status_code=200,
    )
    requests_mock.get(
        "https://api.unsplash.com/photos/random", json=[{}], status_code=200
    )
    requests_mock.get(
        "https://api.nasa.gov/planetary/apod",
        json={"media_type": "image"},
        status_code=200,
    )
    requests_mock.get(
        "https://api.github.com/user", json={"login": "u"}, status_code=200
    )

    env_keys = {
        "OPENWEATHER_API_KEY": "owmkey",
        "OPEN_AI_SECRET": "sk-key",
        "GOOGLE_AI_SECRET": "gaikey",
        "UNSPLASH_ACCESS_KEY": "ukey",
        "NASA_SECRET": "nkey",
        "GITHUB_SECRET": "ghpkey",
    }
    configured = {"weather", "ai_image", "unsplash", "apod", "github"}
    results = vak.run_probes(env_keys, configured, plugin_filter=None, timeout=5)
    statuses = {r["status"] for r in results}
    assert vak.STATUS_OK in statuses
    assert vak.STATUS_INVALID not in statuses


def test_run_probes_skips_unconfigured_missing_key():
    """Plugin configured but key absent → Skipped."""
    env_keys: dict[str, str] = {}  # no keys
    configured = {"weather"}
    results = vak.run_probes(env_keys, configured, plugin_filter=None, timeout=5)
    weather_results = [r for r in results if r["plugin"] == "weather"]
    assert weather_results
    assert all(r["status"] == vak.STATUS_SKIPPED for r in weather_results)


def test_run_probes_empty_config_empty_env():
    """No configured plugins, no keys → no results."""
    env_keys: dict[str, str] = {}
    configured: set[str] = set()
    results = vak.run_probes(env_keys, configured, plugin_filter=None, timeout=5)
    assert results == []


def test_run_probes_plugin_filter(requests_mock):
    """--plugin filter limits output to that plugin only."""
    requests_mock.get(
        "https://api.nasa.gov/planetary/apod",
        json={"media_type": "image"},
        status_code=200,
    )
    env_keys = {"NASA_SECRET": "nkey"}
    configured = {"weather", "apod", "github"}
    results = vak.run_probes(env_keys, configured, plugin_filter="apod", timeout=5)
    assert all(r["plugin"] == "apod" for r in results)
    assert len(results) == 1


# ---------------------------------------------------------------------------
# Exit code tests
# ---------------------------------------------------------------------------


def test_exit_code_all_ok():
    results = [
        {"status": vak.STATUS_OK, "plugin": "x", "service": "S", "message": ""},
        {"status": vak.STATUS_SKIPPED, "plugin": "y", "service": "T", "message": ""},
    ]
    assert vak._exit_code(results) == 0


def test_exit_code_invalid():
    results = [
        {"status": vak.STATUS_INVALID, "plugin": "x", "service": "S", "message": ""},
    ]
    assert vak._exit_code(results) == 1


def test_exit_code_network_error():
    results = [
        {
            "status": vak.STATUS_NETWORK_ERROR,
            "plugin": "x",
            "service": "S",
            "message": "",
        },
    ]
    assert vak._exit_code(results) == 2


def test_exit_code_empty():
    assert vak._exit_code([]) == 0


# ---------------------------------------------------------------------------
# CLI (main) integration tests
# ---------------------------------------------------------------------------


def test_main_missing_config_returns_2(tmp_path):
    code = vak.main(["--config", str(tmp_path / "nonexistent.json")])
    assert code == 2


def test_main_json_output(tmp_path, requests_mock, device_json, env_file):
    """--json flag produces valid JSON list."""
    # Mock all external endpoints as OK
    requests_mock.get(
        "https://api.openweathermap.org/geo/1.0/reverse", json=[], status_code=200
    )
    requests_mock.get(
        "https://api.openai.com/v1/models", json={"data": []}, status_code=200
    )
    requests_mock.get(
        "https://generativelanguage.googleapis.com/v1beta/models",
        json={},
        status_code=200,
    )
    requests_mock.get(
        "https://api.unsplash.com/photos/random", json=[{}], status_code=200
    )
    requests_mock.get(
        "https://api.nasa.gov/planetary/apod",
        json={"media_type": "image"},
        status_code=200,
    )
    requests_mock.get(
        "https://api.github.com/user", json={"login": "u"}, status_code=200
    )

    import io
    from unittest.mock import patch

    output = io.StringIO()
    with patch(
        "builtins.print", side_effect=lambda *a, **kw: output.write(str(a[0]) + "\n")
    ):
        code = vak.main(
            ["--config", device_json, "--env", env_file, "--json", "--timeout", "5"]
        )

    assert code == 0
    printed = output.getvalue()
    parsed = json.loads(printed)
    assert isinstance(parsed, list)
    assert len(parsed) > 0


def test_main_all_invalid_exits_1(tmp_path, requests_mock, device_json, env_file):
    """If all probes return 401, main exits with code 1."""
    requests_mock.get("https://api.openweathermap.org/geo/1.0/reverse", status_code=401)
    requests_mock.get("https://api.openai.com/v1/models", status_code=401)
    requests_mock.get(
        "https://generativelanguage.googleapis.com/v1beta/models", status_code=401
    )
    requests_mock.get("https://api.unsplash.com/photos/random", status_code=401)
    requests_mock.get("https://api.nasa.gov/planetary/apod", status_code=401)
    requests_mock.get("https://api.github.com/user", status_code=401)

    from unittest.mock import patch

    with patch("builtins.print"):
        code = vak.main(["--config", device_json, "--env", env_file, "--timeout", "5"])
    assert code == 1


def test_main_empty_config_exits_0(tmp_path, empty_device_json, empty_env_file):
    """Empty config + empty .env → exit 0, no probes run."""
    from unittest.mock import patch

    with patch("builtins.print"):
        code = vak.main(
            ["--config", empty_device_json, "--env", empty_env_file, "--timeout", "5"]
        )
    assert code == 0


def test_main_unknown_plugin_skipped(tmp_path, requests_mock):
    """Plugin IDs with no probe definition produce no output (skipped silently)."""
    config = {
        "name": "T",
        "display_type": "mock",
        "resolution": [800, 480],
        "orientation": "horizontal",
        "playlist_config": {
            "playlists": [{"name": "D", "plugins": [{"plugin_id": "clock"}]}]
        },
    }
    cfg_path = tmp_path / "device.json"
    cfg_path.write_text(json.dumps(config))
    env_path = tmp_path / ".env"
    env_path.write_text("")

    from unittest.mock import patch

    with patch("builtins.print"):
        code = vak.main(
            ["--config", str(cfg_path), "--env", str(env_path), "--timeout", "5"]
        )
    assert code == 0
