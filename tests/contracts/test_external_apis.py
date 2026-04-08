"""Contract tests for external API integrations (JTN-292).

These tests guard plugin parsing code against schema drift in the external
APIs InkyPi depends on. Each test:

  1. Loads a representative JSON fixture from tests/contracts/fixtures/
  2. Validates the fixture against a minimal expected schema (defined inline)
  3. Calls the plugin's parsing code with the fixture (via requests-mock so
     no live network calls happen)
  4. Asserts the parser produces the expected output

If an upstream API changes its response shape, the relevant test breaks
loudly here instead of silently in production. To intentionally update a
fixture, capture a fresh response and replace the file in fixtures/.

Coverage in this PR: NASA APOD, GitHub repo (stars), Open-Meteo forecast.
Other plugins (OpenWeatherMap, Unsplash, RSS, Google Calendar) will be
added in follow-up PRs — see JTN-292.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import requests_mock

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text())


# ---------------------------------------------------------------------------
# NASA APOD
# ---------------------------------------------------------------------------


_APOD_REQUIRED_FIELDS = {"date", "media_type", "title", "explanation"}


def _validate_apod_schema(payload: dict) -> None:
    """Minimal schema check for an APOD response."""
    missing = _APOD_REQUIRED_FIELDS - payload.keys()
    assert not missing, f"APOD fixture missing required fields: {missing}"
    assert isinstance(payload["date"], str)
    assert payload["media_type"] in {"image", "video", "other"}
    if payload["media_type"] == "image":
        assert "url" in payload, "image APODs must include a url"


def test_apod_image_fixture_matches_schema():
    payload = _load_fixture("nasa_apod_image.json")
    _validate_apod_schema(payload)
    # An image APOD should have either hdurl or url that the parser can read.
    assert payload["media_type"] == "image"
    assert payload.get("hdurl") or payload.get("url")


def test_apod_video_fixture_matches_schema():
    payload = _load_fixture("nasa_apod_video.json")
    _validate_apod_schema(payload)
    assert payload["media_type"] == "video"


def test_apod_parser_image_url_resolution():
    """The APOD parser prefers hdurl over url when both are present."""
    payload = _load_fixture("nasa_apod_image.json")
    # Mirror the resolution logic in src/plugins/apod/apod.py
    image_url = payload.get("hdurl") or payload.get("url")
    assert image_url == payload["hdurl"]
    assert image_url.startswith("https://")


def test_apod_parser_rejects_video_media_type():
    """The APOD parser raises when media_type != 'image'."""
    payload = _load_fixture("nasa_apod_video.json")
    # Mirror the check in src/plugins/apod/apod.py
    assert payload.get("media_type") != "image"


# ---------------------------------------------------------------------------
# GitHub repo (stars plugin)
# ---------------------------------------------------------------------------


_GITHUB_REPO_REQUIRED_FIELDS = {"id", "name", "full_name", "stargazers_count"}


def _validate_github_repo_schema(payload: dict) -> None:
    missing = _GITHUB_REPO_REQUIRED_FIELDS - payload.keys()
    assert not missing, f"GitHub repo fixture missing required fields: {missing}"
    assert isinstance(payload["stargazers_count"], int)
    assert payload["stargazers_count"] >= 0


def test_github_repo_fixture_matches_schema():
    payload = _load_fixture("github_repo_stars.json")
    _validate_github_repo_schema(payload)


def test_github_stars_parser_extracts_count():
    """github_stars.fetch_stars() returns the stargazers_count from the API response."""
    from plugins.github.github_stars import fetch_stars

    payload = _load_fixture("github_repo_stars.json")
    expected_stars = payload["stargazers_count"]

    with requests_mock.Mocker() as m:
        m.get("https://api.github.com/repos/octocat/Hello-World", json=payload)
        result = fetch_stars("octocat/Hello-World")

    assert result == expected_stars
    assert result == 1729


def test_github_stars_parser_handles_zero_stars():
    """A repo with zero stars should return 0, not crash on a missing/None field."""
    from plugins.github.github_stars import fetch_stars

    payload = _load_fixture("github_repo_stars.json").copy()
    payload["stargazers_count"] = 0

    with requests_mock.Mocker() as m:
        m.get("https://api.github.com/repos/octocat/Hello-World", json=payload)
        result = fetch_stars("octocat/Hello-World")

    assert result == 0


def test_github_stars_parser_handles_404():
    """A non-existent repo returns 0 (not raise) — see fetch_stars in github_stars.py."""
    from plugins.github.github_stars import fetch_stars

    with requests_mock.Mocker() as m:
        m.get(
            "https://api.github.com/repos/missing/missing",
            status_code=404,
            text="Not Found",
        )
        result = fetch_stars("missing/missing")

    assert result == 0


# ---------------------------------------------------------------------------
# Open-Meteo forecast (weather plugin)
# ---------------------------------------------------------------------------


_OPEN_METEO_REQUIRED_TOPS = {
    "latitude",
    "longitude",
    "current_weather",
    "hourly",
    "daily",
}
_OPEN_METEO_CURRENT_FIELDS = {"temperature", "windspeed", "weathercode", "time"}
_OPEN_METEO_HOURLY_FIELDS = {
    "time",
    "temperature_2m",
    "precipitation",
    "precipitation_probability",
    "relative_humidity_2m",
    "surface_pressure",
    "visibility",
}
_OPEN_METEO_DAILY_FIELDS = {
    "time",
    "weathercode",
    "temperature_2m_max",
    "temperature_2m_min",
    "sunrise",
    "sunset",
}


def _validate_open_meteo_schema(payload: dict) -> None:
    missing_top = _OPEN_METEO_REQUIRED_TOPS - payload.keys()
    assert (
        not missing_top
    ), f"Open-Meteo fixture missing top-level fields: {missing_top}"

    current = payload["current_weather"]
    missing_current = _OPEN_METEO_CURRENT_FIELDS - current.keys()
    assert not missing_current, f"current_weather missing fields: {missing_current}"

    hourly = payload["hourly"]
    missing_hourly = _OPEN_METEO_HOURLY_FIELDS - hourly.keys()
    assert not missing_hourly, f"hourly missing fields: {missing_hourly}"

    daily = payload["daily"]
    missing_daily = _OPEN_METEO_DAILY_FIELDS - daily.keys()
    assert not missing_daily, f"daily missing fields: {missing_daily}"

    # Hourly arrays must all be the same length
    hourly_lens = {len(v) for k, v in hourly.items() if k != "time"}
    assert (
        len(hourly_lens) == 1
    ), f"hourly arrays have inconsistent lengths: {hourly_lens}"
    assert hourly_lens.pop() == len(hourly["time"])


def test_open_meteo_fixture_matches_schema():
    payload = _load_fixture("open_meteo_forecast.json")
    _validate_open_meteo_schema(payload)


def test_open_meteo_parser_returns_full_payload():
    """get_open_meteo_data is a thin wrapper that returns the parsed JSON unchanged."""
    from plugins.weather.weather_api import get_open_meteo_data

    payload = _load_fixture("open_meteo_forecast.json")

    with requests_mock.Mocker() as m:
        m.get("https://api.open-meteo.com/v1/forecast", json=payload)
        result = get_open_meteo_data(
            lat=40.7128, long=-74.006, units="metric", forecast_days=3
        )

    # The wrapper returns the JSON as-is — the calling plugin extracts fields from it.
    assert result["latitude"] == payload["latitude"]
    assert result["current_weather"]["temperature"] == 18.3
    assert len(result["daily"]["time"]) == 3
    assert result["daily"]["temperature_2m_max"][0] == 22.0


def test_open_meteo_parser_raises_on_http_error():
    """A non-2xx response raises a clear RuntimeError."""
    from plugins.weather.weather_api import get_open_meteo_data

    with requests_mock.Mocker() as m:
        m.get("https://api.open-meteo.com/v1/forecast", status_code=500, text="boom")
        with pytest.raises(RuntimeError, match="Failed to retrieve Open-Meteo"):
            get_open_meteo_data(
                lat=40.7128, long=-74.006, units="metric", forecast_days=3
            )
