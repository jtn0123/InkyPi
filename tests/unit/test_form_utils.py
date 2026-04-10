"""Unit tests for src/utils/form_utils.py."""

from __future__ import annotations

import pytest

from utils.form_utils import (
    FormRequest,
    MissingFieldsError,
    sanitize_log_field,
    sanitize_response_value,
    validate_plugin_required_fields,
    validate_required,
)

# ---------------------------------------------------------------------------
# sanitize_log_field
# ---------------------------------------------------------------------------


class TestSanitizeLogField:
    def test_passthrough_plain_string(self):
        assert sanitize_log_field("hello") == "hello"

    def test_strips_newline(self):
        assert sanitize_log_field("foo\nbar") == "foobar"

    def test_strips_carriage_return(self):
        assert sanitize_log_field("foo\rbar") == "foobar"

    def test_strips_null_byte(self):
        assert sanitize_log_field("foo\x00bar") == "foobar"

    def test_strips_all_control_chars_combined(self):
        assert sanitize_log_field("a\nb\rc\x00d") == "abcd"

    def test_truncates_to_default_200(self):
        long_str = "x" * 300
        result = sanitize_log_field(long_str)
        assert len(result) == 200

    def test_custom_max_len(self):
        result = sanitize_log_field("abcdefgh", max_len=4)
        assert result == "abcd"

    def test_coerces_non_string_to_str(self):
        assert sanitize_log_field(42) == "42"
        assert sanitize_log_field(None) == "None"
        assert sanitize_log_field(3.14) == "3.14"

    def test_unicode_passthrough(self):
        assert sanitize_log_field("héllo wörld") == "héllo wörld"

    def test_ansi_escape_sequence_preserved(self):
        # ANSI codes are not control characters per this helper; they should pass through
        ansi = "\x1b[31mred\x1b[0m"
        result = sanitize_log_field(ansi)
        assert "red" in result

    def test_empty_string(self):
        assert sanitize_log_field("") == ""

    def test_exactly_at_max_len(self):
        s = "a" * 200
        assert sanitize_log_field(s) == s

    def test_max_len_zero(self):
        assert sanitize_log_field("anything", max_len=0) == ""


# ---------------------------------------------------------------------------
# sanitize_response_value
# ---------------------------------------------------------------------------


class TestSanitizeResponseValue:
    def test_plain_string(self):
        assert sanitize_response_value("hello") == "hello"

    def test_escapes_lt_gt(self):
        result = sanitize_response_value("<script>")
        assert "<" not in result
        assert ">" not in result
        assert result == "&lt;script&gt;"

    def test_escapes_ampersand(self):
        assert "&amp;" in sanitize_response_value("a&b")

    def test_quotes_not_escaped(self):
        # quote=False means single and double quotes pass through
        result = sanitize_response_value('say "hi"')
        assert '"' in result

    def test_strips_control_chars(self):
        result = sanitize_response_value("foo\nbar")
        assert "\n" not in result
        assert "foo" in result
        assert "bar" in result

    def test_coerces_non_string(self):
        result = sanitize_response_value(42)
        assert result == "42"

    def test_truncates_long_value(self):
        long_val = "x" * 300
        assert len(sanitize_response_value(long_val)) <= 200

    def test_combined_control_and_html(self):
        result = sanitize_response_value("<b>\ninjected</b>")
        assert "\n" not in result
        assert "<" not in result


# ---------------------------------------------------------------------------
# validate_required
# ---------------------------------------------------------------------------


class TestValidateRequired:
    def test_all_present_no_error(self):
        validate_required({"a": "1", "b": "2"}, ["a", "b"])  # should not raise

    def test_raises_for_missing_key(self):
        with pytest.raises(MissingFieldsError) as exc_info:
            validate_required({"a": "1"}, ["a", "b"])
        assert "b" in exc_info.value.missing

    def test_raises_for_empty_string(self):
        with pytest.raises(MissingFieldsError) as exc_info:
            validate_required({"a": ""}, ["a"])
        assert "a" in exc_info.value.missing

    def test_raises_for_whitespace_only(self):
        with pytest.raises(MissingFieldsError) as exc_info:
            validate_required({"a": "   "}, ["a"])
        assert "a" in exc_info.value.missing

    def test_raises_for_none_value(self):
        with pytest.raises(MissingFieldsError) as exc_info:
            validate_required({"a": None}, ["a"])
        assert "a" in exc_info.value.missing

    def test_extra_keys_ignored(self):
        validate_required({"a": "1", "extra": "x"}, ["a"])  # should not raise

    def test_empty_required_list(self):
        validate_required({}, [])  # no required keys → no error

    def test_multiple_missing_all_reported(self):
        with pytest.raises(MissingFieldsError) as exc_info:
            validate_required({}, ["x", "y", "z"])
        assert set(exc_info.value.missing) == {"x", "y", "z"}

    def test_message_contains_missing_fields(self):
        with pytest.raises(MissingFieldsError) as exc_info:
            validate_required({"a": ""}, ["a"])
        assert "a" in exc_info.value.message
        assert "Required fields missing" in exc_info.value.message

    def test_value_with_content_passes(self):
        validate_required({"name": "Alice"}, ["name"])  # should not raise

    def test_zero_int_passes(self):
        # 0 str-ifies to "0" which has len 1 → not empty
        validate_required({"count": 0}, ["count"])


