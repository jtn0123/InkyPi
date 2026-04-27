from __future__ import annotations

import json

from utils.request_models import (
    parse_api_keys_save_request,
    parse_device_cycle_request,
    parse_playlist_create_request,
    parse_playlist_name_request,
    parse_playlist_reorder_request,
    parse_playlist_update_request,
    parse_plugin_instance_action_request,
    parse_plugin_order_request,
    parse_plugin_settings_form_request,
    parse_plugin_update_instance_request,
    parse_plugin_update_now_request,
    validate_cycle_minutes,
    validate_playlist_name,
    validate_plugin_id,
)


def test_validate_playlist_name_strips_and_accepts_safe_ascii() -> None:
    name, error = validate_playlist_name("  Morning List  ")

    assert error is None
    assert name == "Morning List"


def test_validate_playlist_name_rejects_non_ascii_with_field() -> None:
    name, error = validate_playlist_name("Café", field="new_name")

    assert name is None
    assert error is not None
    assert error.field == "new_name"
    assert error.code == "validation_error"


def test_parse_playlist_create_request_returns_typed_minutes() -> None:
    parsed, error = parse_playlist_create_request(
        {"playlist_name": "Night", "start_time": "22:00", "end_time": "05:00"}
    )

    assert error is None
    assert parsed is not None
    assert parsed.playlist_name == "Night"
    assert parsed.start_min == 22 * 60
    assert parsed.end_min == 5 * 60
    assert parsed.cycle_minutes_int is None


def test_parse_playlist_create_request_accepts_cycle_override() -> None:
    parsed, error = parse_playlist_create_request(
        {
            "playlist_name": "Night",
            "start_time": "22:00",
            "end_time": "05:00",
            "cycle_minutes": "15",
        }
    )

    assert error is None
    assert parsed is not None
    assert parsed.cycle_minutes_int == 15


def test_parse_playlist_create_request_rejects_matching_times() -> None:
    parsed, error = parse_playlist_create_request(
        {"playlist_name": "Same", "start_time": "10:00", "end_time": "10:00"}
    )

    assert parsed is None
    assert error is not None
    assert error.field == "end_time"


def test_parse_playlist_create_request_rejects_non_object_payload() -> None:
    parsed, error = parse_playlist_create_request(["not", "an", "object"])

    assert parsed is None
    assert error is not None
    assert error.message == "Invalid JSON data"


def test_validate_cycle_minutes_accepts_optional_and_range() -> None:
    missing_value, missing_error = validate_cycle_minutes(None)
    value, error = validate_cycle_minutes("15")

    assert missing_value is None
    assert missing_error is None
    assert value == 15
    assert error is None


def test_validate_cycle_minutes_rejects_out_of_range() -> None:
    value, error = validate_cycle_minutes(1441)

    assert value is None
    assert error is not None
    assert error.field == "cycle_minutes"


def test_parse_playlist_update_request_returns_typed_model() -> None:
    parsed, error = parse_playlist_update_request(
        {
            "new_name": "Focus",
            "start_time": "08:00",
            "end_time": "12:00",
            "cycle_minutes": "30",
        }
    )

    assert error is None
    assert parsed is not None
    assert parsed.new_name == "Focus"
    assert parsed.start_min == 8 * 60
    assert parsed.end_min == 12 * 60
    assert parsed.cycle_minutes_int == 30


def test_parse_playlist_update_request_rejects_non_object_payload() -> None:
    parsed, error = parse_playlist_update_request("bad")

    assert parsed is None
    assert error is not None
    assert error.message == "Invalid JSON data"


def test_parse_api_keys_save_request_accepts_entries_list() -> None:
    parsed, error = parse_api_keys_save_request(
        {"entries": [{"key": "MY_KEY", "value": "secret"}]}
    )

    assert error is None
    assert parsed is not None
    assert parsed.entries == [{"key": "MY_KEY", "value": "secret"}]


def test_parse_api_keys_save_request_rejects_non_list_entries() -> None:
    parsed, error = parse_api_keys_save_request({"entries": "bad"})

    assert parsed is None
    assert error is not None
    assert error.field == "entries"


def test_parse_plugin_order_request_returns_string_order() -> None:
    parsed, error = parse_plugin_order_request({"order": ["clock", "weather"]})

    assert error is None
    assert parsed is not None
    assert parsed.order == ["clock", "weather"]


def test_parse_plugin_order_request_rejects_non_string_items() -> None:
    parsed, error = parse_plugin_order_request({"order": ["clock", 3]})

    assert parsed is None
    assert error is not None
    assert error.field == "order"


def test_parse_device_cycle_request_returns_int_minutes() -> None:
    parsed, error = parse_device_cycle_request({"minutes": "30"})

    assert error is None
    assert parsed is not None
    assert parsed.minutes == 30


def test_parse_device_cycle_request_rejects_out_of_range() -> None:
    parsed, error = parse_device_cycle_request({"minutes": 0})

    assert parsed is None
    assert error is not None
    assert error.field == "minutes"
    assert "between" in error.message


def test_parse_device_cycle_request_requires_minutes() -> None:
    parsed, error = parse_device_cycle_request({})

    assert parsed is None
    assert error is not None
    assert error.field == "minutes"
    assert error.message == "Minutes is required"


