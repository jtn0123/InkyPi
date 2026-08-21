"""Regression guard: the sidebar nav must never clip its own items.

Background: `.sidebar-nav` was `flex: 1` with `overflow-y: auto`, while
`.sidebar-foot` could not shrink. On a short viewport the footer claimed its
full natural height and the nav box ended up smaller than its content — a 258px
box holding 300px of items — so the last entry ("API Keys") sat inside a
scrollable region with no visible scrollbar. It simply looked like the link did
not exist, and whether it appeared depended on how tall the NOW PLAYING card
happened to be, which made it look intermittent.

The fix stops the nav shrinking below its content, lets the footer yield first,
and makes the sidebar itself scroll if even that is not enough. Navigation is
the one thing in the shell that must stay reachable at any viewport height.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SIDEBAR_CSS = ROOT / "src" / "static" / "styles" / "partials" / "_sidebar.css"
MAIN_CSS = ROOT / "src" / "static" / "styles" / "main.css"
SIDEBAR_TEMPLATE = ROOT / "src" / "templates" / "macros" / "sidebar.html"

CSS_COMMENT_RE = re.compile(r"/\*.*?\*/", re.S)


def _block_for_selector(css: str, selector: str) -> str:
    """Return the body of the first rule whose selector list contains *selector*."""
    cleaned = CSS_COMMENT_RE.sub("", css)
    wanted = " ".join(selector.split())
    for match in re.finditer(r"(?P<sels>[^{}]+)\{(?P<body>[^}]*)\}", cleaned, re.S):
        sels = [" ".join(s.split()) for s in match.group("sels").split(",")]
        if wanted in sels:
            return match.group("body")
    raise AssertionError(f"selector {selector!r} not found")


class TestNavDoesNotShrinkBelowItsContent:
    def test_sidebar_nav_does_not_shrink(self) -> None:
        body = _block_for_selector(SIDEBAR_CSS.read_text(), ".sidebar-nav")
        flex = re.search(r"flex:\s*([^;]+);", body)
        assert flex, ".sidebar-nav must declare a flex shorthand"
        shorthand = " ".join(flex.group(1).split())
        # `flex: 1` (== 1 1 0%) is what allowed the nav to be squeezed.
        assert (
            shorthand != "1"
        ), "`flex: 1` lets the nav shrink below its content and clip nav items"
        assert (
            shorthand.split()[1] == "0"
        ), f"flex-shrink must be 0 so nav items are never clipped, got {shorthand!r}"

    def test_sidebar_nav_no_longer_hides_overflow_from_the_user(self) -> None:
        """A scroll container with no scrollbar is indistinguishable from a bug."""
        body = _block_for_selector(SIDEBAR_CSS.read_text(), ".sidebar-nav")
        assert (
            "overflow-y: auto" not in body
        ), "the nav should not be its own scroll container; the sidebar scrolls"

    def test_footer_yields_before_the_nav(self) -> None:
        body = _block_for_selector(SIDEBAR_CSS.read_text(), ".sidebar-foot")
        assert "margin-top: auto" in body, (
            "the footer should be pushed to the bottom rather than competing "
            "with the nav for space"
        )

    def test_sidebar_scrolls_rather_than_clipping(self) -> None:
        body = _block_for_selector(SIDEBAR_CSS.read_text(), ".shell-sidebar")
        assert (
            "overflow: hidden" not in body
        ), "`overflow: hidden` on the sidebar amputates whatever does not fit"
        assert "overflow-y: auto" in body


class TestBundleIsInSync:
    """main.css is generated; a partial-only fix would not reach the browser."""

    def test_fix_is_present_in_the_built_bundle(self) -> None:
        body = _block_for_selector(MAIN_CSS.read_text(), ".sidebar-nav")
        flex = re.search(r"flex:\s*([^;]+);", body)
        assert flex, "no flex shorthand on .sidebar-nav in main.css"
        assert (
            flex.group(1).split()[1] == "0"
        ), "main.css is stale — run scripts/build_css.py"


class TestEveryNavDestinationIsPresent:
    def test_sidebar_lists_all_primary_destinations(self) -> None:
        markup = SIDEBAR_TEMPLATE.read_text()
        sidebar = markup[markup.index('class="sidebar-nav"') :]
        for label in (
            "Dashboard",
            "Playlists",
            "Plugins",
            "History",
            "Settings",
            "API Keys",
        ):
            assert f"<span>{label}</span>" in sidebar, f"{label} missing from sidebar"
