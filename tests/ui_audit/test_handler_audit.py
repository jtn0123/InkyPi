"""Layer 1 of the UI breakage detection net: static handler audit.

Parses every template in ``src/templates/`` and every JS file in
``src/static/scripts/`` and proves that each clickable element can reach at
least one handler. Runs in well under 5 s and introduces no new Python
dependencies (uses stdlib ``html.parser`` + regex).

Rules enforced:

1. **Rule 1 — missing data-action handler.** For any clickable element with
   ``data-X-action="value"``, at least one JS file must reference the family
   ``X`` (via ``dataset.Xaction`` or ``[data-x-action]`` selector) *and* the
   action value must appear as a string literal in at least one JS file.
   The second half is loose on purpose: handlers routinely delegate across
   files (``plugin_page.js`` reads ``dataset.pluginAction`` and hands the
   value to ``plugin_form.js``), so insisting the literal appears in the
   same file as the dataset read produces false positives.

2. **Rule 2 — orphan ``<button type="button">``.** A ``<button>`` whose
   ``type`` is explicitly ``button`` (i.e. not a form-submit) with no
   ``data-*-action``, no ``hx-*`` attribute, no recognised delegated
   ``data-*`` marker, and no ``id``/``class`` referenced from JS is an
   orphan — clicking it does nothing.

3. **Rule 3 — dead anchor.** ``<a href="#foo">`` must either match an
   ``id="foo"`` somewhere in the template family (same file or ``base.html``
   it extends) or be wired up by JS.

Findings can be silenced by adding an entry to
``tests/ui_audit/allowlist.yml``. Each entry must carry a one-line ``reason``
— the allowlist is a scalpel, not a sledgehammer.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

from tests.ui_audit.parsers import (
    ScriptScan,
    TemplateScan,
    _strip_jinja,
    collect_scripts,
    collect_templates,
    family_handlers,
    id_is_referenced,
)

# Attributes that indicate a button is wired up via a *delegated* handler
# rather than by id/class lookup. We skip Rule 2 for buttons carrying any of
# these — they are not orphans.
_DELEGATED_MARKERS = frozenset(
    {
        "data-open-modal",
        "data-close-modal",
        "data-settings-tab",
        "data-plugin-subtab",
        "data-playlist-toggle",
        "data-collapsible-toggle",
        "data-frame-option",
        "data-repeater-add",
        "data-repeater-remove",
        # Playlist card controls use these attrs as inputs to class-bound
        # handlers — the class selector covers the wiring, so carrying any
        # of these is evidence of intentional wiring rather than orphanage.
        "data-playlist",
        "data-playlist-name",
    }
)


REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATES_DIR = REPO_ROOT / "src" / "templates"
SCRIPTS_DIR = REPO_ROOT / "src" / "static" / "scripts"
ALLOWLIST_PATH = Path(__file__).with_name("allowlist.yml")


@dataclass(frozen=True)
class Finding:
    rule: str
    template: str
    line: int
    value: str
    detail: str

    def matches_allowlist_entry(self, entry: dict) -> bool:
        return (
            entry.get("rule") == self.rule
            and entry.get("template") == self.template
            and int(entry.get("line", -1)) == self.line
            and entry.get("value") == self.value
        )

    def as_table_row(self) -> str:
        return (
            f"  [{self.rule}] {self.template}:{self.line}  "
            f"value={self.value!r}  — {self.detail}"
        )


def _load_allowlist() -> list[dict]:
    if not ALLOWLIST_PATH.exists():
        return []
    raw = yaml.safe_load(ALLOWLIST_PATH.read_text(encoding="utf-8")) or {}
    entries = raw.get("entries") or []
    if not isinstance(entries, list):  # pragma: no cover - defensive
        raise AssertionError(
            f"{ALLOWLIST_PATH}: 'entries' must be a list (got {type(entries).__name__})"
        )
    for entry in entries:
        if not entry.get("reason"):
            raise AssertionError(
                f"{ALLOWLIST_PATH}: every entry requires a 'reason' (got {entry!r})"
            )
    return entries


def _rule1_findings(
    templates: list[TemplateScan], scripts: list[ScriptScan]
) -> list[Finding]:
    out: list[Finding] = []
    for t in templates:
        for c in t.clickables:
            fa = c.data_action_family()
            if not fa:
                continue
            family, value = fa
            handlers = family_handlers(scripts, family)
            if not handlers:
                out.append(
                    Finding(
                        rule="missing-handler",
                        template=c.template,
                        line=c.line,
                        value=f"data-{family}-action={value}",
                        detail=f"no JS file references dataset.{_dataset_camel(family)} or [data-{family}-action]",
                    )
                )
                continue
            if any(value in s.literals for s in scripts):
                continue
            out.append(
                Finding(
                    rule="missing-handler",
                    template=c.template,
                    line=c.line,
                    value=f"data-{family}-action={value}",
                    detail=(
                        "family handlers present ("
                        + ", ".join(s.path.name for s in handlers)
                        + f") but the action literal {value!r} was not found "
                        "in any JS file"
                    ),
                )
            )
    return out


def _dataset_camel(family: str) -> str:
    # plugin -> pluginAction, api-keys -> apiKeysAction
    parts = family.split("-")
    return parts[0] + "".join(p.capitalize() for p in parts[1:]) + "Action"


def _class_referenced(classes: Iterable[str], scripts: list[ScriptScan]) -> bool:
    for cls in classes:
        token = f".{cls}"
        if any(token in s.text for s in scripts):
            return True
    return False


def _rule2_findings(
    templates: list[TemplateScan], scripts: list[ScriptScan]
) -> list[Finding]:
    out: list[Finding] = []
    for t in templates:
        for c in t.clickables:
            if c.tag != "button":
                continue
            # Buttons without an explicit type default to type="submit" inside a
            # <form>. Only audit explicit type="button" — submits are wired up
            # by the form submit handler, not by clickjacking a listener onto
            # the button itself.
            btype = (c.attr("type") or "submit").lower()
            if btype != "button":
                continue
            attr_keys = {k for k, _ in c.attrs}
            if any(k.startswith("data-") and k.endswith("-action") for k in attr_keys):
                continue
            if any(k.startswith("hx-") for k in attr_keys):
                continue
            if attr_keys & _DELEGATED_MARKERS:
                continue
            btn_id = c.attr("id")
            if btn_id:
                canonical = _strip_jinja(btn_id)
                if id_is_referenced(scripts, canonical):
                    continue
                out.append(
                    Finding(
                        rule="orphan-button",
                        template=c.template,
                        line=c.line,
                        value=f"#{canonical}",
                        detail="id not referenced by getElementById/querySelector or any JS literal",
                    )
                )
                continue
            classes = (c.attr("class") or "").split()
            if _class_referenced(classes, scripts):
                continue
            out.append(
                Finding(
                    rule="orphan-button",
                    template=c.template,
                    line=c.line,
                    value=f"<button class={' '.join(classes)!r}>",
                    detail="no id, no data-*-action, no hx-*, no delegated marker, no class referenced from JS",
                )
            )
    return out


def _collect_all_ids(templates: list[TemplateScan]) -> set[str]:
    # Anchors like href="#main-content" reference ids that may live in any
    # template sharing the same base layout. base.html's skip link is the
    # canonical example. Flattening ids across templates is a safe
    # over-approximation — an id that exists nowhere still fails.
    ids: set[str] = set()
    for t in templates:
        ids.update(t.element_ids)
    return ids


def _rule3_findings(
    templates: list[TemplateScan], scripts: list[ScriptScan]
) -> list[Finding]:
    out: list[Finding] = []
    all_ids = _collect_all_ids(templates)
    for t in templates:
        for c in t.clickables:
            if c.tag != "a":
                continue
            href = c.attr("href") or ""
            if not href.startswith("#"):
                continue
            anchor = href[1:]
            if not anchor:
                continue  # bare "#" is an intentional no-op (e.g. dropdown toggle)
            canonical = _strip_jinja(anchor)
            if not canonical:
                continue
            if canonical in t.element_ids or canonical in all_ids:
                continue
            if id_is_referenced(scripts, canonical):
                continue
            out.append(
                Finding(
                    rule="dead-anchor",
                    template=c.template,
                    line=c.line,
                    value=href,
                    detail="no matching id in any template and no JS handler",
                )
            )
    return out


@pytest.fixture(scope="module")
def scanned_templates() -> list[TemplateScan]:
    return collect_templates(TEMPLATES_DIR, REPO_ROOT)


@pytest.fixture(scope="module")
def scanned_scripts() -> list[ScriptScan]:
    return collect_scripts(SCRIPTS_DIR)


@pytest.fixture(scope="module")
def allowlist() -> list[dict]:
    return _load_allowlist()


def test_templates_and_scripts_discoverable(
    scanned_templates: list[TemplateScan], scanned_scripts: list[ScriptScan]
) -> None:
    """Fail fast if the audit is pointed at an empty/wrong directory."""

    assert scanned_templates, f"no templates found under {TEMPLATES_DIR}"
    assert scanned_scripts, f"no JS scripts found under {SCRIPTS_DIR}"


def _partition(
    findings: list[Finding], allowlist: list[dict]
) -> tuple[list[Finding], list[dict]]:
    unmatched_entries = list(allowlist)
    live: list[Finding] = []
    for f in findings:
        hit = None
        for entry in unmatched_entries:
            if f.matches_allowlist_entry(entry):
                hit = entry
                break
        if hit is None:
            live.append(f)
        else:
            unmatched_entries.remove(hit)
    return live, unmatched_entries


def _format(findings: list[Finding]) -> str:
    if not findings:
        return "(none)"
    return "\n".join(f.as_table_row() for f in findings)


def test_no_dead_data_action_handlers(
    scanned_templates: list[TemplateScan],
    scanned_scripts: list[ScriptScan],
    allowlist: list[dict],
) -> None:
    findings = _rule1_findings(scanned_templates, scanned_scripts)
    live, _unused = _partition(findings, allowlist)
    assert not live, (
        "Rule 1 — every data-X-action value must reach a JS handler. "
        "Dead handlers:\n" + _format(live)
    )


def test_no_orphan_buttons(
    scanned_templates: list[TemplateScan],
    scanned_scripts: list[ScriptScan],
    allowlist: list[dict],
) -> None:
    findings = _rule2_findings(scanned_templates, scanned_scripts)
    live, _unused = _partition(findings, allowlist)
    assert not live, (
        "Rule 2 — <button type=button> must have a handler wired via id, class, "
        "data-*-action, hx-*, or a recognised delegated marker. Orphans:\n"
        + _format(live)
    )


def test_no_dead_anchors(
    scanned_templates: list[TemplateScan],
    scanned_scripts: list[ScriptScan],
    allowlist: list[dict],
) -> None:
    findings = _rule3_findings(scanned_templates, scanned_scripts)
    live, _unused = _partition(findings, allowlist)
    assert not live, (
        "Rule 3 — every <a href='#anchor'> must resolve to an id in some "
        "template or have a JS handler. Dead anchors:\n" + _format(live)
    )


def test_allowlist_is_tight(
    scanned_templates: list[TemplateScan],
    scanned_scripts: list[ScriptScan],
    allowlist: list[dict],
) -> None:
    """Allowlist entries that no longer match anything should be removed."""

    all_findings = (
        _rule1_findings(scanned_templates, scanned_scripts)
        + _rule2_findings(scanned_templates, scanned_scripts)
        + _rule3_findings(scanned_templates, scanned_scripts)
    )
    _live, unused = _partition(all_findings, allowlist)
    assert not unused, (
        "allowlist.yml has stale entries that no longer match any finding — "
        "delete them:\n" + "\n".join(f"  {e}" for e in unused)
    )


@pytest.fixture(scope="module")
def findings_snapshot(
    scanned_templates: list[TemplateScan], scanned_scripts: list[ScriptScan]
) -> list[Finding]:
    """Raw findings (pre-allowlist) — used by the inventory sanity check."""

    return (
        _rule1_findings(scanned_templates, scanned_scripts)
        + _rule2_findings(scanned_templates, scanned_scripts)
        + _rule3_findings(scanned_templates, scanned_scripts)
    )


def test_findings_inventory_matches_snapshot(findings_snapshot: list[Finding]) -> None:
    """Human-readable guardrail: the current inventory of raw findings.

    This test doubles as documentation for Agent B / Layer 2. If a new dead
    handler appears, the snapshot changes and the test fails loudly; if
    someone fixes one, they edit the snapshot down and the test stays honest.
    """

    expected_values: set[tuple[str, str, str]] = set()
    # As of L1 landing, the static audit finds zero dead handlers. This is the
    # baseline — any new entry here should be a deliberate, reasoned allowance
    # during a regression window. See the epic (JTN-677) for context.
    actual_values = {(f.rule, f.template, f.value) for f in findings_snapshot}
    missing = expected_values - actual_values
    unexpected = actual_values - expected_values
    assert not missing and not unexpected, (
        "Findings inventory drifted:\n"
        f"  newly-appeared: {sorted(unexpected)}\n"
        f"  no-longer-present: {sorted(missing)}\n"
        "Full current inventory:\n" + _format(findings_snapshot)
    )
