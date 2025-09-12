import os
import xml.etree.ElementTree as ET
from markupsafe import Markup


def render_icon(name: str, class_name: str = "icon-image", title: str | None = None) -> Markup:
    """Render an icon by inlining a local SVG if present, else fall back to Phosphor class.

    Looks for static/icons/ph/{name}.svg. If found, returns the file content wrapped with
    class and optional title attributes. Otherwise, returns an <i> tag that expects
    Phosphor CSS classes to render.
    """
    try:
        base_dir = os.path.dirname(os.path.dirname(__file__))  # src/
        svg_path = os.path.join(base_dir, "static", "icons", "ph", f"{name}.svg")
        if os.path.isfile(svg_path):
            with open(svg_path, "r", encoding="utf-8") as f:
                svg = f.read()

            try:
                root = ET.fromstring(svg)
            except ET.ParseError:
                # If the SVG cannot be parsed, fall through to the fallback below
                raise

            if "class" not in root.attrib:
                root.set("class", class_name)

            if title:
                has_title = any(child.tag.split("}", 1)[-1] == "title" for child in root)
                if not has_title:
                    ns = root.tag.split("}", 1)[0].strip("{") if root.tag.startswith("{") else None
                    title_tag = f"{{{ns}}}title" if ns else "title"
                    title_elem = ET.Element(title_tag)
                    title_elem.text = title
                    root.insert(0, title_elem)

            svg = ET.tostring(root, encoding="unicode")
            return Markup(svg)
    except Exception:
        # On any failure, fall through to class-based fallback
        pass
    # Fallback: Phosphor class (requires stylesheet)
    title_attr = f' title="{title}"' if title else ""
    return Markup(f'<i class="ph ph-{name} ph-thin {class_name}" aria-hidden="true"{title_attr}></i>')


