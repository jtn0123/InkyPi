"""Every @media width query uses one of the named breakpoint tokens.

The tokens are the ``--bp-<name>: <N>px`` lines in partials/_tokens.css.
CSS custom properties cannot be used inside @media, so scripts/build_css.py
reads that list and checks the partials against it (grade item C12).
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


def test_three_or_four_named_breakpoints_in_ascending_order() -> None:
    widths = list(_build_css().breakpoint_tokens().values())
    assert 3 <= len(widths) <= 4, widths
    assert widths == sorted(set(widths)), widths


def test_every_width_query_in_the_partials_uses_a_token() -> None:
    violations = _build_css().breakpoint_violations()
    assert violations == [], (
        "Use a --bp-* token from partials/_tokens.css: (max-width: N) for "
        "N and narrower, (min-width: N+1) for wider than N. Found: "
        + ", ".join(violations)
    )


def test_checker_accepts_tokens_and_reports_one_offs() -> None:
    css = """
/* A comment that mentions @media (max-width: 123px) { is ignored */
@media (max-width: 640px) { a { color: red; } }
@media (min-width: 641px) { a { color: red; } }
@media (max-height: 860px) and (min-width: 769px) { a { color: red; } }
@media (max-aspect-ratio: 3/4) { a { color: red; } }
@media (hover: none) and (pointer: coarse) { a { color: red; } }
@media (max-width: 960px) { a { color: red; } }
@media (min-width: 1024px) { a { color: red; } }
@media (width <= 640px) { a { color: red; } }
@media (max-width: 40em) { a { color: red; } }
"""
    found = _build_css().breakpoint_violations_in(css, [640, 768])
    assert found == [
        (8, "(max-width: 960px)"),
        (9, "(min-width: 1024px)"),
        (10, "(width <= 640px)"),
        (11, "(max-width: 40em)"),
    ]


def test_no_token_list_means_nothing_to_check(tmp_path: Path) -> None:
    # The install build bundles CSS with this script; a tree without
    # _tokens.css must still build (tests/unit/test_install_asset_build.py).
    imports = tmp_path / "_imports.css"
    partial = tmp_path / "partials" / "_a.css"
    partial.parent.mkdir()
    partial.write_text("@media (max-width: 123px) { a { color: red; } }")
    imports.write_text('@import "partials/_a.css";')

    found = _build_css().breakpoint_violations(imports, tmp_path / "_tokens.css")

    assert found == []
