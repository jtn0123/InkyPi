# pyright: reportMissingImports=false
"""
Tests for ARIA landmark roles and skip-to-content link (JTN-296 partial).

Verifies that:
- Base template contains a skip-to-content link pointing to #main-content
- All main pages contain role="main" (or <main>) with id="main-content"
- All main pages contain role="banner" (or <header>) for the page header
- The dashboard page exposes a role="navigation" for the site-nav links
- Skip link CSS positions it off-screen by default
"""

import re
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MAIN_PAGES = [
    "/",
    "/settings",
    "/playlist",
    "/plugin/clock",
    "/api-keys",
    "/history",
]


def _html(client, path: str) -> str:
    resp = client.get(path)
    assert resp.status_code == 200, f"Expected 200 for {path}, got {resp.status_code}"
    return resp.get_data(as_text=True)


# ---------------------------------------------------------------------------
# Skip-to-content link
# ---------------------------------------------------------------------------


def test_base_template_has_skip_link(client):
    """Every page rendered from base.html must have a visible-on-focus skip link."""
    html = _html(client, "/")
    assert 'href="#main-content"' in html, "Skip link href='#main-content' not found"
    assert "skip-link" in html, "skip-link CSS class not found"


@pytest.mark.parametrize("path", MAIN_PAGES)
def test_all_pages_have_skip_link(client, path):
    """All main pages must include the skip-to-content link."""
    html = _html(client, path)
    assert 'href="#main-content"' in html, f"Skip link missing on {path}"


# ---------------------------------------------------------------------------
# role="main" / <main id="main-content">
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", MAIN_PAGES)
def test_all_pages_have_main_landmark(client, path):
    """All main pages must have <main> (or role='main') with id='main-content'."""
    html = _html(client, path)
    has_main_tag = bool(re.search(r'<main\b[^>]*id=["\']main-content["\']', html))
    has_role_main = bool(
        re.search(r'id=["\']main-content["\'][^>]*role=["\']main["\']', html)
        or re.search(r'role=["\']main["\'][^>]*id=["\']main-content["\']', html)
    )
    assert (
        has_main_tag or has_role_main
    ), f"No <main id='main-content'> or role='main' with id='main-content' on {path}"


# ---------------------------------------------------------------------------
# role="banner" / <header>
# Plugin pages are out of scope for this PR (JTN-296 partial).
# ---------------------------------------------------------------------------

BANNER_PAGES = [p for p in MAIN_PAGES if not p.startswith("/plugin")]


@pytest.mark.parametrize("path", BANNER_PAGES)
def test_shared_layout_pages_have_banner_landmark(client, path):
    """Shared-layout pages (non-plugin) must have <header role='banner'>."""
    html = _html(client, path)
    has_banner = bool(re.search(r'role=["\']banner["\']', html))
    assert has_banner, f"No role='banner' found on {path}"


# ---------------------------------------------------------------------------
# role="navigation" (dashboard only — it has the site-level nav links)
# ---------------------------------------------------------------------------


def test_dashboard_has_navigation_landmark(client):
    """Dashboard (home) page must expose role='navigation' for the site nav."""
    html = _html(client, "/")
    has_nav_tag = "<nav " in html or "<nav>" in html
    has_role_nav = 'role="navigation"' in html
    assert (
        has_nav_tag or has_role_nav
    ), "No <nav> or role='navigation' found on the dashboard page"


# ---------------------------------------------------------------------------
# Skip link CSS — must position off-screen by default
# ---------------------------------------------------------------------------


def test_skip_link_css_offscreen():
    """The .skip-link rule must use a negative top/left or clip to hide off-screen."""
    layout_css = (
        Path(__file__).parent.parent.parent
        / "src"
        / "static"
        / "styles"
        / "partials"
        / "_layout.css"
    )
    assert layout_css.exists(), f"_layout.css not found at {layout_css}"
    css = layout_css.read_text(encoding="utf-8")

    # Find the .skip-link block
    match = re.search(r"\.skip-link\s*\{([^}]+)\}", css)
    assert match, ".skip-link rule not found in _layout.css"

    block = match.group(1)
    # Must use a mechanism that hides it off-screen by default
    offscreen = (
        "top: -" in block
        or "left: -" in block
        or "clip:" in block
        or "clip-path:" in block
        or "transform: translate" in block
    )
    assert offscreen, (
        ".skip-link must be positioned off-screen by default; "
        f"found block: {block!r}"
    )
