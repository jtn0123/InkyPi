# pyright: reportMissingImports=false
"""Error scenario tests for the Weather plugin."""
from unittest.mock import MagicMock

import pytest
import requests


def _make_weather_plugin():
    from plugins.weather.weather import Weather

    return Weather({"id": "weather"})


def _make_device_config(api_key="fake_key"):
    cfg = MagicMock()
    cfg.get_resolution.return_value = (800, 480)
    cfg.get_config.side_effect = lambda key, default=None: {
        "orientation": "horizontal",
        "timezone": "UTC",
        "time_format": "12h",
    }.get(key, default)
    cfg.load_env_key.return_value = api_key
    return cfg


def _base_settings(**overrides):
    settings = {
        "latitude": "40.7128",
        "longitude": "-74.0060",
        "units": "metric",
        "weatherProvider": "OpenWeatherMap",
    }
    settings.update(overrides)
    return settings


def test_weather_invalid_coordinates(monkeypatch):
    """lat=999, lon=999 should still attempt API call and fail."""
    p = _make_weather_plugin()
    cfg = _make_device_config()

    def raise_error(*args, **kwargs):
        raise requests.exceptions.HTTPError("400 Bad Request")

    mock_session = type("S", (), {"get": staticmethod(raise_error)})()
    monkeypatch.setattr(
        "plugins.weather.weather_api.get_http_session", lambda: mock_session
    )

    with pytest.raises(RuntimeError, match="request failure"):
        p.generate_image(_base_settings(latitude="999", longitude="999"), cfg)


def test_weather_api_timeout(monkeypatch):
    """requests.get raises Timeout."""
    p = _make_weather_plugin()
    cfg = _make_device_config()

    def timeout_fn(*a, **kw):
        raise requests.exceptions.Timeout("timed out")

    mock_session = type("S", (), {"get": staticmethod(timeout_fn)})()
    monkeypatch.setattr(
        "plugins.weather.weather_api.get_http_session", lambda: mock_session
    )

    with pytest.raises(RuntimeError, match="request failure"):
        p.generate_image(_base_settings(), cfg)


def test_weather_malformed_response(monkeypatch):
    """200 OK but empty/malformed JSON body."""
    p = _make_weather_plugin()
    cfg = _make_device_config()

    class EmptyResp:
        status_code = 200

        def json(self):
            return {}

        def raise_for_status(self):
            pass

    mock_session = type("S", (), {"get": staticmethod(lambda *a, **kw: EmptyResp())})()
    monkeypatch.setattr(
        "plugins.weather.weather_api.get_http_session", lambda: mock_session
    )

    with pytest.raises((RuntimeError, KeyError, AttributeError, TypeError)):
        p.generate_image(_base_settings(), cfg)


def test_weather_realistic_response_shape(monkeypatch, realistic_weather_response):
    """Verify the realistic weather fixture has the expected structure."""
    resp = realistic_weather_response
    assert "current" in resp
    assert "daily" in resp
    assert "hourly" in resp
    assert resp["current"]["weather"][0]["main"] == "Clouds"
    assert len(resp["daily"]) == 7
    assert len(resp["hourly"]) == 24


def test_weather_openmeteo_timeout(monkeypatch):
    """OpenMeteo provider timeout."""
    p = _make_weather_plugin()
    cfg = _make_device_config()

    def timeout_fn(*a, **kw):
        raise requests.exceptions.Timeout("timed out")

    mock_session = type("S", (), {"get": staticmethod(timeout_fn)})()
    monkeypatch.setattr(
        "plugins.weather.weather_api.get_http_session", lambda: mock_session
    )

    with pytest.raises(RuntimeError, match="request failure"):
        p.generate_image(_base_settings(weatherProvider="OpenMeteo"), cfg)
