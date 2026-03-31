#!/usr/bin/env python3
"""Concatenate CSS @import partials into a single file for production.

Usage:
    python scripts/build_css.py                 # concatenate only
    python scripts/build_css.py --minify        # concatenate + minify
    python scripts/build_css.py --check         # verify round-trip (no write)

The script reads src/static/styles/_imports.css (the tracked manifest of @import
directives), resolves every partial in order, and writes the bundled output to
main.css (or to --output if given).
"""

import argparse
import re
import sys
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
