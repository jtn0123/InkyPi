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

    monkeypatch.setattr("requests.get", raise_error)

    with pytest.raises(RuntimeError, match="request failure"):
        p.generate_image(_base_settings(latitude="999", longitude="999"), cfg)


def test_weather_api_timeout(monkeypatch):
    """requests.get raises Timeout."""
    p = _make_weather_plugin()
    cfg = _make_device_config()

    monkeypatch.setattr(
        "requests.get",
        lambda *a, **kw: (_ for _ in ()).throw(requests.exceptions.Timeout("timed out")),
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

    monkeypatch.setattr("requests.get", lambda *a, **kw: EmptyResp())

    with pytest.raises((RuntimeError, KeyError, AttributeError, TypeError)):
        p.generate_image(_base_settings(), cfg)


def test_weather_openmeteo_timeout(monkeypatch):
    """OpenMeteo provider timeout."""
    p = _make_weather_plugin()
    cfg = _make_device_config()

    monkeypatch.setattr(
        "requests.get",
        lambda *a, **kw: (_ for _ in ()).throw(requests.exceptions.Timeout("timed out")),
    )

    with pytest.raises(RuntimeError, match="request failure"):
        p.generate_image(_base_settings(weatherProvider="OpenMeteo"), cfg)
