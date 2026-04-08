"""Tests for utils/config_schema.py — validate_device_config and ConfigValidationError.

Coverage targets:
- Valid minimal config passes without error.
- Wrong type for a known field raises ConfigValidationError with path in message.
- Missing a required field (playlist item name) raises with helpful message.
- Unknown extra fields PASS (permissive additionalProperties: true).
- Real device_dev.json validates cleanly (regression guard).
- Fallback validation (jsonschema=None) catches bad orientation.
- Fallback allows valid orientation.
- Missing schema file skips validation without error.
"""

import json
import os

import pytest

import utils.config_schema as schema_mod
from utils.config_schema import ConfigValidationError, validate_device_config

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MINIMAL_VALID = {
    "name": "TestDevice",
    "display_type": "mock",
    "resolution": [800, 480],
    "orientation": "horizontal",
    "playlist_config": {
        "playlists": [],
        "active_playlist": None,
    },
    "refresh_info": {},
}


def _with(**overrides):
    """Return a copy of the minimal valid config with fields overridden."""
    cfg = dict(_MINIMAL_VALID)
    cfg.update(overrides)
    return cfg


# ---------------------------------------------------------------------------
# Valid minimal config passes
# ---------------------------------------------------------------------------


def test_valid_minimal_config_passes():
    """A well-formed minimal config should not raise."""
    validate_device_config(_MINIMAL_VALID)  # no exception


# ---------------------------------------------------------------------------
# Wrong type for known field raises ConfigValidationError with path
# ---------------------------------------------------------------------------


def test_wrong_type_resolution_raises():
    """resolution must be an array of integers — passing strings should fail."""
    bad = _with(resolution=["wide", "tall"])
    with pytest.raises(ConfigValidationError) as exc_info:
        validate_device_config(bad)
    msg = str(exc_info.value)
    assert "resolution" in msg or "schema validation" in msg


def test_wrong_type_plugin_cycle_interval_raises():
    """plugin_cycle_interval_seconds must be an integer, not a string."""
    bad = _with(plugin_cycle_interval_seconds="fast")
    with pytest.raises(ConfigValidationError) as exc_info:
        validate_device_config(bad)
    msg = str(exc_info.value)
    assert "schema validation" in msg


def test_invalid_orientation_raises():
    """orientation must be 'horizontal' or 'vertical'."""
    bad = _with(orientation="diagonal")
    with pytest.raises(ConfigValidationError) as exc_info:
        validate_device_config(bad)
    msg = str(exc_info.value)
    assert "orientation" in msg


# ---------------------------------------------------------------------------
# ConfigValidationError is a subclass of ValueError (backward compat)
# ---------------------------------------------------------------------------


def test_config_validation_error_is_value_error():
    bad = _with(orientation="sideways")
    with pytest.raises(ValueError):
        validate_device_config(bad)


# ---------------------------------------------------------------------------
# Missing required field in playlist item raises with helpful message
# ---------------------------------------------------------------------------


def test_missing_required_playlist_item_field_raises():
    """A playlist item without 'name' violates the schema."""
    bad = _with(
        playlist_config={
            "playlists": [
                # 'name' is required but omitted
                {"plugins": [], "start_time": "00:00", "end_time": "24:00"}
            ],
            "active_playlist": None,
        }
    )
    with pytest.raises(ConfigValidationError) as exc_info:
        validate_device_config(bad)
    msg = str(exc_info.value)
    assert "schema validation" in msg


# ---------------------------------------------------------------------------
# Unknown extra fields PASS (permissive schema)
# ---------------------------------------------------------------------------


def test_unknown_extra_fields_pass():
    """Extra keys not in the schema must not cause a validation error."""
    cfg = _with(
        completely_unknown_key="hello",
        another_unknown={"nested": True},
    )
    validate_device_config(cfg)  # no exception


# ---------------------------------------------------------------------------
# Real device_dev.json validates cleanly (regression guard)
# ---------------------------------------------------------------------------


def test_real_device_dev_json_validates():
    """The checked-in device_dev.json must pass schema validation."""
    dev_json_path = os.path.join(
        os.path.dirname(__file__),  # tests/unit/
        "..",
        "..",
        "src",
        "config",
        "device_dev.json",
    )
    dev_json_path = os.path.abspath(dev_json_path)
    assert os.path.isfile(
        dev_json_path
    ), f"device_dev.json not found at {dev_json_path}"

    with open(dev_json_path) as fh:
        cfg = json.load(fh)

    validate_device_config(cfg)  # no exception


# ---------------------------------------------------------------------------
# Fallback validation (jsonschema=None) — catches bad orientation
# ---------------------------------------------------------------------------


def test_fallback_catches_bad_orientation(monkeypatch):
    """When jsonschema is unavailable, the fallback catches invalid orientation."""
    monkeypatch.setattr(schema_mod, "jsonschema", None)
    bad = _with(orientation="upside_down")
    with pytest.raises(ConfigValidationError) as exc_info:
        validate_device_config(bad)
    msg = str(exc_info.value)
    assert "orientation" in msg
    assert "invalid value" in msg


def test_fallback_allows_valid_orientation(monkeypatch):
    """When jsonschema is unavailable, a valid orientation passes the fallback."""
    monkeypatch.setattr(schema_mod, "jsonschema", None)
    validate_device_config(_MINIMAL_VALID)  # no exception


def test_fallback_no_orientation_key_passes(monkeypatch):
    """Fallback must not crash when orientation key is absent."""
    monkeypatch.setattr(schema_mod, "jsonschema", None)
    cfg = {k: v for k, v in _MINIMAL_VALID.items() if k != "orientation"}
    validate_device_config(cfg)  # no exception


# ---------------------------------------------------------------------------
# Missing schema file skips validation without error
# ---------------------------------------------------------------------------


def test_missing_schema_file_skips_silently(monkeypatch, tmp_path):
    """If the schema file is absent, validation is skipped (no crash)."""
    missing_path = str(tmp_path / "nonexistent_schema.json")
    monkeypatch.setattr(schema_mod, "SCHEMA_PATH", missing_path)
    # Clear lru_cache so new path takes effect
    schema_mod._load_schema.cache_clear()
    validate_device_config(
        _with(orientation="diagonal")
    )  # no exception even with bad data


# ---------------------------------------------------------------------------
# Error message includes the path to the invalid field
# ---------------------------------------------------------------------------


def test_error_message_includes_field_path():
    """ConfigValidationError message must include the offending field name/path."""
    bad = _with(orientation="sideways")
    with pytest.raises(ConfigValidationError) as exc_info:
        validate_device_config(bad)
    # The path 'orientation' must appear somewhere in the message
    assert "orientation" in str(exc_info.value)
