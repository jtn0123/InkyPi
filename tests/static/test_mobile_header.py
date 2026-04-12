# pyright: reportMissingImports=false
"""Regression tests for mobile dashboard header (JTN-340).

The `/` dashboard header rendered `InkyPi Development` (or any long
device name) clipped on the right at narrow viewports (< 430px) because
`.app-title` had no overflow handling and `.title-container` did not
allow flex children to shrink below their content size.

We assert the CSS now guards against this by:
- `.app-title` using `text-overflow: ellipsis` with `overflow: hidden`
  and `white-space: nowrap` so long names truncate cleanly instead of
  overflowing the header container.
- `.title-container` using `min-width: 0` so the title can actually
  shrink inside a flex row (the default `min-width: auto` prevents
  ellipsis truncation on flex children).
- The dashboard template exposing the full name via a `title`
  attribute so screen readers and hover tooltips still convey the
  untruncated device name.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_STYLES_DIR = _REPO_ROOT / "src" / "static" / "styles"
_INKY_TEMPLATE = _REPO_ROOT / "src" / "templates" / "inky.html"


def _read_all_css() -> str:
    parts = [
        p.read_text(encoding="utf-8")
        for p in sorted(_STYLES_DIR.glob("partials/_*.css"))
    ]
    return "\n".join(parts)


def _extract_rule(css: str, selector: str) -> str:
    """Return the body of the first CSS rule whose selector list
    contains *selector* at the top level (not inside @media)."""
    # Strip @media blocks so we only match global rules.
    depth = 0
    stripped: list[str] = []
    in_media = False
    i = 0
    while i < len(css):
        if css[i : i + 6] == "@media" and depth == 0:
            in_media = True
            while i < len(css) and css[i] != "{":
                i += 1
            depth = 1
            i += 1
            continue
        if in_media:
            if css[i] == "{":
                depth += 1
            elif css[i] == "}":
                depth -= 1
                if depth == 0:
                    in_media = False
            i += 1
            continue
        stripped.append(css[i])
        i += 1
    global_css = "".join(stripped)

    pattern = re.compile(
        r"(^|[},])\s*([^{}]*?" + re.escape(selector) + r"[^{}]*?)\{([^{}]*)\}",
        re.MULTILINE | re.DOTALL,
    )
    for match in pattern.finditer(global_css):
        selectors = match.group(2)
        for part in selectors.split(","):
            if part.strip().endswith(selector):
                return match.group(3)
    return ""


def test_app_title_truncates_with_ellipsis():
    """`.app-title` must not allow long names to clip the header (JTN-340)."""
    css = _read_all_css()
    body = _extract_rule(css, ".app-title")
    assert body, "No `.app-header .app-title` rule found in CSS partials"
    assert "text-overflow: ellipsis" in body, (
        "`.app-title` must set `text-overflow: ellipsis` so long device "
        "names truncate instead of clipping on narrow viewports (JTN-340)."
    )
    assert "overflow: hidden" in body, (
        "`.app-title` must set `overflow: hidden` to pair with "
        "`text-overflow: ellipsis` (JTN-340)."
    )
    assert "white-space: nowrap" in body, (
        "`.app-title` must set `white-space: nowrap` so ellipsis "
        "truncation activates on overflow (JTN-340)."
    )
    assert "min-width: 0" in body, (
        "`.app-title` needs `min-width: 0` so flex parents can shrink it "
        "below its intrinsic content width (JTN-340)."
    )


def test_title_container_allows_shrink():
    """`.title-container` must allow the title to shrink inside flex (JTN-340)."""
    css = _read_all_css()
    body = _extract_rule(css, ".title-container")
    assert body, "No `.title-container` rule found in CSS partials"
    assert "min-width: 0" in body, (
        "`.title-container` must set `min-width: 0` so its child title "
        "can shrink below its content width and trigger ellipsis "
        "truncation on narrow viewports (JTN-340)."
    )


def test_dashboard_header_exposes_full_name_via_title_attr():
    """Full device name must remain accessible when truncated (JTN-340)."""
    html = _INKY_TEMPLATE.read_text(encoding="utf-8")
    assert 'class="app-title"' in html, "app-title element missing from inky.html"
    # The h1 should carry a title attribute so hover/a11y still surfaces
    # the full device name even when CSS truncates it with ellipsis.
    pattern = re.compile(
        r"<h1[^>]*class=\"app-title\"[^>]*title=\"\{\{\s*config\.name\s*\}\}\"",
    )
    assert pattern.search(html), (
        "`.app-title` <h1> must expose the full `config.name` via a "
        "`title` attribute so truncated names remain discoverable (JTN-340)."
    )
