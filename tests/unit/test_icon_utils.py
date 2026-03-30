import builtins
import io
import re

from utils import icon_utils


def _setup_svg(monkeypatch, svg_content):
    monkeypatch.setattr(icon_utils.os.path, "isfile", lambda path: True)

    def fake_open(*args, **kwargs):
        return io.StringIO(svg_content)

    monkeypatch.setattr(builtins, "open", fake_open)


def test_title_injected_with_xml_declaration(monkeypatch):
    svg_content = (
        "<?xml version='1.0' encoding='UTF-8'?>\n"
        "<svg xmlns='http://www.w3.org/2000/svg'></svg>"
    )
    _setup_svg(monkeypatch, svg_content)
    result = icon_utils.render_icon("test", title="MyIcon")
    assert "<title>MyIcon</title>" in result
    assert re.search(r"<svg[^>]*><title>MyIcon</title>", str(result))


def test_title_xss_is_escaped(monkeypatch):
    svg_content = "<svg xmlns='http://www.w3.org/2000/svg'></svg>"
    _setup_svg(monkeypatch, svg_content)
    result = icon_utils.render_icon("test", title='<script>alert("xss")</script>')
    assert "<script>" not in str(result)
    assert "&lt;script&gt;" in str(result)


def test_title_xss_escaped_in_fallback():
    # When SVG file doesn't exist, fallback uses title attr
    result = icon_utils.render_icon(
        "nonexistent_icon_xyz", title='"onmouseover="alert(1)'
    )
    result_str = str(result)
    # The double-quote in the title should be escaped as &quot; or &#34;
    assert '"onmouseover=' not in result_str
    assert "&#34;" in result_str or "&quot;" in result_str


def test_svg_with_existing_class_not_duplicated(monkeypatch):
    """SVG that already has a class attribute should not get a second one."""
    svg_content = '<svg class="existing" xmlns="http://www.w3.org/2000/svg"></svg>'
    _setup_svg(monkeypatch, svg_content)
    result = str(icon_utils.render_icon("test", class_name="my-icon"))
    # Should NOT inject another class attr
    assert result.count("class=") == 1
    assert 'class="existing"' in result


def test_svg_without_title_no_title_injected(monkeypatch):
    """When no title is provided, no <title> tag should be injected."""
    svg_content = '<svg xmlns="http://www.w3.org/2000/svg"><rect/></svg>'
    _setup_svg(monkeypatch, svg_content)
    result = str(icon_utils.render_icon("test"))
    assert "<title>" not in result


def test_svg_with_existing_title_not_duplicated(monkeypatch):
    """SVG that already has a <title> should not get a second one."""
    svg_content = (
        '<svg xmlns="http://www.w3.org/2000/svg"><title>Original</title></svg>'
    )
    _setup_svg(monkeypatch, svg_content)
    result = str(icon_utils.render_icon("test", title="NewTitle"))
    assert result.count("<title>") == 1
    assert "Original" in result


def test_exception_falls_back_to_class_icon(monkeypatch):
    """Any exception in SVG loading should produce the Phosphor fallback."""
    monkeypatch.setattr(icon_utils.os.path, "isfile", lambda path: True)

    def raise_on_open(*args, **kwargs):
        raise OSError("disk error")

    monkeypatch.setattr(builtins, "open", raise_on_open)
    result = str(icon_utils.render_icon("test"))
    assert "ph ph-test" in result
    assert "<svg" not in result


def test_fallback_without_title():
    """Fallback icon without title should have no title attribute."""
    result = str(icon_utils.render_icon("nonexistent_xyz"))
    assert "ph ph-nonexistent_xyz" in result
    assert "title=" not in result


def test_title_injected_with_doctype(monkeypatch):
    svg_content = (
        "<!DOCTYPE svg PUBLIC '-//W3C//DTD SVG 1.1//EN' "
        "'http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd'>\n"
        "<svg xmlns='http://www.w3.org/2000/svg'></svg>"
    )
    _setup_svg(monkeypatch, svg_content)
    result = icon_utils.render_icon("test", title="DocIcon")
    assert "<title>DocIcon</title>" in result
    assert re.search(r"<svg[^>]*><title>DocIcon</title>", str(result))
