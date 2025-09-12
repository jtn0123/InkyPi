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
