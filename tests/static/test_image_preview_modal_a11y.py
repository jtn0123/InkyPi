# pyright: reportMissingImports=false
"""Accessibility tests for the image preview lightbox modal (JTN-467).

Ensures the modal has a proper aria-labelledby attribute pointing to an
existing element, satisfying WCAG 2.1 SC 4.1.2 (Name, Role, Value).
"""

import re
from pathlib import Path

_TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "src" / "templates"
_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "src" / "static" / "scripts"


def test_plugin_html_image_preview_modal_has_aria_labelledby():
    """plugin.html must have aria-labelledby on #imagePreviewModal."""
    content = (_TEMPLATES_DIR / "plugin.html").read_text(encoding="utf-8")
    assert (
        'aria-labelledby="imagePreviewTitle"' in content
    ), "#imagePreviewModal in plugin.html must have aria-labelledby='imagePreviewTitle'"


def test_plugin_html_image_preview_modal_labelledby_target_exists():
    """The id referenced by aria-labelledby must exist inside the modal in plugin.html."""
    content = (_TEMPLATES_DIR / "plugin.html").read_text(encoding="utf-8")
    # Find the modal block
    modal_start = content.find('id="imagePreviewModal"')
    assert modal_start != -1, "#imagePreviewModal not found in plugin.html"
    # Find the end of the modal div (closing tag after modal-content)
    modal_end = content.find("</div>", content.find("</div>", modal_start) + 1) + len(
        "</div>"
    )
    modal_block = content[modal_start:modal_end]
    assert (
        'id="imagePreviewTitle"' in modal_block
    ), "Element with id='imagePreviewTitle' must exist inside #imagePreviewModal in plugin.html"


def test_lightbox_js_dynamic_modal_uses_aria_labelledby():
    """lightbox.js must use aria-labelledby (not just aria-label) on the dynamically created modal."""
    content = (_SCRIPTS_DIR / "lightbox.js").read_text(encoding="utf-8")
    assert (
        "aria-labelledby" in content
    ), "lightbox.js must set aria-labelledby on the dynamically-created modal"
    assert (
        "imagePreviewTitle" in content
    ), "lightbox.js must reference 'imagePreviewTitle' for aria-labelledby"


def test_lightbox_js_dynamic_modal_creates_heading_element():
    """lightbox.js must create an h2 heading with id='imagePreviewTitle' for screen readers."""
    content = (_SCRIPTS_DIR / "lightbox.js").read_text(encoding="utf-8")
    assert re.search(
        r"createElement\(['\"]h2['\"]\)", content
    ), "lightbox.js must create an h2 element for the accessible modal name"
    assert (
        "heading.id = 'imagePreviewTitle'" in content
    ), "lightbox.js must set heading.id = 'imagePreviewTitle'"


def test_plugin_page_rendered_modal_has_aria_labelledby(client):
    """Rendered plugin page must contain the modal with aria-labelledby and the target id."""
    resp = client.get("/plugin/clock")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    assert (
        'aria-labelledby="imagePreviewTitle"' in html
    ), "Rendered plugin page must have aria-labelledby='imagePreviewTitle' on #imagePreviewModal"

    assert (
        'id="imagePreviewTitle"' in html
    ), "Rendered plugin page must contain an element with id='imagePreviewTitle'"
