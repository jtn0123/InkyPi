"""Tests for accessibility labels and dialog semantics (JTN-155, JTN-156)."""

import re
from pathlib import Path


def test_github_colors_widget_has_labels():
    """Each color picker in github_colors.html must have an associated label."""
    content = Path("src/templates/widgets/github_colors.html").read_text()
    for level in ["None", "Low", "Medium", "High", "Very High"]:
        assert level in content, f"Missing label for intensity level: {level}"
    assert 'id="contributionColor' in content


def test_github_settings_has_color_labels():
    """Each color picker in github settings.html must have an associated label."""
    content = Path("src/plugins/github/settings.html").read_text()
    for level in ["None", "Low", "Medium", "High", "Very High"]:
        assert level in content, f"Missing label for intensity level: {level}"
    assert 'id="contributionColor' in content


def test_weather_map_modal_has_dialog_role():
    """The weather map modal must have role=dialog and aria-modal=true."""
    content = Path("src/templates/widgets/weather_map.html").read_text()
    assert 'role="dialog"' in content
    assert 'aria-modal="true"' in content
    assert "aria-labelledby=" in content


def test_weather_map_close_button_is_button_element():
    """The close button must be a <button>, not a <span>."""
    content = Path("src/templates/widgets/weather_map.html").read_text()
    span_close = re.search(r'<span[^>]*class="[^"]*close-button', content)
    assert span_close is None, "close-button should be <button>, not <span>"


def test_weather_settings_modal_has_dialog_role():
    """The legacy weather settings modal must also have dialog semantics."""
    content = Path("src/plugins/weather/settings.html").read_text()
    assert 'role="dialog"' in content
    assert 'aria-modal="true"' in content


def test_weather_settings_close_button_is_button_element():
    """The close button in weather settings must be a <button>, not a <span>."""
    content = Path("src/plugins/weather/settings.html").read_text()
    span_close = re.search(r'<span[^>]*class="[^"]*close-button', content)
    assert span_close is None, "close-button should be <button>, not <span>"
