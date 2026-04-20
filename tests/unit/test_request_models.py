# mypy: disable-error-code=untyped-decorator
"""Unit tests for reusable playlist/settings request models."""

from __future__ import annotations

import pytest

from utils.request_models import (
    ClientLogRequest,
    DeviceCycleRequest,
    PlaylistCreateRequest,
    PlaylistReorderRequest,
    PlaylistSelectionRequest,
    PlaylistUpdateRequest,
    PluginIsolationRequest,
    RequestValidationError,
    SettingsFormRequest,
    SettingsImportRequest,
    SettingsUpdateRequest,
    ShutdownRequest,
    require_mapping,
)


def test_request_validation_error_populates_field_details() -> None:
    err = RequestValidationError("bad input", status=422, field="playlist_name")

    assert err.details == {"field": "playlist_name"}
    assert err.as_json_error_kwargs() == {
        "message": "bad input",
        "status": 422,
        "code": "validation_error",
        "details": {"field": "playlist_name"},
    }


def test_require_mapping_rejects_non_mapping() -> None:
    with pytest.raises(RequestValidationError) as exc_info:
        require_mapping(["not", "a", "mapping"])

    err = exc_info.value
    assert err.message == "Request body must be a JSON object"
    assert err.status == 400
    assert err.code is None
    assert err.details is None


def test_playlist_create_request_parses_and_trims() -> None:
    parsed = PlaylistCreateRequest.from_mapping(
        {
            "playlist_name": "  Morning Run  ",
            "start_time": "08:00",
            "end_time": "12:00",
        }
    )

    assert parsed.playlist_name == "Morning Run"
    assert parsed.start_time == "08:00"
    assert parsed.end_time == "12:00"
    assert parsed.start_min == 8 * 60
    assert parsed.end_min == 12 * 60


def test_playlist_create_request_preserves_route_length_message() -> None:
    with pytest.raises(RequestValidationError) as exc_info:
        PlaylistCreateRequest.from_mapping(
            {
                "playlist_name": "x" * 65,
                "start_time": "08:00",
                "end_time": "12:00",
            }
        )

    err = exc_info.value
    assert err.message == "Playlist name must be 64 characters or fewer"
    assert err.field == "playlist_name"
    assert err.status == 400


def test_playlist_create_request_rejects_invalid_time_field() -> None:
    with pytest.raises(RequestValidationError) as exc_info:
        PlaylistCreateRequest.from_mapping(
            {
                "playlist_name": "Morning",
                "start_time": "bad",
                "end_time": "12:00",
            }
        )

    err = exc_info.value
    assert err.message == "Invalid start/end time format"
    assert err.field == "start_time"
    assert err.status == 400


def test_playlist_update_request_uses_missing_fields_message() -> None:
    with pytest.raises(RequestValidationError) as exc_info:
        PlaylistUpdateRequest.from_mapping(
            {"new_name": "Updated", "start_time": "08:00"}
        )

    err = exc_info.value
    assert err.message == "Missing required fields"
    assert err.field == "end_time"
    assert err.status == 400


@pytest.mark.parametrize("cycle_minutes", ["abc", 0, 1441])
def test_playlist_update_request_validates_cycle_minutes(
    cycle_minutes: object,
) -> None:
    with pytest.raises(RequestValidationError) as exc_info:
        PlaylistUpdateRequest.from_mapping(
            {
                "new_name": "Updated",
                "start_time": "08:00",
                "end_time": "10:00",
                "cycle_minutes": cycle_minutes,
            }
        )

    assert exc_info.value.field == "cycle_minutes"


def test_playlist_selection_request_supports_custom_message() -> None:
    with pytest.raises(RequestValidationError) as exc_info:
        PlaylistSelectionRequest.from_mapping(
            {}, required_message="playlist_name and ordered list are required"
        )

    err = exc_info.value
    assert err.message == "playlist_name and ordered list are required"
    assert err.field == "playlist_name"


def test_playlist_reorder_request_converts_items_to_model_payload() -> None:
    parsed = PlaylistReorderRequest.from_mapping(
        {
            "playlist_name": "Morning",
            "ordered": [
                {"plugin_id": "weather", "name": "Weather"},
                {"plugin_id": "calendar", "name": "Calendar"},
            ],
        }
    )

    assert parsed.playlist_name == "Morning"
    assert parsed.as_reorder_payload() == [
        {"plugin_id": "weather", "name": "Weather"},
        {"plugin_id": "calendar", "name": "Calendar"},
    ]


@pytest.mark.parametrize("minutes", [None, "abc"])
def test_device_cycle_request_rejects_invalid_minutes(minutes: object) -> None:
    with pytest.raises(RequestValidationError) as exc_info:
        DeviceCycleRequest.from_mapping({"minutes": minutes})

    err = exc_info.value
    assert err.message == "Invalid minutes"
    assert err.field == "minutes"
    assert err.status == 400


def test_plugin_isolation_request_trims_and_checks_registered_ids() -> None:
    parsed = PluginIsolationRequest.from_mapping(
        {"plugin_id": " weather "}, registered_ids={"weather", "calendar"}
    )
    assert parsed.plugin_id == "weather"

    with pytest.raises(RequestValidationError) as exc_info:
        PluginIsolationRequest.from_mapping(
            {"plugin_id": "unknown"}, registered_ids={"weather"}
        )

    err = exc_info.value
    assert err.message == "plugin_id must reference a registered plugin"
    assert err.field == "plugin_id"
    assert err.status == 422


