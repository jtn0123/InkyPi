# pyright: reportMissingImports=false
"""The floating status badge stays readable in every state and theme.

Its colours come from the theme tokens. If a token is renamed or a fallback
creeps back in, the badge can end up with text that fails contrast in one
theme only, so axe's colour-contrast rule is run on each combination.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Page
from tests.integration.browser_helpers import navigate_and_wait

pytestmark = pytest.mark.skipif(
    os.getenv("SKIP_UI", "").lower() in ("1", "true")
    or os.getenv("SKIP_A11Y", "").lower() in ("1", "true"),
    reason="UI / a11y checks skipped by env",
)

_AXE_JS = Path(__file__).resolve().parent.parent / "fixtures" / "axe.min.js"

_SHOW_BADGE_AND_POPOVER = """([state]) => {
    document.querySelectorAll('.test-badge').forEach(n => n.remove());
    const badge = document.createElement('div');
    badge.className = `status-badge status-${state} test-badge`;
    badge.innerHTML = '<span class="status-badge-dot"></span>'
        + '<span class="status-badge-label">2 issues</span>';
    const popover = document.createElement('div');
    popover.className = 'status-popover test-badge';
    popover.innerHTML = '<p class="status-popover-heading">System status</p>'
        + '<ul class="status-popover-list">'
        + '<li class="status-popover-item severity-error"><strong>Error</strong>'
        + ' <span class="status-popover-detail">Display write failed</span></li>'
        + '<li class="status-popover-item severity-warning"><strong>Warning</strong>'
        + ' <span class="status-popover-detail">Disk nearly full</span></li>'
        + '</ul><a class="status-popover-link" href="#">Open diagnostics</a>';
    document.body.append(badge, popover);
}"""


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("state", ["ok", "warning", "error"])
def test_status_badge_text_meets_contrast(
    live_server: str, browser_page: Page, theme: str, state: str
) -> None:
    page = browser_page
    navigate_and_wait(page, live_server, "/errors")
    page.evaluate(
        "theme => document.documentElement.setAttribute('data-theme', theme)", theme
    )
    page.evaluate(_SHOW_BADGE_AND_POPOVER, [state])
    page.add_script_tag(path=str(_AXE_JS))
    # Freeze the error pulse so the shadow can't affect sampling.
    page.add_style_tag(content=".test-badge { animation: none !important; }")

    result: dict[str, Any] = page.evaluate(
        """() => axe.run(document.querySelectorAll('.test-badge'), {
            runOnly: {type: 'rule', values: ['color-contrast']},
        })"""
    )
    failures = [
        f"{node['target']}: {node['any'][0]['message'] if node['any'] else ''}"
        for violation in result["violations"]
        for node in violation["nodes"]
    ]
    assert not failures, f"{theme}/{state}:\n" + "\n".join(failures)
    assert result["passes"], "axe checked nothing; the badge did not render"
