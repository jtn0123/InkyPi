"""Media queries in the stylesheets use values browsers recognise.

A browser skips a whole ``@media`` block whose feature value it doesn't know,
with no warning. The high-contrast styles were written for
``prefers-contrast: high`` and so never applied anywhere.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

STYLES = Path(__file__).resolve().parents[2] / "src" / "static" / "styles"

# https://drafts.csswg.org/mediaqueries-5/
VALID = {
    "prefers-contrast": {"no-preference", "more", "less", "custom"},
    "prefers-reduced-motion": {"no-preference", "reduce"},
    "prefers-color-scheme": {"light", "dark"},
    "forced-colors": {"none", "active"},
}
FEATURE = re.compile(r"\(\s*(" + "|".join(VALID) + r")\s*:\s*([a-z-]+)\s*\)")


def _stylesheets() -> list[Path]:
    return sorted(STYLES.rglob("*.css"))


def test_stylesheets_found() -> None:
    assert any(p.name == "_a11y.css" for p in _stylesheets())


@pytest.mark.parametrize("path", _stylesheets(), ids=lambda p: p.name)
def test_media_feature_values_are_valid(path: Path) -> None:
    bad = [
        f"{feature}: {value}"
        for feature, value in FEATURE.findall(path.read_text(encoding="utf-8"))
        if value not in VALID[feature]
    ]
    assert not bad, f"{path.name} uses values browsers ignore: {bad}"
