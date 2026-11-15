"""The committed main.css must match what scripts/build_css.py builds.

main.css is tracked so a fresh clone (and every test and browser run) uses it
as-is. CI used to rebuild it before testing, which hid a partial edit whose
rebuilt main.css was never committed.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[2]


def _build_css() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "build_css", REPO_ROOT / "scripts" / "build_css.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_committed_main_css_matches_the_partials() -> None:
    build_css = _build_css()
    expected = build_css.resolve_imports(build_css.IMPORTS_CSS)
    committed = build_css.MAIN_CSS.read_text(encoding="utf-8")
    assert committed == expected, (
        "src/static/styles/main.css is out of date with its partials: run "
        "`python scripts/build_css.py` and commit main.css"
    )
