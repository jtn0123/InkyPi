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
    """plugin.html must declare the image preview modal with an accessible name.

    Since JTN-503 the modal is rendered via the ``modal()`` macro in
    ``macros/components.html`` which derives ``aria-labelledby`` from the
    modal id; rather than scanning the raw template (the attribute is
    produced by the macro at render time) we verify the template invokes
    the macro for ``imagePreviewModal``.
    """
    content = (_TEMPLATES_DIR / "plugin.html").read_text(encoding="utf-8")
    assert (
        "modal('imagePreviewModal'" in content
    ), "plugin.html must invoke the modal() macro for 'imagePreviewModal'"


def test_plugin_html_image_preview_modal_labelledby_target_exists():
    """The modal() macro must generate a heading whose id matches aria-labelledby.

    The macro sets ``title_id = id ~ 'Title'`` and emits both the
    ``aria-labelledby`` attribute and the matching ``<h2 id=...>``, so if
    the macro definition is intact we are guaranteed the rendered target
    exists. Assert directly on the macro source to catch regressions.
    """
    macros_path = _TEMPLATES_DIR / "macros" / "components.html"
    content = macros_path.read_text(encoding="utf-8")
    assert (
        "title_id = id ~ 'Title'" in content
    ), "modal() macro must derive title_id from the modal id"
    assert (
        'aria-labelledby="{{ title_id }}"' in content
    ), "modal() macro must set aria-labelledby to the derived title_id"
    assert (
        'id="{{ title_id }}"' in content
    ), "modal() macro must emit a heading with id matching title_id"


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
    """Rendered plugin page must contain the modal with aria-labelledby and the target id.

    After JTN-503 the modal is rendered via the ``modal()`` macro which
    derives the title id from the modal id (``imagePreviewModalTitle``).
    """
    resp = client.get("/plugin/clock")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    assert (
        'aria-labelledby="imagePreviewModalTitle"' in html
    ), "Rendered plugin page must have aria-labelledby='imagePreviewModalTitle' on #imagePreviewModal"

    assert (
        'id="imagePreviewModalTitle"' in html
    ), "Rendered plugin page must contain an element with id='imagePreviewModalTitle'"
