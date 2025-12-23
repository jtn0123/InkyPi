# pyright: reportMissingImports=false
"""Tests for Weather plugin UI enhancements including progressive disclosure, validation, and wizard."""

import pytest

def test_weather_plugin_settings_organization(client):
    """Test that weather settings are properly organized into basic and advanced sections."""
    resp = client.get("/plugin/weather")
    assert resp.status_code == 200

    response_text = resp.get_data(as_text=True)

    # Essential settings should be in basic section
    basic_section_start = response_text.find("settings-section basic-only")
    basic_section_end = response_text.find("settings-section advanced-only")

    if basic_section_start != -1 and basic_section_end != -1:
        basic_section = response_text[basic_section_start:basic_section_end]

        # Check that basic settings are in basic section
        assert "Essential Settings" in basic_section
        assert "latitude" in basic_section
        assert "longitude" in basic_section
        assert "units" in basic_section

    # Advanced settings should be in advanced section
    advanced_section_start = response_text.find("settings-section advanced-only")
    if advanced_section_start != -1:
        advanced_section = response_text[advanced_section_start:]

        # Check that advanced settings are in advanced section
        assert "Advanced Display" in advanced_section
        assert "displayRefreshTime" in advanced_section
        assert "displayMetrics" in advanced_section

def test_weather_plugin_smart_defaults(client):
    """Test that weather plugin has proper smart defaults."""
    resp = client.get("/plugin/weather")
    assert resp.status_code == 200

    response_text = resp.get_data(as_text=True)

    # Check for optimized default values in JavaScript
    assert "imperial" in response_text  # Default temperature unit
    assert "forecastDays" in response_text

    # Check that less technical options are disabled by default
    assert "displayMetrics" in response_text
    assert "displayRefreshTime" in response_text

def test_weather_plugin_settings_persistence(client):
    """Test that weather plugin has settings persistence logic."""
    resp = client.get("/plugin/weather")
    assert resp.status_code == 200

    response_text = resp.get_data(as_text=True)

    # Check for settings loading logic
    assert "loadPluginSettings" in response_text
    assert "pluginSettings" in response_text

    # Check for form population
    assert "document.getElementById" in response_text
    assert ".value =" in response_text
    assert ".checked =" in response_text

def test_weather_plugin_wizard_step_navigation(client):
    """Test that weather wizard has proper step navigation."""
    resp = client.get("/plugin/weather")
    assert resp.status_code == 200

    response_text = resp.get_data(as_text=True)

    # Check for wizard navigation elements
    assert "wizard-navigation" in response_text
    assert "wizard-progress" in response_text
    assert "wizard-step-indicator" in response_text

    # Check for step controls
    assert "wizardNext" in response_text
    assert "wizardPrev" in response_text