def test_parse_playlist_update_request_uses_shared_missing_time_error() -> None:
    parsed, error = parse_playlist_update_request(
        {"new_name": "Focus", "end_time": "12:00"}
    )

    assert parsed is None
    assert error is not None
    assert error.field == "start_time"
    assert error.message == "Start time and End time are required"


def test_parse_playlist_reorder_request_returns_ordered_payload() -> None:
    parsed, error = parse_playlist_reorder_request(
        {
            "playlist_name": " Default ",
            "ordered": [{"plugin_id": " clock ", "name": " Clock "}],
        }
    )

    assert error is None
    assert parsed is not None
    assert parsed.playlist_name == "Default"
    assert parsed.ordered_payload() == [{"plugin_id": "clock", "name": "Clock"}]


def test_parse_playlist_reorder_request_rejects_wrong_item_shape() -> None:
    parsed, error = parse_playlist_reorder_request(
        {"playlist_name": "Default", "ordered": [{"pid": "clock"}]}
    )

    assert parsed is None
    assert error is not None
    assert error.field == "ordered"


def test_parse_playlist_reorder_request_rejects_empty_plugin_id() -> None:
    parsed, error = parse_playlist_reorder_request(
        {"playlist_name": "Default", "ordered": [{"plugin_id": " ", "name": "Clock"}]}
    )

    assert parsed is None
    assert error is not None
    assert error.field == "ordered"


def test_parse_playlist_reorder_request_labels_missing_ordered() -> None:
    parsed, error = parse_playlist_reorder_request({"playlist_name": "Default"})

    assert parsed is None
    assert error is not None
    assert error.field == "ordered"
    assert error.message == "ordered list is required"


def test_parse_playlist_name_request_strips_name() -> None:
    parsed, error = parse_playlist_name_request(
        {"playlist_name": " Default "}, missing_message="playlist_name required"
    )

    assert error is None
    assert parsed is not None
    assert parsed.playlist_name == "Default"


def test_parse_plugin_instance_action_request_returns_typed_payload() -> None:
    parsed, error = parse_plugin_instance_action_request(
        {
            "playlist_name": " Default ",
            "plugin_id": "clock",
            "plugin_instance": "Clock A",
        }
    )

    assert error is None
    assert parsed is not None
    assert parsed.playlist_name == "Default"
    assert parsed.plugin_id == "clock"
    assert parsed.plugin_instance == "Clock A"


def test_validate_plugin_id_strips_and_accepts_string() -> None:
    plugin_id, error = validate_plugin_id("  weather  ")

    assert error is None
    assert plugin_id == "weather"


def test_validate_plugin_id_rejects_missing_with_field() -> None:
    plugin_id, error = validate_plugin_id(" ")

    assert plugin_id is None
    assert error is not None
    assert error.status == 422
    assert error.field == "plugin_id"
    assert error.message == "plugin_id is required"


def test_parse_plugin_settings_form_request_pops_plugin_id() -> None:
    parsed, error = parse_plugin_settings_form_request(
        {"plugin_id": "  clock  ", "timezone": "UTC"}
    )

    assert error is None
    assert parsed is not None
    assert parsed.plugin_id == "clock"
    assert parsed.plugin_settings == {"timezone": "UTC"}


def test_parse_plugin_settings_form_request_rejects_missing_plugin_id() -> None:
    parsed, error = parse_plugin_settings_form_request({"timezone": "UTC"})

    assert parsed is None
    assert error is not None
    assert error.status == 422
    assert error.field == "plugin_id"


def test_parse_plugin_update_instance_request_decodes_refresh_settings() -> None:
    parsed, error = parse_plugin_update_instance_request(
        {
            "plugin_id": "clock",
            "timezone": "UTC",
            "refresh_settings": json.dumps({"refreshType": "interval"}),
        }
    )

    assert error is None
    assert parsed is not None
    assert parsed.plugin_id == "clock"
    assert parsed.plugin_settings == {"timezone": "UTC"}
    assert parsed.refresh_settings == {"refreshType": "interval"}


def test_parse_plugin_update_instance_request_rejects_bad_refresh_json() -> None:
    parsed, error = parse_plugin_update_instance_request(
        {"plugin_id": "clock", "refresh_settings": "not valid json"}
    )

    assert parsed is None
    assert error is not None
    assert error.message == "Refresh settings must be valid JSON"
    assert error.field == "refresh_settings"


def test_parse_plugin_update_instance_request_rejects_non_object_refresh() -> None:
    parsed, error = parse_plugin_update_instance_request(
        {"plugin_id": "clock", "refresh_settings": json.dumps(["bad"])}
    )

    assert parsed is None
    assert error is not None
    assert error.message == "Refresh settings must be an object"
    assert error.field == "refresh_settings"


def test_parse_plugin_update_now_request_extracts_async_flag() -> None:
    parsed, error = parse_plugin_update_now_request(
        {"plugin_id": "clock", "timezone": "UTC"},
        async_query="1",
    )

    assert error is None
    assert parsed is not None
    assert parsed.plugin_id == "clock"
    assert parsed.plugin_settings == {"timezone": "UTC"}
    assert parsed.want_async is True


def test_parse_plugin_instance_action_request_requires_playlist_name() -> None:
    parsed, error = parse_plugin_instance_action_request(
        {"plugin_id": "clock", "plugin_instance": "Clock A"}
    )

    assert parsed is None
    assert error is not None
    assert error.field == "playlist_name"
