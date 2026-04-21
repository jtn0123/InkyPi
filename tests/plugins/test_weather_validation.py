# pyright: reportMissingImports=false
"""Input validation tests (location, units, API key, provider)."""

from unittest.mock import MagicMock, patch

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


def test_weather_units_invalid_falls_back_to_imperial():
    """JTN-784: invalid `units` fall back to imperial at render time so a bare
    /update_now produces a render. Form-level validation (validate_settings)
    enforces the allowed set on save."""
    from plugins.weather.weather import Weather

    weather = Weather({"id": "weather"})
    settings = {
        "latitude": "40.0",
        "longitude": "-74.0",
        "units": "invalid_units",
        "weatherProvider": "OpenMeteo",
    }
    device_config = MagicMock()
    device_config.get_config.return_value = "UTC"
    device_config.load_env_key.return_value = None
    device_config.get_resolution.return_value = (800, 480)

    # OpenMeteo path with no key; stub network + render so the assertion is
    # about *which units the render path used*, not network behaviour.
    with (
        patch.object(Weather, "get_open_meteo_data", return_value={}) as m_data,
        patch.object(Weather, "get_open_meteo_air_quality", return_value={}),
        patch.object(
            Weather,
            "parse_open_meteo_data",
            return_value={"dt": 0, "title": "-"},
        ),
        patch.object(Weather, "render_image", return_value=object()),
        patch.object(Weather, "_request_timeout", return_value=None),
        patch.object(Weather, "get_plugin_dir", return_value=""),
    ):
        weather.generate_image(settings, device_config)

    args, _kwargs = m_data.call_args
    # Signature: get_open_meteo_data(self, lat, long, units, forecast_days)
    assert args[2] == "imperial"


def test_weather_missing_latitude_falls_back_to_default():
    """JTN-784: missing lat/lon default to NYC coords at render time."""
    from plugins.weather.weather import Weather

    weather = Weather({"id": "weather"})
    settings = {
        "longitude": "-74.0",
        "units": "metric",
        "weatherProvider": "OpenMeteo",
    }
    device_config = MagicMock()
    device_config.get_config.return_value = "UTC"
    device_config.load_env_key.return_value = None
    device_config.get_resolution.return_value = (800, 480)

    with (
        patch.object(Weather, "get_open_meteo_data", return_value={}) as m_data,
        patch.object(Weather, "get_open_meteo_air_quality", return_value={}),
        patch.object(
            Weather,
            "parse_open_meteo_data",
            return_value={"dt": 0, "title": "-"},
        ),
        patch.object(Weather, "render_image", return_value=object()),
        patch.object(Weather, "_request_timeout", return_value=None),
        patch.object(Weather, "get_plugin_dir", return_value=""),
    ):
        weather.generate_image(settings, device_config)

    args, _kwargs = m_data.call_args
    # patched classmethod Mock sees (lat, long, units, forecast_days) without self.
    assert args[0] == pytest.approx(40.7128)  # default latitude (NYC)


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


def test_weather_missing_coordinates_falls_back_to_default(device_config_dev):
    """JTN-784: missing lat/long no longer raise — defaults (NYC) are applied.
    Bug 9 regression (TypeError from ``float(None)``) is still covered by
    ``test_weather_invalid_coordinates_raises`` below, which exercises the
    ``float()`` path with non-numeric values."""
    from plugins.weather.weather import Weather

    p = Weather({"id": "weather"})
    settings = {"units": "metric", "weatherProvider": "OpenMeteo"}

    with (
        patch.object(Weather, "get_open_meteo_data", return_value={}) as m_data,
        patch.object(Weather, "get_open_meteo_air_quality", return_value={}),
        patch.object(
            Weather,
            "parse_open_meteo_data",
            return_value={"dt": 0, "title": "-"},
        ),
        patch.object(Weather, "render_image", return_value=object()),
        patch.object(Weather, "_request_timeout", return_value=None),
        patch.object(Weather, "get_plugin_dir", return_value=""),
    ):
        p.generate_image(settings, device_config_dev)
    args, _kwargs = m_data.call_args
    assert args[0] == pytest.approx(40.7128)
    assert args[1] == pytest.approx(-74.0060)


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


def test_weather_validate_settings_rejects_out_of_range_latitude():
    """JTN-354: validate_settings must reject latitudes outside [-90, 90]."""
    from plugins.weather.weather import Weather

    p = Weather({"id": "weather"})

    for bad_lat in ("999.999", "91", "-91", "9999", "-90.0001", "90.0001"):
        err = p.validate_settings({"latitude": bad_lat, "longitude": "-74.0"})
        assert err is not None
        assert "Latitude" in err


