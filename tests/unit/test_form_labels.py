# pyright: reportMissingImports=false
"""
Tests that every form control on /playlist and /plugin/calendar
has an accessible label (JTN-315).

A control is considered labeled if any of the following is true:
  - It has an `id` that matches a `<label for="id">` in the same document
  - It is nested inside a `<label>` element (implicit label)
  - It carries an `aria-label` attribute
  - It carries an `aria-labelledby` attribute
"""

from __future__ import annotations

from html.parser import HTMLParser


class _FormLabelAuditor(HTMLParser):
    """Lightweight HTML parser that identifies form controls and their labels."""

    def __init__(self) -> None:
        super().__init__()
        self.controls: list[dict] = []
        self.label_for_ids: set[str] = set()
        self._label_depth: int = 0

    def handle_starttag(self, tag: str, attrs_list: list) -> None:
        attrs = dict(attrs_list)
        if tag == "label":
            self._label_depth += 1
            for_val = attrs.get("for")
            if for_val:
                self.label_for_ids.add(for_val)
        elif tag in ("input", "select", "textarea"):
            name = attrs.get("name", "")
            typ = attrs.get("type", "text")
            control_id = attrs.get("id", "")
            aria_label = attrs.get("aria-label", "")
            aria_labelledby = attrs.get("aria-labelledby", "")
            if name and typ != "hidden":
                self.controls.append(
                    {
                        "name": name,
                        "type": typ,
                        "id": control_id,
                        "aria_label": aria_label,
                        "aria_labelledby": aria_labelledby,
                        "inside_label": self._label_depth > 0,
                    }
                )

    def handle_endtag(self, tag: str) -> None:
        if tag == "label" and self._label_depth > 0:
            self._label_depth -= 1


def _find_unlabeled(html: str) -> list[dict]:
    """Return controls that have no accessible label."""
    auditor = _FormLabelAuditor()
    auditor.feed(html)
    unlabeled = []
    for ctrl in auditor.controls:
        has_label_for = bool(ctrl["id"]) and ctrl["id"] in auditor.label_for_ids
        has_implicit = ctrl["inside_label"]
        has_aria = bool(ctrl["aria_label"] or ctrl["aria_labelledby"])
        if not (has_label_for or has_implicit or has_aria):
            unlabeled.append(ctrl)
    return unlabeled


# ---------------------------------------------------------------------------
# /playlist
# ---------------------------------------------------------------------------


def test_playlist_page_all_controls_labeled(client):
    """/playlist — every named input/select/textarea must have an accessible label."""
    resp = client.get("/playlist")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    unlabeled = _find_unlabeled(html)
    assert (
        unlabeled == []
    ), f"/playlist has {len(unlabeled)} unlabeled form control(s): " + ", ".join(
        f"name={c['name']} id={c['id']!r}" for c in unlabeled
    )


# ---------------------------------------------------------------------------
# /plugin/calendar
# ---------------------------------------------------------------------------


def test_calendar_plugin_page_all_controls_labeled(client):
    """/plugin/calendar — every named input/select/textarea must have an accessible label."""
    resp = client.get("/plugin/calendar")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    unlabeled = _find_unlabeled(html)
    assert unlabeled == [], (
        f"/plugin/calendar has {len(unlabeled)} unlabeled form control(s): "
        + ", ".join(f"name={c['name']} id={c['id']!r}" for c in unlabeled)
    )
