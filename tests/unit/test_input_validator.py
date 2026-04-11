"""Unit tests for the new input validation helpers in src/utils/form_utils.py.

Covers:
- ValidationError
- validate_int_range
- sanitize_for_log (alias for sanitize_log_field)
- validate_json_schema
"""

from __future__ import annotations

import pytest

from utils.form_utils import (
    ValidationError,
    sanitize_for_log,
    validate_int_range,
    validate_json_schema,
)

# ---------------------------------------------------------------------------
# ValidationError
# ---------------------------------------------------------------------------


class TestValidationError:
    def test_is_value_error(self):
        err = ValidationError("bad input")
        assert isinstance(err, ValueError)

    def test_message_stored(self):
        err = ValidationError("something went wrong")
        assert err.message == "something went wrong"
        assert str(err) == "something went wrong"

    def test_field_defaults_to_none(self):
        err = ValidationError("msg")
        assert err.field is None

    def test_field_stored_when_given(self):
        err = ValidationError("msg", field="latitude")
        assert err.field == "latitude"

    def test_raise_and_catch(self):
        with pytest.raises(ValidationError) as exc_info:
            raise ValidationError("out of range", field="saturation")
        assert exc_info.value.field == "saturation"
        assert "out of range" in str(exc_info.value)


# ---------------------------------------------------------------------------
# validate_int_range
# ---------------------------------------------------------------------------


class TestValidateIntRange:
    def test_valid_value_at_min(self):
        assert validate_int_range(1, field="cycle_minutes", min=1, max=1440) == 1

    def test_valid_value_at_max(self):
        assert validate_int_range(1440, field="cycle_minutes", min=1, max=1440) == 1440

    def test_valid_value_in_middle(self):
        assert validate_int_range(60, field="cycle_minutes", min=1, max=1440) == 60

    def test_value_as_string(self):
        # Accepts numeric strings
        assert validate_int_range("30", field="minutes", min=1, max=100) == 30

    def test_below_min_raises(self):
        with pytest.raises(ValidationError) as exc_info:
            validate_int_range(0, field="cycle_minutes", min=1, max=1440)
        assert exc_info.value.field == "cycle_minutes"
        assert "1" in exc_info.value.message
        assert "1440" in exc_info.value.message

    def test_above_max_raises(self):
        with pytest.raises(ValidationError) as exc_info:
            validate_int_range(1441, field="cycle_minutes", min=1, max=1440)
        assert exc_info.value.field == "cycle_minutes"

    def test_non_numeric_raises(self):
        with pytest.raises(ValidationError) as exc_info:
            validate_int_range("abc", field="interval", min=1, max=100)
        assert exc_info.value.field == "interval"
        assert "integer" in exc_info.value.message.lower()

    def test_none_raises(self):
        with pytest.raises(ValidationError):
            validate_int_range(None, field="interval", min=1, max=100)

    def test_float_truncates_and_validates(self):
        # int(3.9) == 3, which is in [1, 10]
        assert validate_int_range(3.9, field="val", min=1, max=10) == 3

    def test_negative_range(self):
        assert validate_int_range(-5, field="temp", min=-10, max=0) == -5

    def test_zero_range(self):
        assert validate_int_range(5, field="val", min=5, max=5) == 5

    def test_exactly_boundary_passes(self):
        assert validate_int_range(10, field="v", min=1, max=10) == 10


# ---------------------------------------------------------------------------
# sanitize_for_log (canonical alias)
# ---------------------------------------------------------------------------


class TestSanitizeForLog:
    def test_is_same_as_sanitize_log_field(self):
        from utils.form_utils import sanitize_log_field

        assert sanitize_for_log is sanitize_log_field

    def test_strips_newlines(self):
        assert sanitize_for_log("hello\nworld") == "helloworld"

    def test_strips_carriage_return(self):
        assert sanitize_for_log("hello\rworld") == "helloworld"

    def test_strips_null_byte(self):
        assert sanitize_for_log("hello\x00world") == "helloworld"

    def test_truncates(self):
        long_str = "x" * 500
        assert len(sanitize_for_log(long_str)) == 200

    def test_coerces_non_string(self):
        assert sanitize_for_log(42) == "42"

    def test_empty_string(self):
        assert sanitize_for_log("") == ""


# ---------------------------------------------------------------------------
# validate_json_schema
# ---------------------------------------------------------------------------


_SIMPLE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "count": {"type": "integer", "minimum": 1, "maximum": 100},
        "mode": {"type": "string", "enum": ["a", "b"]},
    },
    "required": ["name"],
}


class TestValidateJsonSchema:
    def test_valid_data_returns_empty_list(self):
        errors = validate_json_schema(
            {"name": "test", "count": 5, "mode": "a"}, _SIMPLE_SCHEMA
        )
        assert errors == []

    def test_missing_required_field(self):
        errors = validate_json_schema({}, _SIMPLE_SCHEMA)
        assert len(errors) > 0
        assert any("name" in e for e in errors)

    def test_wrong_type_for_field(self):
        errors = validate_json_schema({"name": 123}, _SIMPLE_SCHEMA)
        assert len(errors) > 0

    def test_out_of_range_minimum(self):
        errors = validate_json_schema({"name": "x", "count": 0}, _SIMPLE_SCHEMA)
        assert len(errors) > 0
        assert any("count" in e or "minimum" in e.lower() for e in errors)

    def test_out_of_range_maximum(self):
        errors = validate_json_schema({"name": "x", "count": 101}, _SIMPLE_SCHEMA)
        assert len(errors) > 0

    def test_invalid_enum_value(self):
        errors = validate_json_schema({"name": "x", "mode": "c"}, _SIMPLE_SCHEMA)
        assert len(errors) > 0

    def test_additional_properties_allowed(self):
        errors = validate_json_schema({"name": "x", "extra_key": "ok"}, _SIMPLE_SCHEMA)
        assert errors == []

    def test_multiple_errors_all_returned(self):
        # Missing required 'name' AND wrong type for 'count'
        errors = validate_json_schema({"count": "not-an-int"}, _SIMPLE_SCHEMA)
        assert len(errors) >= 1  # at least 'name' missing

    def test_empty_dict_with_no_required_fields(self):
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {"x": {"type": "string"}},
        }
        errors = validate_json_schema({}, schema)
        assert errors == []

    def test_returns_list_type(self):
        result = validate_json_schema({"name": "ok"}, _SIMPLE_SCHEMA)
        assert isinstance(result, list)