def test_weather_validate_settings_rejects_out_of_range_longitude():
    """JTN-354: validate_settings must reject longitudes outside [-180, 180]."""
    from plugins.weather.weather import Weather

    p = Weather({"id": "weather"})

    for bad_lon in ("500", "181", "-181", "180.0001", "-180.0001"):
        err = p.validate_settings({"latitude": "40.0", "longitude": bad_lon})
        assert err is not None
        assert "Longitude" in err


def test_weather_validate_settings_rejects_non_numeric():
    """JTN-354: validate_settings must reject non-numeric lat/lon."""
    from plugins.weather.weather import Weather

    p = Weather({"id": "weather"})

    assert p.validate_settings({"latitude": "abc", "longitude": "-74.0"}) is not None
    assert p.validate_settings({"latitude": "40.0", "longitude": "xyz"}) is not None


def test_weather_validate_settings_rejects_missing_coordinates():
    """JTN-354: validate_settings must reject missing/empty lat/lon."""
    from plugins.weather.weather import Weather

    p = Weather({"id": "weather"})

    assert p.validate_settings({"longitude": "-74.0"}) is not None
    assert p.validate_settings({"latitude": "40.0"}) is not None
    assert p.validate_settings({"latitude": "", "longitude": ""}) is not None


def test_weather_validate_settings_accepts_valid_coordinates():
    """JTN-354: valid lat/lon at and inside bounds must pass validation."""
    from plugins.weather.weather import Weather

    p = Weather({"id": "weather"})

    valid_cases = [
        ("37.7749", "-122.4194"),  # San Francisco
        ("0", "0"),
        ("90", "180"),
        ("-90", "-180"),
        ("40.7128", "-74.0060"),  # New York
    ]
    for lat, lon in valid_cases:
        assert p.validate_settings({"latitude": lat, "longitude": lon}) is None


def test_weather_save_plugin_settings_rejects_out_of_range_latitude(client):
    """JTN-354: POST to /save_plugin_settings with bad lat must return 400."""
    data = {
        "plugin_id": "weather",
        "latitude": "999.999",
        "longitude": "-74.0060",
        "units": "imperial",
        "weatherProvider": "OpenMeteo",
    }
    resp = client.post("/save_plugin_settings", data=data)
    assert resp.status_code == 400
    body = resp.get_json() or {}
    assert body.get("success") is False
    assert "Latitude" in (body.get("error") or body.get("message") or "")


def test_weather_save_plugin_settings_rejects_out_of_range_longitude(client):
    """JTN-354: POST to /save_plugin_settings with bad lon must return 400."""
    data = {
        "plugin_id": "weather",
        "latitude": "40.7128",
        "longitude": "500",
        "units": "imperial",
        "weatherProvider": "OpenMeteo",
    }
    resp = client.post("/save_plugin_settings", data=data)
    assert resp.status_code == 400
    body = resp.get_json() or {}
    assert body.get("success") is False
    assert "Longitude" in (body.get("error") or body.get("message") or "")


def test_weather_save_plugin_settings_rejects_negative_out_of_range(client):
    """JTN-354: lat=-91 must be rejected with 400."""
    data = {
        "plugin_id": "weather",
        "latitude": "-91",
        "longitude": "-74.0060",
        "units": "imperial",
        "weatherProvider": "OpenMeteo",
    }
    resp = client.post("/save_plugin_settings", data=data)
    assert resp.status_code == 400


def test_weather_plugin_settings_template_has_numeric_inputs(client):
    """JTN-354: lat/lon inputs must be type=number with min/max constraints."""
    resp = client.get("/plugin/weather")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    # Latitude constraints
    assert 'id="latitude"' in html
    assert 'type="number"' in html
    assert 'min="-90"' in html
    assert 'max="90"' in html
    # Longitude constraints
    assert 'id="longitude"' in html
    assert 'min="-180"' in html
    assert 'max="180"' in html


def test_weather_invalid_units_falls_back_to_imperial(device_config_dev):
    """JTN-784: invalid `units` fall back to imperial at render time; form
    validation still rejects the bad value on save."""
    from plugins.weather.weather import Weather

    p = Weather({"id": "weather"})
    settings = {
        "latitude": "40.7128",
        "longitude": "-74.0060",
        "units": "invalid",
        "weatherProvider": "OpenMeteo",
    }

    with (
        patch.object(Weather, "get_open_meteo_data", return_value={}) as m_data,
        patch.object(Weather, "get_open_meteo_air_quality", return_value={}),
        patch.object(
            Weather,
            "parse_open_meteo_data",
            return_value={"dt": 0, "title": "-"},
        ),
        patch.object(Weather, "render_image", return_value=object()),
        patch.object(Weather, "_request_timeout", return_value=None),
        patch.object(Weather, "get_plugin_dir", return_value=""),
    ):
        p.generate_image(settings, device_config_dev)
    args, _kwargs = m_data.call_args
    assert args[2] == "imperial"


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
