#!/usr/bin/env python3
"""Bundle and optionally minify JS and CSS assets for production.

Usage:
    python scripts/build_assets.py              # bundle + minify JS and CSS
    python scripts/build_assets.py --no-minify  # concatenate only, no minification
    python scripts/build_assets.py --check      # dry-run: print stats, no write

Outputs:
    src/static/dist/common.bundle.<hash>.min.js   (or .js without --no-minify)
    src/static/dist/common.bundle.<hash>.min.css  (or .css without --no-minify)
    src/static/dist/manifest.json

The manifest maps logical names to versioned filenames:
    {
        "common.js":  "common.bundle.abc12345.min.js",
        "common.css": "common.bundle.abc12345.min.css"
    }

If rjsmin is installed it is used for JS minification; otherwise a simple
stdlib-based strip of // comments and blank lines is applied instead.
"""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "src" / "static" / "scripts"
STYLES_DIR = REPO_ROOT / "src" / "static" / "styles"
DIST_DIR = REPO_ROOT / "src" / "static" / "dist"

# ---------------------------------------------------------------------------
# JS bundle manifest — files loaded on EVERY page (base.html).
# Order matters: theme must bootstrap first (no-defer), then csrf, then the
# deferred utilities.  Page-specific scripts are intentionally excluded here;
# they stay as individual <script> tags until a follow-up ticket splits them.
# ---------------------------------------------------------------------------

JS_MANIFEST: list[str] = [
    "theme.js",
    "csrf.js",
    "client_errors.js",
    "form_validator.js",
    "response_modal.js",
    "dark_mode.js",
    "ui_helpers.js",
]

# ---------------------------------------------------------------------------
# CSS source — reuse the already-bundled main.css produced by build_css.py.
# We further minify it (or just copy) into the dist directory with a hash.
# ---------------------------------------------------------------------------

CSS_SOURCE = STYLES_DIR / "main.css"


# ---------------------------------------------------------------------------
# Simple JS minifier (no external deps)
# ---------------------------------------------------------------------------


def _minify_js_simple(js: str) -> str:
    """Best-effort pure-stdlib JS minification.

    Removes single-line comments (// ...) that appear on their own line,
    strips blank lines, and collapses leading whitespace.  Intentionally
    conservative to avoid breaking string literals that contain "//".
    """
    lines = js.splitlines()
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        # Drop lines that are *only* a // comment (safe heuristic)
        if stripped.startswith("//"):
            continue
        # Drop blank lines
        if not stripped:
            continue
        out.append(stripped)
    return "\n".join(out)


def _minify_js(js: str) -> str:
    """Minify JS using rjsmin if available, else fall back to simple strip."""
    try:
        import rjsmin  # type: ignore[import]

        return rjsmin.jsmin(js)
    except ImportError:
        return _minify_js_simple(js)


# ---------------------------------------------------------------------------
# Simple CSS minifier (same algorithm as build_css.py)
# ---------------------------------------------------------------------------


def _minify_css(css: str) -> str:
    """Lightweight minification: strip comments, collapse whitespace."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    css = re.sub(r"\s+", " ", css)
    css = re.sub(r"\s*([{}:;,>~+])\s*", r"\1", css)
    css = css.replace(";}", "}")
    return css.strip()


# ---------------------------------------------------------------------------
# Hash helper
# ---------------------------------------------------------------------------


def _content_hash(content: str, length: int = 8) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:length]


# ---------------------------------------------------------------------------
# Bundle builders
# ---------------------------------------------------------------------------


def build_js_bundle(minify: bool = True) -> tuple[str, list[str]]:
    """Concatenate JS files from JS_MANIFEST and optionally minify.

    Returns (bundled_content, list_of_included_filenames).
    """
    parts: list[str] = []
    included: list[str] = []

    for filename in JS_MANIFEST:
        path = SCRIPTS_DIR / filename
        if not path.is_file():
            print(f"WARNING: JS file not found, skipping: {path}", file=sys.stderr)
            continue
        source = path.read_text(encoding="utf-8")
        parts.append(f"// === {filename} ===\n{source}")
        included.append(filename)

    bundled = "\n\n".join(parts)
    if minify:
        bundled = _minify_js(bundled)
    return bundled, included


def build_css_bundle(minify: bool = True) -> str:
    """Read the pre-built main.css and optionally minify it."""
    if not CSS_SOURCE.is_file():
        sys.exit(
            f"ERROR: {CSS_SOURCE} not found. "
            "Run 'python scripts/build_css.py' first."
        )
    css = CSS_SOURCE.read_text(encoding="utf-8")
    if minify:
        css = _minify_css(css)
    return css


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Bundle JS/CSS assets for production.")
    parser.add_argument(
        "--no-minify",
        dest="minify",
        action="store_false",
        help="Concatenate only, skip minification",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Dry-run: print stats without writing files",
    )
    args = parser.parse_args(argv)

    # --- JS ---
    js_content, included_files = build_js_bundle(minify=args.minify)
    js_hash = _content_hash(js_content)
    suffix = "min.js" if args.minify else "js"
    js_filename = f"common.bundle.{js_hash}.{suffix}"

    # --- CSS ---
    css_content = build_css_bundle(minify=args.minify)
    css_hash = _content_hash(css_content)
    css_suffix = "min.css" if args.minify else "css"
    css_filename = f"common.bundle.{css_hash}.{css_suffix}"

    # --- Manifest ---
    manifest = {
        "common.js": js_filename,
        "common.css": css_filename,
    }

    if args.check:
        print(f"JS bundle:  {len(js_content):>9,} bytes  ->  {js_filename}")
        print(f"CSS bundle: {len(css_content):>9,} bytes  ->  {css_filename}")
        print(f"Files bundled ({len(included_files)}): {', '.join(included_files)}")
        print("manifest.json preview:")
        print(json.dumps(manifest, indent=2))
        return

    # --- Write ---
    DIST_DIR.mkdir(parents=True, exist_ok=True)

    # Clean up previous bundles (avoid stale hashed files accumulating)
    for old in DIST_DIR.glob("common.bundle.*.js"):
        old.unlink()
    for old in DIST_DIR.glob("common.bundle.*.min.js"):
        old.unlink()
    for old in DIST_DIR.glob("common.bundle.*.css"):
        old.unlink()
    for old in DIST_DIR.glob("common.bundle.*.min.css"):
        old.unlink()

    def _display_path(p: Path) -> str:
        try:
            return str(p.relative_to(REPO_ROOT))
        except ValueError:
            return str(p)

    js_out = DIST_DIR / js_filename
    js_out.write_text(js_content, encoding="utf-8")
    print(f"Wrote JS:  {len(js_content):,} bytes -> {_display_path(js_out)}")

    css_out = DIST_DIR / css_filename
    css_out.write_text(css_content, encoding="utf-8")
    print(f"Wrote CSS: {len(css_content):,} bytes -> {_display_path(css_out)}")

    manifest_out = DIST_DIR / "manifest.json"
    manifest_out.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote manifest -> {_display_path(manifest_out)}")
    print(f"Files bundled ({len(included_files)}): {', '.join(included_files)}")


if __name__ == "__main__":
    main()