# ---------------------------------------------------------------------------
# validate_plugin_required_fields
# ---------------------------------------------------------------------------


class _FakePlugin:
    """Minimal plugin stub for testing."""

    def __init__(self, schema):
        self._schema = schema

    def build_settings_schema(self):
        return self._schema


class TestValidatePluginRequiredFields:
    def _make_schema(self, fields):
        """Build a schema dict with one section containing the given fields."""
        return {
            "sections": [
                {
                    "items": [
                        {
                            "kind": "field",
                            "name": f["name"],
                            "label": f.get("label", f["name"]),
                            "required": f.get("required", True),
                        }
                        for f in fields
                    ]
                }
            ]
        }

    def test_returns_none_when_all_present(self):
        plugin = _FakePlugin(self._make_schema([{"name": "city", "label": "City"}]))
        result = validate_plugin_required_fields(plugin, {"city": "London"})
        assert result is None

    def test_returns_error_for_missing_field(self):
        plugin = _FakePlugin(self._make_schema([{"name": "city", "label": "City"}]))
        result = validate_plugin_required_fields(plugin, {})
        assert result is not None
        assert "City" in result

    def test_returns_error_for_empty_string(self):
        plugin = _FakePlugin(self._make_schema([{"name": "city", "label": "City"}]))
        result = validate_plugin_required_fields(plugin, {"city": ""})
        assert result is not None

    def test_optional_field_not_flagged(self):
        schema = {
            "sections": [
                {
                    "items": [
                        {
                            "kind": "field",
                            "name": "opt",
                            "label": "Opt",
                            "required": False,
                        }
                    ]
                }
            ]
        }
        plugin = _FakePlugin(schema)
        result = validate_plugin_required_fields(plugin, {})
        assert result is None

    def test_row_kind_recurses(self):
        schema = {
            "sections": [
                {
                    "items": [
                        {
                            "kind": "row",
                            "items": [
                                {
                                    "kind": "field",
                                    "name": "inner",
                                    "label": "Inner",
                                    "required": True,
                                }
                            ],
                        }
                    ]
                }
            ]
        }
        plugin = _FakePlugin(schema)
        result = validate_plugin_required_fields(plugin, {})
        assert result is not None
        assert "Inner" in result

    def test_no_schema_method_returns_none(self):
        class NoSchema:
            pass

        result = validate_plugin_required_fields(NoSchema(), {})
        assert result is None

    def test_schema_raises_returns_none(self):
        class BrokenPlugin:
            def build_settings_schema(self):
                raise RuntimeError("broken")

        result = validate_plugin_required_fields(BrokenPlugin(), {})
        assert result is None

    def test_multiple_missing_all_listed(self):
        schema = self._make_schema(
            [{"name": "a", "label": "FieldA"}, {"name": "b", "label": "FieldB"}]
        )
        plugin = _FakePlugin(schema)
        result = validate_plugin_required_fields(plugin, {})
        assert result is not None
        assert "FieldA" in result
        assert "FieldB" in result


# ---------------------------------------------------------------------------
# FormRequest
# ---------------------------------------------------------------------------


class TestFormRequest:
    def test_construction_defaults(self):
        fr = FormRequest()
        assert fr.plugin_id == ""
        assert fr.data == {}
        assert fr.extra == {}

    def test_from_dict_extracts_plugin_id(self):
        raw = {"plugin_id": "weather", "city": "Paris"}
        fr = FormRequest.from_dict(raw)
        assert fr.plugin_id == "weather"
        assert fr.data["city"] == "Paris"

    def test_from_dict_preserves_all_keys(self):
        raw = {"plugin_id": "x", "a": "1", "b": "2"}
        fr = FormRequest.from_dict(raw)
        assert fr.data["a"] == "1"
        assert fr.data["b"] == "2"

    def test_from_dict_missing_plugin_id(self):
        fr = FormRequest.from_dict({"setting": "value"})
        assert fr.plugin_id == ""

    def test_immutability(self):
        fr = FormRequest(data={"x": "1"}, plugin_id="p")
        with pytest.raises((AttributeError, TypeError)):
            fr.plugin_id = "other"  # type: ignore[misc]

    def test_explicit_construction(self):
        fr = FormRequest(data={"k": "v"}, plugin_id="myplug", extra={"meta": True})
        assert fr.extra["meta"] is True

    def test_from_dict_none_plugin_id_gives_empty_string(self):
        fr = FormRequest.from_dict({"plugin_id": None})
        assert fr.plugin_id == ""
