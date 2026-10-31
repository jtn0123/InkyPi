# pyright: reportMissingImports=false
"""Rendered plugin text must stay on the panel.

Long titles, long words and long feeds used to push text off the e-ink panel
or cut it mid-line (Countdown, AI Text, RSS, To-Do List, GitHub). Pixel
baselines only run on Linux, so these checks inspect the DOM instead: each
plugin's template is rendered, loaded in Chromium at the panel size, and every
visible line of text must sit inside the viewport and inside any ancestor that
clips its overflow. Text that a deliberate ``-webkit-line-clamp`` or
``text-overflow: ellipsis`` hides is allowed; that is the intended fix.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

_requires_browser = pytest.mark.skipif(
    os.getenv("REQUIRE_BROWSER_SMOKE", "").lower() not in ("1", "true"),
    reason=(
        "Renders HTML via Playwright Chromium. Set REQUIRE_BROWSER_SMOKE=1 to "
        "run it (see tests/snapshots/README.md)."
    ),
)

pytestmark = _requires_browser

_PLUGINS_DIR = Path(__file__).resolve().parents[2] / "src" / "plugins"

LONG = (
    "The Extraordinarily Long Headline That Keeps Going Well Past Any Reasonable "
    "Width For An E-Ink Panel And Then Some More Words"
)
LONG_WORD = "Llanfairpwllgwyngyllgogerychwyrndrobwllllantysiliogogogoch"
NON_ASCII = "Zürich Café — São Paulo 東京 Ελληνικά"

# Panel sizes after orientation: landscape 7.3", portrait 7.3", 2.13" e-ink.
SIZES = [(800, 480), (480, 800), (250, 122)]

# Collects every visible line of text that escapes the viewport or a clipping
# ancestor. A clamped/ellipsised ancestor is a deliberate cut, so text it
# hides is not reported.
_OVERFLOW_JS = """
() => {
  const tol = 1.5;
  const vw = window.innerWidth, vh = window.innerHeight;
  const deliberate = (el) => {
    const cs = getComputedStyle(el);
    return (cs.webkitLineClamp && cs.webkitLineClamp !== 'none')
      || cs.textOverflow === 'ellipsis';
  };
  const clips = (el) => {
    const cs = getComputedStyle(el);
    return cs.overflowX !== 'visible' || cs.overflowY !== 'visible';
  };
  const problems = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let node;
  while ((node = walker.nextNode())) {
    const text = node.textContent.trim();
    if (!text) continue;
    const parent = node.parentElement;
    if (!parent || ['SCRIPT', 'STYLE'].includes(parent.tagName)) continue;
    if (getComputedStyle(parent).visibility === 'hidden') continue;
    const range = document.createRange();
    range.selectNodeContents(node);
    const rects = [...range.getClientRects()].filter(r => r.width > 0 && r.height > 0);
    let clampedAncestor = false;
    for (let el = parent; el && el !== document.body; el = el.parentElement) {
      if (deliberate(el)) { clampedAncestor = true; break; }
    }
    for (const r of rects) {
      // A text rect is the font's full ascent+descent, which pokes a pixel or
      // two past a tight line-height box even when the line is fully shown;
      // only a cut of more than a quarter of the line counts vertically.
      const vt = Math.max(tol, r.height * 0.25);
      const where = `"${text.slice(0, 40)}" at [${Math.round(r.left)},${Math.round(r.top)},${Math.round(r.right)},${Math.round(r.bottom)}]`;
      if (!clampedAncestor && (r.left < -tol || r.top < -vt || r.right > vw + tol || r.bottom > vh + vt)) {
        problems.push(`off panel: ${where}`);
        continue;
      }
      if (clampedAncestor) continue;
      for (let el = parent; el && el !== document.documentElement; el = el.parentElement) {
        if (!clips(el)) continue;
        const b = el.getBoundingClientRect();
        if (r.left < b.left - tol || r.top < b.top - vt || r.right > b.right + tol || r.bottom > b.bottom + vt) {
          problems.push(`clipped by <${el.tagName.toLowerCase()} class="${el.className}">: ${where}`);
          break;
        }
      }
    }
  }
  return problems;
}
"""


def _plugin(plugin_id: str) -> Any:
    info = json.loads((_PLUGINS_DIR / plugin_id / "plugin-info.json").read_text())
    module = __import__(f"plugins.{plugin_id}.{plugin_id}", fromlist=[info["class"]])
    return getattr(module, info["class"])(info)


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        # Same file-access flags as utils.image_utils so local CSS/fonts load.
        instance = playwright.chromium.launch(
            args=[
                "--allow-file-access-from-files",
                "--enable-local-file-accesses",
                "--disable-web-security",
            ]
        )
        try:
            yield instance
        finally:
            instance.close()


def _render_html(
    plugin_id: str,
    html: str,
    css: str,
    params: dict[str, Any],
    size: tuple[int, int],
) -> str:
    """Render the plugin template to HTML without screenshotting it."""
    plugin = _plugin(plugin_id)
    captured: dict[str, str] = {}

    def capture(rendered_html: str, _dimensions: tuple[int, int]) -> None:
        captured["html"] = rendered_html

    plugin._capture_screenshot = capture
    plugin.render_image(size, html, css, dict(params))
    return captured["html"]


def _load(browser: Any, tmp_path: Path, html: str, size: tuple[int, int]) -> Any:
    path = tmp_path / f"render_{size[0]}x{size[1]}.html"
    path.write_text(html, encoding="utf-8")
    page = browser.new_page(viewport={"width": size[0], "height": size[1]})
    page.goto(f"file://{path}")
    page.wait_for_load_state("load")
    page.evaluate("() => document.fonts ? document.fonts.ready.then(() => true) : true")
    return page


def _assert_text_fits(
    browser: Any,
    tmp_path: Path,
    plugin_id: str,
    html: str,
    css: str,
    params: dict[str, Any],
    size: tuple[int, int],
) -> Any:
    page = _load(
        browser, tmp_path, _render_html(plugin_id, html, css, params, size), size
    )
    problems = page.evaluate(_OVERFLOW_JS)
    assert not problems, f"{plugin_id} at {size[0]}x{size[1]}:\n" + "\n".join(problems)
    return page


def _todo_params(lists: list[tuple[str, list[str]]], title: str) -> dict[str, Any]:
    return {
        "title": title,
        "list_style": "disc",
        "font_scale": 1,
        "lists": [{"title": name, "elements": items} for name, items in lists],
        "plugin_settings": {"textColor": "#000000"},
    }


def _rss_items(count: int, title: str, description: str) -> list[dict[str, Any]]:
    return [
        {"title": f"{title} {i}", "description": description, "image": None}
        for i in range(count)
    ]


@pytest.mark.parametrize("size", SIZES)
@pytest.mark.parametrize("title", [LONG, LONG_WORD, NON_ASCII])
def test_countdown_title_and_count_stay_on_panel(
    browser: Any, tmp_path: Path, size: tuple[int, int], title: str
) -> None:
    params = {
        "title": title,
        "date": "December 25, 2037",
        "day_count": 4242,
        "label": "Days Left",
        "plugin_settings": {},
    }
    page = _assert_text_fits(
        browser, tmp_path, "countdown", "countdown.html", "countdown.css", params, size
    )
    page.close()


@pytest.mark.parametrize("size", SIZES)
def test_ai_text_long_response_is_not_cut_mid_line(
    browser: Any, tmp_path: Path, size: tuple[int, int]
) -> None:
    params = {
        "title": LONG,
        "content": " ".join([LONG] * 4) + " " + LONG_WORD,
        "plugin_settings": {},
    }
    page = _assert_text_fits(
        browser, tmp_path, "ai_text", "ai_text.html", "ai_text.css", params, size
    )
    page.close()


@pytest.mark.parametrize("size", SIZES)
@pytest.mark.parametrize(
    "items",
    [
        _rss_items(10, LONG, "A short description of the story. " + LONG),
        _rss_items(1, LONG_WORD * 2, LONG_WORD * 3),
        _rss_items(5, NON_ASCII, ""),
    ],
    ids=["long", "long_word", "non_ascii"],
)
def test_rss_items_stay_on_panel(
    browser: Any, tmp_path: Path, size: tuple[int, int], items: list[dict[str, Any]]
) -> None:
    params = {
        "title": LONG,
        "items": items,
        "include_images": False,
        "font_scale": 1,
        "plugin_settings": {},
    }
    page = _assert_text_fits(
        browser, tmp_path, "rss", "rss.html", "rss.css", params, size
    )
    page.close()


def test_rss_empty_feed_says_so(browser: Any, tmp_path: Path) -> None:
    params = {
        "title": "Top Stories",
        "items": [],
        "include_images": False,
        "font_scale": 1,
        "plugin_settings": {},
    }
    page = _assert_text_fits(
        browser, tmp_path, "rss", "rss.html", "rss.css", params, (800, 480)
    )
    assert page.locator(".empty-state").is_visible()
    page.close()


@pytest.mark.parametrize("size", SIZES)
@pytest.mark.parametrize(
    "lists,title",
    [
        ([(LONG, [LONG, LONG_WORD, NON_ASCII, "short"])], LONG),
        (
            [
                ("Groceries", [f"Item {i}" for i in range(40)]),
                ("Work", [f"Task {i}" for i in range(25)]),
            ],
            "Tasks",
        ),
    ],
    ids=["long", "many"],
)
def test_todo_list_titles_stay_on_panel(
    browser: Any,
    tmp_path: Path,
    size: tuple[int, int],
    lists: list[tuple[str, list[str]]],
    title: str,
) -> None:
    # Overflowing list items are clipped by the card by design; the check
    # here is that titles and items never leave the panel or run sideways.
    page = _assert_text_fits(
        browser,
        tmp_path,
        "todo_list",
        "todo_list.html",
        "todo_list.css",
        _todo_params(lists, title),
        size,
    )
    page.close()


@pytest.mark.parametrize(
    "lists,expected",
    [([], "No lists yet"), ([("Groceries", [])], "Nothing here")],
    ids=["no_lists", "empty_list"],
)
def test_todo_list_empty_states(
    browser: Any,
    tmp_path: Path,
    lists: list[tuple[str, list[str]]],
    expected: str,
) -> None:
    page = _assert_text_fits(
        browser,
        tmp_path,
        "todo_list",
        "todo_list.html",
        "todo_list.css",
        _todo_params(lists, "Tasks"),
        (800, 480),
    )
    assert expected in page.inner_text("body")
    page.close()


@pytest.mark.parametrize("size", SIZES)
def test_github_long_repository_name_stays_on_panel(
    browser: Any, tmp_path: Path, size: tuple[int, int]
) -> None:
    params = {
        "repository": "some-organisation-name/an-extremely-long-repository-name-here",
        "stars": 1234567,
        "plugin_settings": {"textColor": "#000000"},
    }
    page = _assert_text_fits(
        browser, tmp_path, "github", "github_stars.html", "github.css", params, size
    )
    page.close()


@pytest.mark.parametrize("size", SIZES)
def test_year_progress_bar_is_drawn_without_a_text_colour(
    browser: Any, tmp_path: Path, size: tuple[int, int]
) -> None:
    # /update_now can render with no textColor; the fill used to be
    # transparent then, leaving an invisible bar.
    params = {
        "year": 2026,
        "year_percent": 83,
        "days_left": 62,
        "plugin_settings": {},
    }
    page = _assert_text_fits(
        browser,
        tmp_path,
        "year_progress",
        "year_progress.html",
        "year_progress.css",
        params,
        size,
    )
    fill = page.evaluate(
        "() => getComputedStyle(document.querySelector('.progress-fill')).backgroundColor"
    )
    assert fill not in ("", "transparent", "rgba(0, 0, 0, 0)"), fill
    page.close()
