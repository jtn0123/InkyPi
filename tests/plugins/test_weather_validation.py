# pyright: reportMissingImports=false
"""Input validation tests (location, units, API key, provider)."""

from unittest.mock import MagicMock

import pytest


def test_weather_provider_validation():
    """Test weather provider validation."""
    from plugins.weather.weather import Weather

    weather = Weather({"id": "weather"})

    # Test invalid provider
    settings = {
        "latitude": "40.0",
        "longitude": "-74.0",
        "units": "metric",
        "weatherProvider": "InvalidProvider",
    }
    device_config = MagicMock()
    device_config.get_config.return_value = "UTC"
    device_config.load_env_key.return_value = "fake_key"

    try:
        weather.generate_image(settings, device_config)
        assert False, "Should have raised RuntimeError"
    except RuntimeError as e:
        assert "Unknown weather provider" in str(e)


def test_weather_units_validation():
    """Test weather units validation."""
    from plugins.weather.weather import Weather

    weather = Weather({"id": "weather"})

    # Test invalid units
    settings = {
        "latitude": "40.0",
        "longitude": "-74.0",
        "units": "invalid_units",
        "weatherProvider": "OpenWeatherMap",
    }
    device_config = MagicMock()
    device_config.get_config.return_value = "UTC"
    device_config.load_env_key.return_value = "fake_key"

    try:
        weather.generate_image(settings, device_config)
        assert False, "Should have raised RuntimeError"
    except RuntimeError as e:
        assert "Units are required" in str(e)


def test_weather_location_validation():
    """Test weather location validation."""
    from plugins.weather.weather import Weather

    weather = Weather({"id": "weather"})

    # Test missing latitude
    settings = {
        "longitude": "-74.0",
        "units": "metric",
        "weatherProvider": "OpenWeatherMap",
    }
    device_config = MagicMock()
    device_config.get_config.return_value = "UTC"

    with pytest.raises(RuntimeError, match="required"):
        weather.generate_image(settings, device_config)


def test_weather_api_key_validation():
    """Test weather API key validation."""
    from plugins.weather.weather import Weather

    weather = Weather({"id": "weather"})

    # Test missing API key
    settings = {
        "latitude": "40.0",
        "longitude": "-74.0",
        "units": "metric",
        "weatherProvider": "OpenWeatherMap",
    }
    device_config = MagicMock()
    device_config.get_config.return_value = "UTC"
    device_config.load_env_key.return_value = None

    try:
        weather.generate_image(settings, device_config)
        assert False, "Should have raised RuntimeError"
    except RuntimeError as e:
        assert "OpenWeatherMap API Key not configured" in str(e)


def test_weather_missing_api_key(device_config_dev, monkeypatch):
    """Test weather plugin with missing API key."""
    from plugins.weather.weather import Weather

    p = Weather({"id": "weather"})
    # Mock load_env_key to return None to simulate missing API key
    monkeypatch.setattr(device_config_dev, "load_env_key", lambda key: None)

    settings = {
        "latitude": "40.7128",
        "longitude": "-74.0060",
        "units": "metric",
        "weatherProvider": "OpenWeatherMap",
    }

    with pytest.raises(RuntimeError, match="OpenWeatherMap API Key not configured"):
        p.generate_image(settings, device_config_dev)


def test_weather_missing_coordinates_raises(device_config_dev):
    """Bug 9: Missing lat/long should raise RuntimeError, not TypeError from float(None)."""
    from plugins.weather.weather import Weather

    p = Weather({"id": "weather"})
    settings = {"units": "metric", "weatherProvider": "OpenWeatherMap"}

    with pytest.raises(RuntimeError, match="required"):
        p.generate_image(settings, device_config_dev)


def test_weather_invalid_coordinates_raises(device_config_dev):
    """Bug 9: Non-numeric lat/long should raise RuntimeError."""
    from plugins.weather.weather import Weather

    p = Weather({"id": "weather"})
    settings = {
        "latitude": "not_a_number",
        "longitude": "abc",
        "units": "metric",
        "weatherProvider": "OpenWeatherMap",
    }

    with pytest.raises(RuntimeError, match="valid numbers"):
        p.generate_image(settings, device_config_dev)


def test_weather_invalid_units(device_config_dev):
    """Test weather plugin with invalid units."""
    from plugins.weather.weather import Weather

    p = Weather({"id": "weather"})
    settings = {
        "latitude": "40.7128",
        "longitude": "-74.0060",
        "units": "invalid",
        "weatherProvider": "OpenWeatherMap",
    }

    with pytest.raises(RuntimeError, match="Units are required"):
        p.generate_image(settings, device_config_dev)


def test_weather_unknown_provider(device_config_dev, monkeypatch):
    """Test weather plugin with unknown provider."""
    from plugins.weather.weather import Weather

    p = Weather({"id": "weather"})

    # Mock API key
    monkeypatch.setattr(device_config_dev, "load_env_key", lambda key: "fake_key")

    settings = {
        "latitude": "40.7128",
        "longitude": "-74.0060",
        "units": "metric",
        "weatherProvider": "UnknownProvider",
    }

    with pytest.raises(RuntimeError, match="Unknown weather provider"):
        p.generate_image(settings, device_config_dev)
