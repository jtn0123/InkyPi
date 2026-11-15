"""Scrolls the app starts itself follow the "reduce motion" setting.

The stylesheet's ``prefers-reduced-motion`` rule only shortens CSS
animations and transitions. ``scrollIntoView({behavior: "smooth"})`` ignores
it, so every scripted scroll asks ``InkyPiTheme.scrollBehavior()`` instead,
which answers "auto" (instant) when the user has asked for less motion.
"""

from __future__ import annotations

import re
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "src" / "static" / "scripts"
_HARDCODED_SMOOTH = re.compile(r"""behavior:\s*["']smooth["']""")


def _app_scripts() -> list[Path]:
    return [
        path
        for path in sorted(SCRIPTS.rglob("*.js"))
        if "vendor" not in path.parts
        and "dist" not in path.parts
        and not path.name.endswith(".min.js")
    ]


def test_no_script_hardcodes_smooth_scrolling() -> None:
    offenders = [
        f"{path.relative_to(SCRIPTS)}:{number}"
        for path in _app_scripts()
        for number, line in enumerate(path.read_text().splitlines(), start=1)
        if _HARDCODED_SMOOTH.search(line) and not line.lstrip().startswith("//")
    ]
    assert not offenders, (
        "Use globalThis.InkyPiTheme?.scrollBehavior() for scripted scrolls: "
        f"{offenders}"
    )


def test_theme_exposes_the_reduced_motion_check() -> None:
    theme = (SCRIPTS / "theme.js").read_text()
    assert "(prefers-reduced-motion: reduce)" in theme
    assert re.search(r"window\.InkyPiTheme = \{[^}]*\bscrollBehavior,", theme)