def test_shutdown_request_defaults_and_parses_bool() -> None:
    assert ShutdownRequest.from_optional_mapping(None).reboot is False
    assert ShutdownRequest.from_optional_mapping({}).reboot is False
    assert ShutdownRequest.from_optional_mapping({"reboot": "yes"}).reboot is True


@pytest.mark.parametrize(
    ("raw_level", "expected"),
    [
        ("warning", "warning"),
        ("warn", "warning"),
        ("err", "error"),
        ("error", "error"),
        ("debug", "debug"),
        ("other", "info"),
        (None, "info"),
    ],
)
def test_client_log_request_normalizes_level_aliases(
    raw_level: object, expected: str
) -> None:
    parsed = ClientLogRequest.from_mapping({"level": raw_level, "message": "hello"})

    assert parsed.level == expected
    assert parsed.message == "hello"


def test_settings_update_request_validates_optional_target_version() -> None:
    assert SettingsUpdateRequest.from_mapping({}).target_version is None

    parsed = SettingsUpdateRequest.from_mapping({"target_version": " v1.2.3 "})
    assert parsed.target_version == "v1.2.3"

    with pytest.raises(RequestValidationError) as exc_info:
        SettingsUpdateRequest.from_mapping({"target_version": "not-a-version"})

    err = exc_info.value
    assert err.message == "Invalid target version format"
    assert err.field == "target_version"
    assert err.status == 400


@pytest.mark.parametrize("raw_value", [None, "", "   ", 123])
def test_settings_update_request_rejects_empty_or_non_string_target_versions(
    raw_value: object,
) -> None:
    with pytest.raises(RequestValidationError) as exc_info:
        SettingsUpdateRequest.from_mapping({"target_version": raw_value})

    err = exc_info.value
    assert err.message == "target_version must be a non-empty string"
    assert err.field == "target_version"
    assert err.status == 400


def test_settings_form_request_builds_route_compatible_settings_dict() -> None:
    parsed = SettingsFormRequest.from_mapping(
        {
            "deviceName": "  Kitchen Display  ",
            "unit": "minute",
            "interval": "30",
            "timezoneName": "UTC",
            "timeFormat": "24h",
            "orientation": "horizontal",
            "previewSizeMode": "fit",
            "invertImage": "on",
            "logSystemStats": "on",
            "saturation": "1.5",
            "brightness": "1.1",
            "sharpness": "1.2",
            "contrast": "0.9",
            "inky_saturation": "0.7",
        },
        valid_timezones={"UTC"},
    )

    assert parsed.device_name == "Kitchen Display"
    assert parsed.interval_seconds == 30 * 60
    assert parsed.to_settings_dict() == {
        "name": "Kitchen Display",
        "orientation": "horizontal",
        "inverted_image": True,
        "log_system_stats": True,
        "timezone": "UTC",
        "time_format": "24h",
        "plugin_cycle_interval_seconds": 30 * 60,
        "image_settings": {
            "saturation": 1.5,
            "brightness": 1.1,
            "sharpness": 1.2,
            "contrast": 0.9,
            "inky_saturation": 0.7,
        },
        "preview_size_mode": "fit",
    }


def test_settings_form_request_rejects_invalid_timezone() -> None:
    with pytest.raises(RequestValidationError) as exc_info:
        SettingsFormRequest.from_mapping(
            {
                "deviceName": "Device",
                "unit": "minute",
                "interval": "30",
                "timezoneName": "Mars/Olympus",
                "timeFormat": "24h",
            },
            valid_timezones={"UTC"},
        )

    err = exc_info.value
    assert "valid IANA timezone" in err.message
    assert err.field == "timezoneName"
    assert err.status == 422


def test_settings_form_request_rejects_control_characters_in_device_name() -> None:
    with pytest.raises(RequestValidationError) as exc_info:
        SettingsFormRequest.from_mapping(
            {
                "deviceName": "Kitchen\nDisplay",
                "unit": "minute",
                "interval": "30",
                "timezoneName": "UTC",
                "timeFormat": "24h",
            },
            valid_timezones={"UTC"},
        )

    err = exc_info.value
    assert err.message == "Device Name may not contain control characters"
    assert err.field == "deviceName"
    assert err.status == 422


def test_settings_import_request_filters_allowed_keys_and_stringifies_values() -> None:
    parsed = SettingsImportRequest.from_mapping(
        {
            "config": {
                "name": "Imported Device",
                "timezone": "UTC",
                "dangerous_key": "nope",
            },
            "env_keys": {
                "OPEN_AI_SECRET": 123,
                "EVIL_KEY": "nope",
                "NASA_SECRET": None,
            },
        },
        allowed_config_keys={"name", "timezone"},
        allowed_env_keys={"OPEN_AI_SECRET", "NASA_SECRET"},
    )

    assert parsed.config == {"name": "Imported Device", "timezone": "UTC"}
    assert parsed.env_keys == {"OPEN_AI_SECRET": "123"}


@pytest.mark.parametrize("field", ["config", "env_keys"])
def test_settings_import_request_requires_mapping_children(field: str) -> None:
    payload: dict[str, object]
    if field == "config":
        payload = {"config": ["not", "a", "mapping"], "env_keys": {}}
    else:
        payload = {"config": {}, "env_keys": ["not", "a", "mapping"]}

    with pytest.raises(RequestValidationError) as exc_info:
        SettingsImportRequest.from_mapping(
            payload,
            allowed_config_keys={"name"},
            allowed_env_keys={"OPEN_AI_SECRET"},
        )

    err = exc_info.value
    assert err.message == f"{field} must be a JSON object"
    assert err.field == field
    assert err.status == 400
