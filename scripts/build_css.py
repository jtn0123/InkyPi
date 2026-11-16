#!/usr/bin/env python3
"""Concatenate CSS @import partials into a single file for production.

Usage:
    python scripts/build_css.py                 # concatenate only
    python scripts/build_css.py --minify        # concatenate + minify
    python scripts/build_css.py --check         # verify round-trip (no write)

The script reads src/static/styles/_imports.css (the tracked manifest of @import
directives), resolves every partial in order, and writes the bundled output to
main.css (or to --output if given). It warns about any @media width query
that does not use one of the breakpoint tokens listed in partials/_tokens.css.
"""

import argparse
import re
import sys
from collections.abc import Iterable
from pathlib import Path

STYLES_DIR = Path(__file__).resolve().parent.parent / "src" / "static" / "styles"
IMPORTS_CSS = STYLES_DIR / "_imports.css"
MAIN_CSS = STYLES_DIR / "main.css"

IMPORT_RE = re.compile(r'^@import\s+["\'](.+?)["\'];', re.MULTILINE)


def resolve_imports(entry: Path) -> str:
    """Read *entry* and inline every @import it references (one level)."""
    text = entry.read_text(encoding="utf-8")
    parts: list[str] = []
    last_end = 0

    for m in IMPORT_RE.finditer(text):
        parts.append(text[last_end : m.start()])
        rel = m.group(1)
        partial = (entry.parent / rel).resolve()
        if not partial.is_file():
            print(f"WARNING: {rel} not found ({partial})", file=sys.stderr)
            parts.append(m.group(0))  # keep original line
        else:
            parts.append(partial.read_text(encoding="utf-8"))
        last_end = m.end()

    parts.append(text[last_end:])
    return "".join(parts)


def minify_css(css: str) -> str:
    """Lightweight minification: strip comments, collapse whitespace."""
    # Remove block comments
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    # Collapse runs of whitespace (but keep single spaces for selectors)
    css = re.sub(r"\s+", " ", css)
    # Remove spaces around structural chars
    css = re.sub(r"\s*([{}:;,>~+])\s*", r"\1", css)
    # Remove trailing semicolons before closing braces
    css = css.replace(";}", "}")
    return css.strip()


# ---------------------------------------------------------------------------
# Breakpoint tokens
# ---------------------------------------------------------------------------
# CSS custom properties cannot be used inside @media, so the named
# breakpoints are listed as "--bp-<name>: <N>px" lines in _tokens.css and
# every width query in the partials must use one of them.

TOKENS_CSS = STYLES_DIR / "partials" / "_tokens.css"
BREAKPOINT_TOKEN_RE = re.compile(r"^\s*--bp-([a-z]+):\s*(\d+)px\b", re.MULTILINE)
MEDIA_PRELUDE_RE = re.compile(r"@media\b([^{;]*)\{")
MEDIA_FEATURE_RE = re.compile(r"\(([^()]*)\)")
WIDTH_FEATURE_RE = re.compile(r"^\s*(max|min)-width\s*:\s*(\d+)px\s*$")
COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)


def breakpoint_tokens(tokens_css: Path = TOKENS_CSS) -> dict[str, int]:
    """The named breakpoints in *tokens_css*, as ``{name: width_px}``."""
    text = tokens_css.read_text(encoding="utf-8")
    return {m.group(1): int(m.group(2)) for m in BREAKPOINT_TOKEN_RE.finditer(text)}


def breakpoint_violations_in(css: str, tokens: Iterable[int]) -> list[tuple[int, str]]:
    """``(line, feature)`` for each @media width feature that is not a token.

    ``(max-width: N)`` must use a token ``N``, and ``(min-width: N)`` must be
    one more than a token, so the two sides of a breakpoint never overlap.
    Height and aspect-ratio features are not checked. Any other width feature
    (range syntax, em units, device-width) is reported.
    """
    widths = set(tokens)
    # Blank comments but keep their newlines, so line numbers still match.
    css = COMMENT_RE.sub(lambda m: "\n" * m.group(0).count("\n"), css)
    found: list[tuple[int, str]] = []
    for prelude in MEDIA_PRELUDE_RE.finditer(css):
        line = css.count("\n", 0, prelude.start()) + 1
        for feature in MEDIA_FEATURE_RE.findall(prelude.group(1)):
            if "width" not in feature:
                continue
            m = WIDTH_FEATURE_RE.match(feature)
            if m:
                edge = int(m.group(2)) - (1 if m.group(1) == "min" else 0)
                if edge in widths:
                    continue
            found.append((line, f"({feature.strip()})"))
    return found


def breakpoint_violations(
    imports_css: Path = IMPORTS_CSS, tokens_css: Path = TOKENS_CSS
) -> list[str]:
    """``partial:line (feature)`` for each width query that is not a token.

    Empty when there is no token list to check against, as in a stripped-down
    tree: the install build runs this script and must not fail on a check.
    """
    if not tokens_css.is_file():
        return []
    tokens = breakpoint_tokens(tokens_css).values()
    violations: list[str] = []
    for rel in IMPORT_RE.findall(imports_css.read_text(encoding="utf-8")):
        partial = (imports_css.parent / rel).resolve()
        if not partial.is_file():
            continue
        css = partial.read_text(encoding="utf-8")
        for line, feature in breakpoint_violations_in(css, tokens):
            violations.append(f"{rel}:{line} {feature}")
    return violations


def main() -> None:
    parser = argparse.ArgumentParser(description="Bundle CSS partials for production.")
    parser.add_argument(
        "--minify", action="store_true", help="Strip comments and whitespace"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output file (default: overwrite main.css)",
    )
    parser.add_argument(
        "--check", action="store_true", help="Dry-run: print stats without writing"
    )
    args = parser.parse_args()

    if not IMPORTS_CSS.is_file():
        sys.exit(f"ERROR: {IMPORTS_CSS} not found")

    bundled = resolve_imports(IMPORTS_CSS)

    # Warn, don't fail: the dev watcher rebuilds on every save, the install
    # and update builds run this too, and tests/unit/test_css_breakpoints.py
    # is the gate.
    try:
        violations = breakpoint_violations()
    except (OSError, UnicodeDecodeError) as exc:
        print(f"WARNING: breakpoint check skipped: {exc}", file=sys.stderr)
        violations = []
    for violation in violations:
        print(
            f"WARNING: {violation} is not a breakpoint token "
            f"(see the --bp-* list in {TOKENS_CSS.name})",
            file=sys.stderr,
        )

    if args.minify:
        bundled = minify_css(bundled)

    if args.check:
        print(f"Bundled size: {len(bundled):,} bytes")
        if args.minify:
            raw = resolve_imports(IMPORTS_CSS)
            saved = len(raw) - len(bundled)
            print(f"Minified saving: {saved:,} bytes ({saved * 100 // len(raw)}%)")
        return

    out = args.output or MAIN_CSS
    out.write_text(bundled, encoding="utf-8")
    print(f"Wrote {len(bundled):,} bytes to {out}")


if __name__ == "__main__":
    main()
