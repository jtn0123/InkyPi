import os
import re
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
            # inject class and title if missing
            # naive injection: add class attribute to first <svg ...>
            cls_attr = f'class="{class_name}"'
            if "<svg" in svg and "class=" not in svg.split("<svg", 1)[1].split(">", 1)[0]:
                svg = svg.replace("<svg", f"<svg {cls_attr}", 1)
            # title
            if title and "<title>" not in svg:
                match = re.search(r"<svg\b[^>]*>", svg, flags=re.IGNORECASE)
                if match:
                    pos = match.end()
                    svg = svg[:pos] + f"<title>{title}</title>" + svg[pos:]
            return Markup(svg)
    except Exception:
        # On any failure, fall through to class-based fallback
        pass
    # Fallback: Phosphor class (requires stylesheet)
    title_attr = f' title="{title}"' if title else ""
    return Markup(f'<i class="ph ph-{name} ph-thin {class_name}" aria-hidden="true"{title_attr}></i>')


