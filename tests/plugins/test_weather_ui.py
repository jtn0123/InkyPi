# pyright: reportMissingImports=false
"""Tests for Weather plugin UI enhancements including progressive disclosure, validation, and wizard."""


def test_weather_plugin_settings_organization(client):
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


def test_weather_plugin_smart_defaults(client):
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


def test_weather_plugin_settings_persistence(client):
    """Test that weather plugin uses the shared boot payload and schema runtime."""
    resp = client.get("/plugin/weather")
    assert resp.status_code == 200

    response_text = resp.get_data(as_text=True)

    assert "__INKYPI_PLUGIN_BOOT__" in response_text
    assert "pluginSettings" in response_text
    assert "plugin_schema.js" in response_text


def test_weather_plugin_wizard_step_navigation(client):
    """Test that weather plugin retains the setup-wizard container and loads the JS that creates nav.

    The wizard navigation buttons (wizardPrev/wizardNext) are injected at runtime by
    progressive_disclosure.js — they must NOT be duplicated in the server-rendered HTML.
    The static HTML should have exactly the bare .setup-wizard container plus the script.
    """
    resp = client.get("/plugin/weather")
    assert resp.status_code == 200

    response_text = resp.get_data(as_text=True)

    # The container element is still rendered server-side
    assert "setup-wizard" in response_text
    # The JS module that injects wizard navigation at runtime must be loaded
    assert "progressive_disclosure.js" in response_text
    # IDs must not be duplicated in static HTML — JS creates them once at runtime
    assert (
        response_text.count('id="wizardPrev"') <= 1
    ), "Duplicate id='wizardPrev' found in server-rendered HTML"
    assert (
        response_text.count('id="wizardNext"') <= 1
    ), "Duplicate id='wizardNext' found in server-rendered HTML"
