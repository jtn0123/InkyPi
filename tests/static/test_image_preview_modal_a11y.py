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
    """plugin.html must render the image preview modal via the a11y-compliant macro.

    The modal was refactored to use the shared `modal()` macro (JTN-503) which
    emits `aria-labelledby="<id>Title"` automatically. We verify plugin.html
    invokes it with id='imagePreviewModal', and that the macro itself emits
    the expected aria-labelledby attribute.
    """
    plugin = (_TEMPLATES_DIR / "plugin.html").read_text(encoding="utf-8")
    assert (
        "modal('imagePreviewModal'" in plugin
        or 'modal("imagePreviewModal"' in plugin
        or 'aria-labelledby="imagePreviewTitle"' in plugin
    ), (
        "plugin.html must render #imagePreviewModal via the modal() macro "
        "or include aria-labelledby='imagePreviewTitle' directly"
    )

    macros = (_TEMPLATES_DIR / "macros" / "components.html").read_text(encoding="utf-8")
    assert (
        'aria-labelledby="{{ title_id }}"' in macros
    ), "modal() macro must emit aria-labelledby for the accessible name"


def test_plugin_html_image_preview_modal_labelledby_target_exists():
    """The id referenced by aria-labelledby must exist inside the modal.

    Either rendered directly in plugin.html, or emitted by the shared modal()
    macro which creates an <h2 id="{{ id }}Title"> for the accessible name.
    """
    plugin = (_TEMPLATES_DIR / "plugin.html").read_text(encoding="utf-8")
    # Direct usage path (pre-macro templates) still works.
    modal_start = plugin.find('id="imagePreviewModal"')
    if modal_start != -1:
        modal_end = plugin.find("</div>", plugin.find("</div>", modal_start) + 1) + len(
            "</div>"
        )
        modal_block = plugin[modal_start:modal_end]
        assert 'id="imagePreviewTitle"' in modal_block, (
            "Element with id='imagePreviewTitle' must exist inside "
            "#imagePreviewModal in plugin.html"
        )
        return

    # Macro path: plugin.html calls modal('imagePreviewModal', ...) and the
    # macro creates <h2 id="{{ id }}Title"> for the accessible name.
    assert (
        "modal('imagePreviewModal'" in plugin or 'modal("imagePreviewModal"' in plugin
    ), "#imagePreviewModal must be rendered by plugin.html (direct or via macro)"

    macros = (_TEMPLATES_DIR / "macros" / "components.html").read_text(encoding="utf-8")
    assert (
        '<h2 id="{{ title_id }}"' in macros
    ), "modal() macro must create an h2 with id=<modal_id>Title for a11y"


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

    # The modal() macro (JTN-503) emits aria-labelledby="<id>Title", so when
    # called with id='imagePreviewModal' the title id becomes
    # 'imagePreviewModalTitle'. The original hand-written modal used
    # 'imagePreviewTitle'. Accept either for template-refactor resilience.
    import re

    m = re.search(
        r'id=[\'"]imagePreviewModal[\'"][^>]*aria-labelledby=[\'"]([^\'"]+)[\'"]',
        html,
    )
    assert m is not None, (
        "Rendered plugin page must have aria-labelledby on #imagePreviewModal "
        "(checked with either quote style)"
    )
    labelled_by_id = m.group(1)
    assert labelled_by_id in {"imagePreviewTitle", "imagePreviewModalTitle"}, (
        "Rendered plugin page must reference 'imagePreviewTitle' or "
        f"'imagePreviewModalTitle' for aria-labelledby; got '{labelled_by_id}'"
    )

    assert f'id="{labelled_by_id}"' in html or f"id='{labelled_by_id}'" in html, (
        f"Rendered plugin page must contain an element with id='{labelled_by_id}' "
        "(the aria-labelledby target)"
    )
