# pyright: reportMissingImports=false
"""Regression test for JTN-314: wizard nav buttons must not use DOM ids.

The initializeWizard() method in progressive_disclosure.js previously injected
buttons with id="wizardPrev" and id="wizardNext".  Because the plugin.html
template always includes a hidden .setup-wizard placeholder, those ids appeared
in the rendered HTML of every plugin settings page — producing 136 duplicate-id
findings in the 2026-04-06 dogfood audit.

Fix: buttons now use data-wizard-prev / data-wizard-next attributes instead of
ids, and an early-return guard prevents any navigation from being injected into
an empty wizard container.
"""

import re
from pathlib import Path

# Plugin ids that can be rendered without external API credentials
_RENDERABLE_PLUGINS = [
    "clock",
    "calendar",
    "weather",
    "ai_image",
    "rss",
    "countdown",
    "year_progress",
]

_JS_PATH = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "static"
    / "scripts"
    / "progressive_disclosure.js"
)


# ---------------------------------------------------------------------------
# Static JS source checks
# ---------------------------------------------------------------------------


def test_wizard_buttons_use_data_attributes_not_ids():
    """progressive_disclosure.js must not emit id="wizardPrev" or id="wizardNext"."""
    source = _JS_PATH.read_text(encoding="utf-8")
    assert 'id="wizardPrev"' not in source, (
        'progressive_disclosure.js still uses id="wizardPrev" — '
        "switch to data-wizard-prev attribute"
    )
    assert 'id="wizardNext"' not in source, (
        'progressive_disclosure.js still uses id="wizardNext" — '
        "switch to data-wizard-next attribute"
    )


def test_wizard_js_queries_data_attributes():
    """JS must query wizard buttons via [data-wizard-prev]/[data-wizard-next]."""
    source = _JS_PATH.read_text(encoding="utf-8")
    assert (
        "[data-wizard-prev]" in source
    ), "progressive_disclosure.js must use querySelector('[data-wizard-prev]')"
    assert (
        "[data-wizard-next]" in source
    ), "progressive_disclosure.js must use querySelector('[data-wizard-next]')"


def test_wizard_empty_container_guard_present():
    """initializeWizard must return early when there are no wizard steps."""
    source = _JS_PATH.read_text(encoding="utf-8")
    # Expect a guard like: if (steps.length === 0) return;
    assert re.search(
        r"steps\.length\s*===\s*0.*return", source, re.DOTALL
    ), "initializeWizard should have an early-return guard for empty step lists"


# ---------------------------------------------------------------------------
# Rendered HTML checks — no id="wizardPrev" or id="wizardNext" in page HTML
# ---------------------------------------------------------------------------


def _find_duplicate_ids(html: str) -> list[str]:
    """Return a list of id values that appear more than once in the HTML."""
    ids = re.findall(r'\bid="([^"]+)"', html)
    seen: dict[str, int] = {}
    for id_val in ids:
        seen[id_val] = seen.get(id_val, 0) + 1
    return [id_val for id_val, count in seen.items() if count > 1]


def test_plugin_pages_have_no_wizard_id_attributes(client):
    """Rendered plugin pages must not contain id='wizardPrev' or id='wizardNext'."""
    for plugin_id in _RENDERABLE_PLUGINS:
        resp = client.get(f"/plugin/{plugin_id}")
        if resp.status_code != 200:
            continue
        html = resp.get_data(as_text=True)
        assert (
            'id="wizardPrev"' not in html
        ), f'/plugin/{plugin_id} HTML contains id="wizardPrev" (JTN-314)'
        assert (
            'id="wizardNext"' not in html
        ), f'/plugin/{plugin_id} HTML contains id="wizardNext" (JTN-314)'


def test_plugin_pages_have_no_duplicate_ids(client):
    """Rendered plugin pages must not contain any duplicate id attributes."""
    for plugin_id in _RENDERABLE_PLUGINS:
        resp = client.get(f"/plugin/{plugin_id}")
        if resp.status_code != 200:
            continue
        html = resp.get_data(as_text=True)
        dupes = _find_duplicate_ids(html)
        assert (
            dupes == []
        ), f"/plugin/{plugin_id} has duplicate id attribute(s): {dupes}"
