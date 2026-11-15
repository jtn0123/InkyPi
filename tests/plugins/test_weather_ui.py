# pyright: reportMissingImports=false
"""Tests for the Weather plugin settings page."""

from flask.testing import FlaskClient


def test_weather_plugin_settings_organization(client: FlaskClient) -> None:
    """Test that weather settings use the shared section/card organization."""
    resp = client.get("/plugin/weather")
    assert resp.status_code == 200

    response_text = resp.get_data(as_text=True)

    assert "data-settings-schema" in response_text
    assert 'data-hybrid-widget="weather-map"' in response_text
    assert 'settings-card-title">Location' in response_text
    assert 'settings-card-title">Data' in response_text
    assert 'settings-card-title">Display' in response_text
    assert "displayRefreshTime" in response_text
    assert "displayMetrics" in response_text


def test_weather_plugin_smart_defaults(client: FlaskClient) -> None:
    """Test that weather plugin has proper smart defaults."""
    resp = client.get("/plugin/weather")
    assert resp.status_code == 200

    response_text = resp.get_data(as_text=True)

    assert 'name="units"' in response_text
    assert 'value="imperial"' in response_text
    assert 'name="weatherProvider"' in response_text
    assert 'value="OpenMeteo"' in response_text
    assert "forecastDays" in response_text

    assert "displayMetrics" in response_text
    assert "displayRefreshTime" in response_text


def test_weather_plugin_settings_persistence(client: FlaskClient) -> None:
    """Test that weather plugin uses the shared boot payload and schema runtime."""
    resp = client.get("/plugin/weather")
    assert resp.status_code == 200

    response_text = resp.get_data(as_text=True)

    assert "__INKYPI_PLUGIN_BOOT__" in response_text
    assert "pluginSettings" in response_text
    assert "plugin_schema.js" in response_text
