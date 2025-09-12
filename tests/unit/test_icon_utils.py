import io
import xml.etree.ElementTree as ET

from src.utils.icon_utils import render_icon


def setup_svg(monkeypatch, svg_content: str, name: str):
    from src.utils import icon_utils
    def fake_isfile(path: str) -> bool:
        return path.endswith(f"{name}.svg")
    def fake_open(path: str, mode: str = "r", encoding: str | None = None):
        return io.StringIO(svg_content)
    monkeypatch.setattr(icon_utils.os.path, "isfile", fake_isfile)
    import builtins
    monkeypatch.setattr(builtins, "open", fake_open)


def test_render_icon_adds_attrs(monkeypatch):
    svg = "<svg width='24' height='24'></svg>"
    setup_svg(monkeypatch, svg, "test")
    result = render_icon("test", class_name="cls", title="Hello")
    root = ET.fromstring(str(result))
    assert root.attrib["class"] == "cls"
    assert root.attrib["width"] == "24"
    assert root.attrib["height"] == "24"
    title = root.find("title")
    assert title is not None and title.text == "Hello"


def test_render_icon_preserves_existing_title(monkeypatch):
    svg = "<svg class='existing'><title>Old</title></svg>"
    setup_svg(monkeypatch, svg, "existing")
    result = render_icon("existing", class_name="new", title="New")
    root = ET.fromstring(str(result))
    # class should remain unchanged
    assert root.attrib["class"] == "existing"
    # title should not be replaced
    title = root.find("title")
    assert title is not None and title.text == "Old"


def test_render_icon_no_attributes(monkeypatch):
    svg = "<svg></svg>"
    setup_svg(monkeypatch, svg, "plain")
    result = render_icon("plain", class_name="cls", title="Hi")
    root = ET.fromstring(str(result))
    assert root.attrib["class"] == "cls"
    title = root.find("title")
    assert title is not None and title.text == "Hi"
