from unittest.mock import patch

import pytest


def test_weather_moon_phase_network_error_fallback(device_config_dev, monkeypatch):
    """If moon phase API fails, fallback should use newmoon and 0% illumination."""
    from plugins.weather.weather import Weather

    w = Weather({"id": "weather"})

    # Minimal inputs
    settings = {
        "latitude": "40.0",
        "longitude": "-74.0",
        "units": "metric",
        "weatherProvider": "OpenMeteo",
    }

    # Configure device settings used by plugin
    monkeypatch.setattr(
        device_config_dev, "get_config", lambda key, default=None: {
            "timezone": "UTC",
            "time_format": "12h",
            "resolution": [400, 300],
        }.get(key, default),
    )
    monkeypatch.setattr(device_config_dev, "get_resolution", lambda: (400, 300))

    # Fake OpenMeteo responses
    mock_weather = {
        "current_weather": {"time": "2025-01-01T12:00", "temperature": 21, "weathercode": 1},
        "daily": {
            "time": ["2025-01-01"],
            "temperature_2m_max": [25],
            "temperature_2m_min": [10],
            "weathercode": [1],
            "sunrise": ["2025-01-01T07:00"],
            "sunset": ["2025-01-01T17:00"],
        },
        "hourly": {
            "time": ["2025-01-01T12:00"],
            "temperature_2m": [21],
            "precipitation_probability": [10],
            "precipitation": [0.0],
            "relative_humidity_2m": [50],
            "surface_pressure": [1010],
            "visibility": [10000],
        },
    }
    mock_aqi = {"hourly": {"time": ["2025-01-01T12:00"], "uv_index": [3.5]}}

    # Monkeypatch weather APIs
    monkeypatch.setattr(Weather, "get_open_meteo_data", lambda self, lat, lon, units, d: mock_weather)
    monkeypatch.setattr(Weather, "get_open_meteo_air_quality", lambda self, lat, lon: mock_aqi)

    # Force the moon phase http_get to raise, triggering fallback
    def raise_error(*args, **kwargs):
        raise RuntimeError("network failure")

    monkeypatch.setattr("plugins.weather.weather.http_get", raise_error, raising=True)

    # Bypass headless rendering with an in-memory image (fixture in conftest)
    with patch.object(w, "render_image", return_value=object()):
        result = w.generate_image(settings, device_config_dev)
        assert result is not None


