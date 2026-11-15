#!/usr/bin/env python3
"""Report vendored front-end libraries that have a newer npm release.

Dependabot can't see these: they are downloaded by ``install/update_vendors.sh``
(Chart.js, FullCalendar), loaded from a CDN listed in
``src/static/cdn_manifest.json`` (Swagger UI), or committed under
``src/static/vendor/`` (htmx, Leaflet). This reads the pinned versions from
those places and asks the npm registry for each package's releases.

A newer release in the pinned major fails the check (exit 1), so the weekly
workflow goes red. A new major is listed but doesn't fail: adopting one is a
deliberate upgrade that may change how a page renders.

Exit codes: 0 current within each major, 1 something is behind, 2 a lookup
failed.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UPDATE_VENDORS = ROOT / "install" / "update_vendors.sh"
CDN_MANIFEST = ROOT / "src" / "static" / "cdn_manifest.json"
VENDOR_DIR = ROOT / "src" / "static" / "vendor"
# Libraries committed straight into src/static/vendor/: (npm package, file,
# pattern for the version inside the file). Reading the version from the file
# itself means replacing the file is the whole update, and nothing can drift.
COMMITTED_FILES = (
    ("htmx.org", VENDOR_DIR / "htmx.min.js", r'version:"(\d+\.\d+\.\d+)"'),
    ("leaflet", VENDOR_DIR / "leaflet" / "leaflet.js", r"Leaflet (\d+\.\d+\.\d+)"),
)
REGISTRY = "https://registry.npmjs.org"

# ``…/npm/<pkg>@<version>/…`` (jsDelivr) or ``unpkg.com/<pkg>@<version>/…``;
# <pkg> may be scoped (``@scope/name``).
_NPM_URL = re.compile(
    r"(?:cdn\.jsdelivr\.net/npm/|unpkg\.com/)"
    r"(?P<package>(?:@[\w.-]+/)?[\w.-]+)@(?P<version>\d[\w.+-]*)/"
)
_SHELL_VAR = re.compile(r"^([A-Z][A-Z0-9_]*)=\"([^\"]*)\"\s*$", re.MULTILINE)


@dataclass(frozen=True)
class Pin:
    package: str
    version: str
    source: str


def _pins_from_urls(urls: list[str], source: str) -> list[Pin]:
    pins = []
    for url in urls:
        match = _NPM_URL.search(url)
        if match is None:
            raise ValueError(f"{source}: not an npm CDN URL: {url}")
        pins.append(Pin(match["package"], match["version"], source))
    return pins


def pins_from_update_vendors(text: str) -> list[Pin]:
    """Return the npm pins in ``update_vendors.sh``, with its version variables expanded."""
    variables = dict(_SHELL_VAR.findall(text))

    def expand(url: str) -> str:
        return re.sub(r"\$\{(\w+)\}", lambda m: variables[m[1]], url)

    urls = [
        expand(line.split("|")[1])
        for line in re.findall(r'^\s*"([^"]*\|https://[^"]*)"\s*$', text, re.M)
    ]
    return _pins_from_urls(urls, "install/update_vendors.sh")


def pins_from_cdn_manifest(text: str) -> list[Pin]:
    """Return the npm pins in ``cdn_manifest.json``."""
    manifest = json.loads(text)
    urls = [str(entry["url"]) for entry in manifest.values()]
    return _pins_from_urls(urls, "src/static/cdn_manifest.json")


def pins_from_committed_files(
    files: tuple[tuple[str, Path, str], ...] = COMMITTED_FILES,
) -> list[Pin]:
    """Return the version of each library committed under ``src/static/vendor/``."""
    pins = []
    for package, path, pattern in files:
        source = path.relative_to(ROOT).as_posix()
        match = re.search(pattern, path.read_text(encoding="utf-8"))
        if match is None:
            raise ValueError(f"{source}: no {package} version found")
        pins.append(Pin(package, match[1], source))
    return pins


def all_pins() -> list[Pin]:
    pins = pins_from_update_vendors(UPDATE_VENDORS.read_text(encoding="utf-8"))
    pins += pins_from_cdn_manifest(CDN_MANIFEST.read_text(encoding="utf-8"))
    pins += pins_from_committed_files()
    unique: dict[tuple[str, str], Pin] = {}
    for pin in pins:
        unique.setdefault((pin.package, pin.version), pin)
    return list(unique.values())


def npm_releases(package: str) -> list[str]:
    """Return every published version of *package* from the npm registry."""
    url = f"{REGISTRY}/{urllib.parse.quote(package, safe='@')}"
    # The abbreviated document lists versions without each one's full metadata.
    request = urllib.request.Request(
        url, headers={"Accept": "application/vnd.npm.install-v1+json"}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return [str(version) for version in json.load(response)["versions"]]


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", version.split("+")[0]))


def _is_stable(version: str) -> bool:
    return re.fullmatch(r"\d+\.\d+\.\d+", version) is not None


def check(
    pins: list[Pin], releases: Callable[[str], list[str]]
) -> tuple[list[str], int]:
    """Return report lines and the exit code for *pins*.

    A newer release in the pinned major is routine upkeep, so it fails the
    check. A new major is a deliberate upgrade (it may change the API or how
    a page renders), so it is reported without failing.
    """
    lines = [
        "| Package | Pinned | Newest in major | New major | Where |",
        "|---|---|---|---|---|",
    ]
    code = 0
    for pin in pins:
        try:
            stable = [v for v in releases(pin.package) if _is_stable(v)]
        except Exception as exc:  # report every lookup failure, then carry on
            lines.append(
                f"| {pin.package} | {pin.version} | lookup failed: {exc} | | {pin.source} |"
            )
            code = max(code, 2)
            continue
        major = _version_key(pin.version)[0]
        same_major = [v for v in stable if _version_key(v)[0] == major]
        newest = max(same_major, key=_version_key, default=pin.version)
        latest = max(stable, key=_version_key, default=pin.version)
        behind = _version_key(newest) > _version_key(pin.version)
        new_major = latest if _version_key(latest)[0] > major else ""
        mark = f"**{newest}**" if behind else newest
        lines.append(
            f"| {pin.package} | {pin.version} | {mark} | {new_major} | {pin.source} |"
        )
        if behind:
            code = max(code, 1)
    return lines, code


def main() -> int:
    lines, code = check(all_pins(), npm_releases)
    report = "\n".join(lines)
    print(report)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write("## Vendored front-end libraries\n\n" + report + "\n")
    if code == 1:
        print(
            "\nA newer release exists in the pinned major. Bump the version and sha256 in "
            "install/update_vendors.sh, the URL and integrity in "
            "src/static/cdn_manifest.json (and src/blueprints/api_docs.py), or replace "
            "the file under src/static/vendor/ with the npm package's dist file.",
            file=sys.stderr,
        )
    return code


if __name__ == "__main__":
    sys.exit(main())
