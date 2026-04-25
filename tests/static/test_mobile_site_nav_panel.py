"""Regression guard: mobile site nav dropdown must not clip items at the
viewport right edge.

Background: at narrow viewports (≤900px), `.shell-sidebar` becomes a 3-column
grid and `.mobile-site-nav` lives in the middle column. The dropdown
`.mobile-site-nav-panel` was previously positioned with `left: 0; right: 0`,
which clipped its width to that narrow middle column — at a 390px viewport
the right edge of every nav item (notably "API Keys") was visibly cut off.

The fix anchors the panel to the right edge of the button column, gives it
a `min-width` that lets it grow leftward into the brand column, and caps it
at viewport width minus the page padding.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SIDEBAR_CSS = ROOT / "src" / "static" / "styles" / "partials" / "_sidebar.css"

CSS_COMMENT_RE = re.compile(r"/\*.*?\*/", re.S)


def _block_for_selector(css: str, selector: str) -> str:
    """Return the body of the *first* CSS rule whose selector list contains
    `selector` exactly. Comments are stripped first so `/*…*/` text inside
    declarations doesn't confuse the regex."""
    cleaned = CSS_COMMENT_RE.sub("", css)
    normalized = " ".join(selector.split())
    for match in re.finditer(
        r"(?P<sels>[^{}]+)\{(?P<body>[^}]*)\}",
        cleaned,
        re.S,
    ):
        sels = [
            " ".join(s.split()) for s in match.group("sels").split(",") if s.strip()
        ]
        if normalized in sels:
            return match.group("body")
    raise AssertionError(f"selector {selector!r} not found in CSS")


def test_mobile_site_nav_panel_does_not_clip_to_grid_column():
    """The panel must NOT use `left: 0` paired with `right: 0` — that pins
    its width to the narrow middle column of the sidebar grid and clips
    items. It should anchor to one edge with a `min-width`/`max-width`
    that lets the dropdown spill across the parent column boundaries."""
    css = SIDEBAR_CSS.read_text(encoding="utf-8")
    block = _block_for_selector(css, ".mobile-site-nav-panel")

    has_left_zero = re.search(r"\bleft:\s*0\b", block)
    has_right_zero = re.search(r"\bright:\s*0\b", block)
    assert not (has_left_zero and has_right_zero), (
        "Panel must not pin BOTH left:0 and right:0 — that constrains it "
        "to the narrow middle grid column and clips item labels at 390px."
    )
    # Must declare some width-affordance so the dropdown can outgrow the column.
    assert (
        "min-width" in block
    ), "Panel needs a min-width so it can extend beyond the narrow column"
    assert (
        "max-width" in block and "100vw" in block
    ), "Panel needs a viewport-bounded max-width so it doesn't spill off-screen"


def test_mobile_site_nav_panel_anchors_to_right_edge():
    """We anchor to the right edge so the panel grows leftward (into the
    brand column) on narrow viewports — an explicit choice worth pinning."""
    css = SIDEBAR_CSS.read_text(encoding="utf-8")
    block = _block_for_selector(css, ".mobile-site-nav-panel")
    assert re.search(
        r"\bright:\s*0\b", block
    ), "Panel should anchor to right:0; if you change anchor side, update this test."
