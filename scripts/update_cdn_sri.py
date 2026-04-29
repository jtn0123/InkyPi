#!/usr/bin/env python3
"""Update SRI hashes in cdn_manifest.json (JTN-478).

Downloads each CDN asset listed in ``src/static/cdn_manifest.json``,
computes its SHA-384 hash, and writes the updated hash back.

Run this script manually whenever a CDN version is bumped:

    python3 scripts/update_cdn_sri.py

Optionally pass --dry-run to print the computed hashes without writing.

Exit codes:
  0  all hashes computed (and written if not dry-run)
  1  one or more URLs failed to download
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPO_ROOT / "src" / "static" / "cdn_manifest.json"


def _validate_cdn_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("CDN asset URLs must be absolute HTTPS URLs")
    return url


def compute_sri_from_url(url: str) -> str:
    """Download *url* and return its ``sha384-<base64>`` SRI hash."""
    safe_url = _validate_cdn_url(url)
    with urllib.request.urlopen(safe_url, timeout=30) as resp:  # noqa: S310
        data = resp.read()
    digest = hashlib.sha384(data).digest()
    return "sha384-" + base64.b64encode(digest).decode("ascii")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print computed hashes without writing the manifest",
    )
    parser.add_argument(
        "--manifest",
        default=str(MANIFEST_PATH),
        help="Path to cdn_manifest.json (default: %(default)s)",
    )
    args = parser.parse_args(argv)

    manifest_path = Path(args.manifest)
    if not manifest_path.is_file():
        print(f"ERROR: manifest not found: {manifest_path}", file=sys.stderr)
        return 1

    manifest: dict[str, dict] = json.loads(manifest_path.read_text(encoding="utf-8"))
    errors: list[str] = []

    for key, entry in manifest.items():
        url = entry.get("url", "")
        if not url:
            print(f"  [{key}] SKIP — no url field")
            continue
        print(f"  [{key}] downloading {url} …", end=" ", flush=True)
        try:
            sri = compute_sri_from_url(url)
            old = entry.get("integrity", "")
            changed = sri != old
            print(sri, "(changed)" if changed else "(unchanged)")
            entry["integrity"] = sri
        except Exception as exc:
            print(f"ERROR: {exc}")
            errors.append(key)

    if errors:
        print(f"\nFailed to update: {errors}", file=sys.stderr)

    if not args.dry_run and not errors:
        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"\nWritten to {manifest_path}")
    elif args.dry_run:
        print("\n[dry-run] manifest not written")

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
