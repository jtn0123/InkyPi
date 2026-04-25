# pyright: reportMissingImports=false
from plugins.base_plugin.settings_schema import (
    callout,
    field,
    option,
    row,
    schema,
    section,
    widget,
)


def test_option_basic() -> None:
    result = option("dark", "Dark Mode")
    assert result["value"] == "dark"
    assert result["label"] == "Dark Mode"


def test_option_extra_kwargs() -> None:
    result = option("en", "English", selected=True)
    assert result["selected"] is True


def test_field_defaults() -> None:
    result = field("username")
    assert result["kind"] == "field"
    assert result["type"] == "text"
    assert result["name"] == "username"
    assert result["label"] == "username"  # label falls back to name


def test_field_custom_label_and_type() -> None:
    result = field("refresh_rate", field_type="number", label="Refresh Rate (s)")
    assert result["type"] == "number"
    assert result["label"] == "Refresh Rate (s)"


def test_row_wraps_items() -> None:
    f1 = field("a")
    f2 = field("b")
    result = row(f1, f2)
    assert result["kind"] == "row"
    assert result["items"] == [f1, f2]


def test_callout_defaults_and_title() -> None:
    result = callout("Watch out!", title="Warning")
    assert result["kind"] == "callout"
    assert result["tone"] == "info"
    assert result["icon"] == "info"
    assert result["title"] == "Warning"
    assert result["text"] == "Watch out!"


def test_callout_without_title_omits_key() -> None:
    result = callout("Note")
    assert "title" not in result


def test_widget_basic() -> None:
    result = widget("color_picker", name="bg_color")
    assert result["kind"] == "widget"
    assert result["widget_type"] == "color_picker"
    assert result["name"] == "bg_color"


def test_section_and_schema_structure() -> None:
    f = field("city")
    sec = section("Location", f)
    assert sec["title"] == "Location"
    assert sec["items"] == [f]

    result = schema(sec)
    assert result["version"] == 1
    assert result["sections"] == [sec]
