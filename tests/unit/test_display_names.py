"""Unit tests for utils.display_names (JTN-618, JTN-619, JTN-620)."""

from __future__ import annotations

import pytest

from utils.display_names import (
    friendly_instance_label,
    humanize_plugin_id,
    instance_suffix_label,
    is_auto_instance_name,
)


class TestIsAutoInstanceName:
    @pytest.mark.parametrize(
        ("instance_name", "plugin_id", "expected"),
        [
            ("weather_saved_settings", "weather", True),
            ("image_folder_saved_settings", "image_folder", True),
            ("my custom name", "weather", False),
            ("weather", "weather", False),
            ("", "weather", False),
            (None, "weather", False),
            ("weather_saved_settings", "", False),
            ("weather_saved_settings", None, False),
            # Near-miss — trailing/leading variants are not auto
            ("weather_saved_settings_2", "weather", False),
            ("saved_settings", "weather", False),
        ],
    )
    def test_detects_auto_generated_keys(self, instance_name, plugin_id, expected):
        assert is_auto_instance_name(instance_name, plugin_id) is expected


class TestHumanizePluginId:
    @pytest.mark.parametrize(
        ("plugin_id", "expected"),
        [
            ("weather", "Weather"),
            ("image_folder", "Image Folder"),
            ("image-folder", "Image Folder"),
            ("ai_image", "Ai Image"),
            ("", ""),
            (None, ""),
        ],
    )
    def test_humanize(self, plugin_id, expected):
        assert humanize_plugin_id(plugin_id) == expected

    @pytest.mark.parametrize(
        ("plugin_id", "expected"),
        [
            # JTN-595 mutmut triage: kill a surviving mutant where
            # ``.strip()`` is removed from humanize_plugin_id — leading /
            # trailing whitespace must never leak into the humanised label.
            ("  weather  ", "Weather"),
            ("\tweather\n", "Weather"),
            ("   image_folder   ", "Image Folder"),
            # Whitespace-only input humanises to an empty string because
            # the underscore/hyphen replacements produce a whitespace run
            # that .strip() collapses to "".
            ("   ", ""),
        ],
    )
    def test_humanize_strips_surrounding_whitespace(self, plugin_id, expected):
        assert humanize_plugin_id(plugin_id) == expected


class TestFriendlyInstanceLabel:
    def test_user_renamed_instance_is_preserved(self):
        assert (
            friendly_instance_label("My Weather", "weather", "Weather") == "My Weather"
        )

    def test_auto_generated_falls_back_to_display_name(self):
        assert (
            friendly_instance_label("weather_saved_settings", "weather", "Weather")
            == "Weather"
        )

    def test_auto_generated_without_display_falls_back_to_humanized_id(self):
        assert (
            friendly_instance_label("image_folder_saved_settings", "image_folder", None)
            == "Image Folder"
        )

    def test_missing_everything_returns_empty_string(self):
        assert friendly_instance_label(None, None, None) == ""

    def test_only_plugin_id_yields_humanized(self):
        assert friendly_instance_label(None, "rss", None) == "Rss"

    def test_internal_key_never_leaks(self):
        # Regression guard: no user-facing path should ever echo the raw
        # "_saved_settings" suffix.
        result = friendly_instance_label("weather_saved_settings", "weather", "Weather")
        assert "saved_settings" not in result


class TestInstanceSuffixLabel:
    def test_auto_name_returns_none(self):
        assert instance_suffix_label("weather_saved_settings", "weather") is None

    def test_user_name_returns_name(self):
        assert instance_suffix_label("Morning Weather", "weather") == "Morning Weather"

    def test_empty_inputs_return_none(self):
        assert instance_suffix_label(None, "weather") is None
        assert instance_suffix_label("", "weather") is None
