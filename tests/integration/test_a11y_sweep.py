# pyright: reportMissingImports=false
"""WCAG AA a11y sweep with axe-core (JTN-740).

Extends the axe-core wiring introduced by JTN-507 (see
``tests/integration/test_axe_a11y.py``) so that **every** page in the
``PAGES_TO_SWEEP`` constant used by the click-sweep *plus* every registered
plugin page is scanned, and the baseline is driven by a human-readable
``a11y_allowlist.yml`` file rather than an in-code dict.

Why split this from ``test_axe_a11y.py``:

* ``test_axe_a11y.py`` runs the **full** axe ruleset (including best-practice
  rules) and is tuned for the six main routes. It stays as-is so the
  earlier violation burndown (JTN-508/509/510/511) keeps tracking.
* This sweep runs **only** WCAG 2.0/2.1 A + AA tagged rules — the baseline
  the issue explicitly asks for. It is parametrised over
  :data:`PAGES_TO_SWEEP` (imported from :mod:`test_click_sweep`) *and*
  every plugin page, so plugin-template regressions show up in CI without
  a separate test file.

Gating
------
Same ``SKIP_A11Y`` / ``SKIP_BROWSER`` knobs as the other a11y tests — this
module is registered in ``tests/conftest.py::A11Y_BROWSER_TESTS`` so
collection is skipped when either env var is truthy, or when Playwright's
Chromium is unavailable.

To run locally::

    playwright install chromium
    SKIP_A11Y=0 PYTHONPATH=src pytest tests/integration/test_a11y_sweep.py -q

Acceptance flow (JTN-740)
-------------------------
Temporarily delete an ``aria-label`` from a real control (e.g. the
``#settingsForm`` save button on ``/plugin/clock``) and re-run the sweep —
it should fail with ``button-name`` (or similar). Reverting the change
returns the suite to green without touching the allowlist.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
import yaml
from tests.integration.test_click_sweep import (
    PAGES_TO_SWEEP,
    _discover_plugin_ids,
)

# ── Allowlist ───────────────────────────────────────────────────────────────
_ALLOWLIST_PATH = Path(__file__).parent / "a11y_allowlist.yml"
_AXE_JS_PATH = Path(__file__).resolve().parent.parent / "fixtures" / "axe.min.js"

# axe options restricting the run to WCAG AA (plus A). These are the tags
# the JTN-740 issue calls out ("WCAG AA baseline") — best-practice rules and
# WCAG AAA violations are out of scope here and are covered by
# ``test_axe_a11y.py`` where appropriate.
_AXE_TAGS: tuple[str, ...] = ("wcag2a", "wcag2aa", "wcag21a", "wcag21aa")

# Generous per-navigation timeout. Plugin pages render server-side but some
# pull remote settings (weather tiles, unsplash previews) on first paint; we
# only want the DOM to settle, so ``domcontentloaded`` is fine and the
# marker wait is optional.
_GOTO_TIMEOUT_MS = 30_000
_MARKER_TIMEOUT_MS = 8_000
_SETTLE_MS = 300


def _load_allowlist() -> dict[str, Any]:
    """Parse ``a11y_allowlist.yml`` into the runtime format.

    Returns a dict with keys:

    * ``"default"`` — ``set[str]`` of rule ids allowlisted on every main page.
    * ``"plugin_default"`` — ``set[str]`` of rule ids allowlisted on every
      ``/plugin/<id>`` page.
    * ``"pages"`` — ``dict[str, set[str]]`` of per-page extras.
    * ``"reasons"`` — ``dict[str, str]`` mapping ``"{scope}:{rule_id}"`` →
      justification text, used only in failure messages.
    """
    raw = yaml.safe_load(_ALLOWLIST_PATH.read_text(encoding="utf-8")) or {}

    def _extract(entries: Any, scope_key: str, reasons: dict[str, str]) -> set[str]:
        ids: set[str] = set()
        if not entries:
            return ids
        if not isinstance(entries, list):
            raise ValueError(
                f"a11y_allowlist.yml: '{scope_key}' must be a list of "
                f"{{id, reason}} entries, got {type(entries).__name__}."
            )
        for entry in entries:
            if not isinstance(entry, dict) or "id" not in entry:
                raise ValueError(
                    f"a11y_allowlist.yml: '{scope_key}' entries must be "
                    f"mappings with an 'id' field, got {entry!r}."
                )
            rule_id = str(entry["id"]).strip()
            reason = str(entry.get("reason", "")).strip()
            if not reason:
                raise ValueError(
                    f"a11y_allowlist.yml: '{scope_key}' entry "
                    f"'{rule_id}' is missing a 'reason' — every allowlist "
                    "entry must document why the violation is tolerated."
                )
            ids.add(rule_id)
            reasons[f"{scope_key}:{rule_id}"] = reason
        return ids

    reasons: dict[str, str] = {}
    default_ids = _extract(raw.get("default"), "default", reasons)
    plugin_default_ids = _extract(raw.get("plugin_default"), "plugin_default", reasons)

    pages: dict[str, set[str]] = {}
    for page_name, entries in (raw.get("pages") or {}).items():
        pages[page_name] = _extract(entries, f"pages.{page_name}", reasons)

    return {
        "default": default_ids,
        "plugin_default": plugin_default_ids,
        "pages": pages,
        "reasons": reasons,
    }


def _allowlist_for(
    page_label: str, is_plugin: bool, bundle: dict[str, Any]
) -> set[str]:
    base: set[str] = set(bundle["plugin_default"] if is_plugin else bundle["default"])
    base |= bundle["pages"].get(page_label, set())
    return base


def _run_axe_on_page(page, url: str, marker: str | None) -> dict[str, Any]:
    page.goto(url, wait_until="domcontentloaded", timeout=_GOTO_TIMEOUT_MS)
    if marker:
        try:
            page.wait_for_selector(marker, timeout=_MARKER_TIMEOUT_MS)
        except Exception:  # noqa: BLE001 — marker absence is not fatal
            pass
    page.wait_for_timeout(_SETTLE_MS)
    page.add_script_tag(content=_AXE_JS_PATH.read_text(encoding="utf-8"))
    options = {"runOnly": {"type": "tag", "values": list(_AXE_TAGS)}}
    return page.evaluate("(opts) => axe.run(document, opts)", options)


def _format_violations(violations: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for v in violations:
        impact = v.get("impact") or "n/a"
        description = v.get("description", "")
        # Surface the first offending node so the failure is actionable —
        # just the rule id isn't enough when the same rule fires on many
        # pages and you need to know which element tripped it.
        nodes = v.get("nodes") or []
        snippet = ""
        if nodes:
            target = nodes[0].get("target") or []
            html = (nodes[0].get("html") or "").strip().replace("\n", " ")
            if len(html) > 180:
                html = html[:177] + "…"
            snippet = f"\n      target={target} html={html!r}"
        lines.append(f"  - {v['id']} ({impact}): {description}{snippet}")
    return "\n".join(lines)


skip_env = pytest.mark.skipif(
    os.getenv("SKIP_A11Y", "").lower() in ("1", "true"),
    reason="A11y checks skipped by env",
)


# ── Core-page sweep ─────────────────────────────────────────────────────────

# We drop ``plugin_clock`` from the core-page list because it's covered by
# the plugin-page sweep below (which iterates over every plugin id). Keeping
# both would just double-run the same route.
_MAIN_PAGES = tuple(p for p in PAGES_TO_SWEEP if not p.path.startswith("/plugin/"))


@skip_env
@pytest.mark.parametrize("sweep", _MAIN_PAGES, ids=lambda s: s.label)
def test_a11y_sweep_main_pages(live_server, browser_page, sweep):
    """WCAG AA sweep over every main route in ``PAGES_TO_SWEEP``."""
    allowlist_bundle = _load_allowlist()
    allowed = _allowlist_for(sweep.label, is_plugin=False, bundle=allowlist_bundle)

    result = _run_axe_on_page(
        browser_page, f"{live_server}{sweep.path}", sweep.ready_marker
    )
    violations = [
        v for v in (result.get("violations") or []) if v.get("id") not in allowed
    ]

    if violations:
        pytest.fail(
            f"A11y sweep ({sweep.label} — {sweep.path}) found "
            f"{len(violations)} WCAG AA violation(s) not on the allowlist "
            f"(see tests/integration/a11y_allowlist.yml):\n"
            f"{_format_violations(violations)}"
        )


# ── Plugin-page sweep ───────────────────────────────────────────────────────

_PLUGIN_IDS: tuple[str, ...] = _discover_plugin_ids()


@skip_env
@pytest.mark.plugin_sweep
@pytest.mark.parametrize("plugin_id", _PLUGIN_IDS, ids=list(_PLUGIN_IDS))
def test_a11y_sweep_plugin_pages(live_server, browser_page, plugin_id: str):
    """WCAG AA sweep over every ``/plugin/<id>`` page.

    Parametrised the same way as
    :func:`tests.integration.test_click_sweep.test_click_sweep_plugin_pages`
    so a template regression in weather/todo/comic/etc. fails CI here too.
    """
    allowlist_bundle = _load_allowlist()
    label = f"plugin_{plugin_id}"
    allowed = _allowlist_for(label, is_plugin=True, bundle=allowlist_bundle)

    result = _run_axe_on_page(
        browser_page, f"{live_server}/plugin/{plugin_id}", "#settingsForm"
    )
    violations = [
        v for v in (result.get("violations") or []) if v.get("id") not in allowed
    ]

    if violations:
        pytest.fail(
            f"A11y sweep ({label} — /plugin/{plugin_id}) found "
            f"{len(violations)} WCAG AA violation(s) not on the allowlist "
            f"(see tests/integration/a11y_allowlist.yml):\n"
            f"{_format_violations(violations)}"
        )


# ── Allowlist self-tests ────────────────────────────────────────────────────
#
# These run even when ``SKIP_A11Y=1`` (no ``@skip_env``) because parsing the
# YAML and catching a stale page key doesn't need a browser. They're the
# lightest line of defence against an allowlist that silently drifts out of
# sync with the pages being swept.


def test_a11y_allowlist_is_well_formed():
    """The YAML parses and every entry carries a non-empty ``reason``."""
    bundle = _load_allowlist()
    # ``_load_allowlist`` already raises on malformed entries; the assertions
    # below just document the expected shape.
    assert isinstance(bundle["default"], set)
    assert isinstance(bundle["plugin_default"], set)
    assert isinstance(bundle["pages"], dict)
    for reason in bundle["reasons"].values():
        assert reason, "Every allowlist entry requires a non-empty reason."


def test_a11y_allowlist_pages_exist():
    """Every ``pages:`` override maps to a real page the sweep will visit.

    Stops the allowlist rotting once a page is renamed or removed — a
    page-specific override referencing a page that no longer exists is
    almost always a sign the violation was fixed and the entry forgotten.
    """
    bundle = _load_allowlist()
    if not bundle["pages"]:
        return
    known = {p.label for p in _MAIN_PAGES}
    known |= {f"plugin_{pid}" for pid in _PLUGIN_IDS}
    unknown = sorted(set(bundle["pages"]) - known)
    assert not unknown, (
        f"a11y_allowlist.yml references unknown pages: {unknown}. "
        "Remove the overrides or update the page label to match."
    )
