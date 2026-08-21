# pyright: reportMissingImports=false
"""Error scenario tests for the Weather plugin."""

from typing import Any
from unittest.mock import MagicMock

import pytest
import requests


def _make_weather_plugin() -> Any:
    from plugins.weather.weather import Weather

    return Weather({"id": "weather"})


def _make_device_config(api_key: Any = "fake_key") -> Any:
    cfg = MagicMock()
    cfg.get_resolution.return_value = (800, 480)
    cfg.get_config.side_effect = lambda key, default=None: {
        "orientation": "horizontal",
        "timezone": "UTC",
        "time_format": "12h",
    }.get(key, default)
    cfg.load_env_key.return_value = api_key
    return cfg


def _base_settings(**overrides: Any) -> Any:
    settings = {
        "latitude": "40.7128",
        "longitude": "-74.0060",
        "units": "metric",
        "weatherProvider": "OpenWeatherMap",
    }
    settings.update(overrides)
    return settings


def test_weather_invalid_coordinates(monkeypatch: pytest.MonkeyPatch) -> None:
    """lat=999, lon=999 should still attempt API call and fail."""
    p = _make_weather_plugin()
    cfg = _make_device_config()

    def raise_error(*args: Any, **kwargs: Any) -> None:
        raise requests.exceptions.HTTPError("400 Bad Request")

    mock_session = type("S", (), {"get": staticmethod(raise_error)})()
    monkeypatch.setattr(
        "plugins.weather.weather_api.get_http_session", lambda: mock_session
    )

    with pytest.raises(RuntimeError, match="request failure"):
        p.generate_image(_base_settings(latitude="999", longitude="999"), cfg)


def test_weather_api_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """requests.get raises Timeout."""
    p = _make_weather_plugin()
    cfg = _make_device_config()

    def timeout_fn(*a: Any, **kw: Any) -> None:
        raise requests.exceptions.Timeout("timed out")

    mock_session = type("S", (), {"get": staticmethod(timeout_fn)})()
    monkeypatch.setattr(
        "plugins.weather.weather_api.get_http_session", lambda: mock_session
    )

    with pytest.raises(RuntimeError, match="request failure"):
        p.generate_image(_base_settings(), cfg)


def test_weather_malformed_response(monkeypatch: pytest.MonkeyPatch) -> Any:
    """200 OK but empty/malformed JSON body."""
    p = _make_weather_plugin()
    cfg = _make_device_config()

    class EmptyResp:
        status_code = 200

        def json(self) -> Any:
            return {}

        def raise_for_status(self) -> None:
            pass

    mock_session = type("S", (), {"get": staticmethod(lambda *a, **kw: EmptyResp())})()
    monkeypatch.setattr(
        "plugins.weather.weather_api.get_http_session", lambda: mock_session
    )

    with pytest.raises((RuntimeError, KeyError, AttributeError, TypeError)):
        p.generate_image(_base_settings(), cfg)


def test_weather_realistic_response_shape(
    monkeypatch: pytest.MonkeyPatch, realistic_weather_response: Any
) -> None:
    """Verify the realistic weather fixture has the expected structure."""
    resp = realistic_weather_response
    assert "current" in resp
    assert "daily" in resp
    assert "hourly" in resp
    assert resp["current"]["weather"][0]["main"] == "Clouds"
    assert len(resp["daily"]) == 7
    assert len(resp["hourly"]) == 24


def test_weather_openmeteo_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """OpenMeteo provider timeout."""
    p = _make_weather_plugin()
    cfg = _make_device_config()

    def timeout_fn(*a: Any, **kw: Any) -> None:
        raise requests.exceptions.Timeout("timed out")

    mock_session = type("S", (), {"get": staticmethod(timeout_fn)})()
    monkeypatch.setattr(
        "plugins.weather.weather_api.get_http_session", lambda: mock_session
    )

    with pytest.raises(RuntimeError, match="request failure"):
        p.generate_image(_base_settings(weatherProvider="OpenMeteo"), cfg)
