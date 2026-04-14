# pyright: reportMissingImports=false
"""Backend route smoke test (Layer 3, Part A).

Walks every ``GET`` route registered on the Flask app that takes **no
required path parameters** and requests it via the shared ``client`` fixture.

Intent: catch routes that 500 on a fresh install / empty-state device config.
This complements the static UI handler audit (Layer 1) and the runtime click
sweep (Layer 3, Part B) — neither of those would notice, e.g., a KeyError in
a template shared across pages.

Assertions per response:

* Response is **not 5xx** — the primary deliverable of this smoke.
* Status is in ``{200, 302, 400, 401, 403, 404, 405, 422}``: auth redirects
  (302/401/403), missing-but-controlled resources (404), method-not-allowed
  on endpoints that only accept POST (405), and explicit validation errors
  on API endpoints that require query params (400/422) are all fine.
* For HTML responses, the body contains a ``<title>`` element and does not
  contain tell-tale error strings (``Internal Server Error`` / ``Traceback``).

Routes that need parameters are skipped automatically (``rule.arguments`` is
non-empty). A YAML allowlist at ``tests/smoke/route_allowlist.yml`` lets us
opt individual parameter-free paths out with a one-line reason (e.g. SSE
streams that block).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

_ALLOWLIST_PATH = Path(__file__).with_name("route_allowlist.yml")
_OK_STATUSES = {200, 302, 400, 401, 403, 404, 405, 422}
_ERROR_MARKERS = ("Internal Server Error", "Traceback (most recent call last)")


def _load_allowlist() -> dict[str, str]:
    """Return {path: reason} pairs to skip during the GET sweep."""
    if not _ALLOWLIST_PATH.exists():
        return {}
    data: Any = yaml.safe_load(_ALLOWLIST_PATH.read_text()) or {}
    entries = data.get("skip_paths", []) if isinstance(data, dict) else []
    out: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        path = entry.get("path")
        reason = entry.get("reason", "(no reason given)")
        if isinstance(path, str):
            out[path] = str(reason)
    return out


def _iter_smoke_targets(flask_app) -> list[tuple[str, str]]:
    """Yield (path, endpoint) pairs for unparameterized GET routes."""
    allow = _load_allowlist()
    targets: list[tuple[str, str]] = []
    seen: set[str] = set()
    for rule in flask_app.url_map.iter_rules():
        methods = rule.methods or set()
        if "GET" not in methods:
            continue
        if rule.arguments:  # requires path params — skip
            continue
        path = str(rule.rule)
        if path in allow:
            continue
        if path in seen:
            continue
        # Defensive: ignore duplicate registrations of the same path.
        seen.add(path)
        targets.append((path, rule.endpoint))
    targets.sort()
    return targets


def _check_one(client, path: str, endpoint: str) -> list[str]:
    """Return a list of human-readable failure strings for a single route."""
    failures: list[str] = []
    resp = client.get(path)
    status = resp.status_code
    if status >= 500:
        failures.append(
            f"{path} ({endpoint}) returned 5xx ({status}):\n"
            f"{resp.get_data(as_text=True)[:1200]}"
        )
        return failures
    if status not in _OK_STATUSES:
        failures.append(
            f"{path} ({endpoint}) returned unexpected status {status}; "
            f"expected one of {sorted(_OK_STATUSES)}"
        )

    content_type = resp.headers.get("Content-Type", "")
    if "text/html" not in content_type.lower():
        return failures

    body = resp.get_data(as_text=True)
    failures.extend(
        f"{path} ({endpoint}) HTML body contains '{marker}' — "
        f"likely an unhandled server error rendered into the template."
        for marker in _ERROR_MARKERS
        if marker in body
    )

    # Redirects don't need a <title>; only check 2xx HTML responses.
    if 200 <= status < 300 and "<title" not in body.lower():
        failures.append(
            f"{path} ({endpoint}) returned HTML 200 without a <title> element"
        )
    return failures


def test_smoke_targets_are_discovered(flask_app):
    """Sanity: we must find a non-trivial number of smoke-able routes."""
    targets = _iter_smoke_targets(flask_app)
    assert (
        len(targets) >= 10
    ), f"expected >=10 unparameterized GET routes, got {len(targets)}: {targets}"


def test_all_get_routes_do_not_500(client, flask_app):
    """Every unparameterized GET route must return a controlled status.

    We iterate rather than parametrise to avoid rebuilding the Flask app at
    pytest collection time (which would require polluting ``os.environ`` and
    monkey-patching ``config.Config`` class attributes before the session's
    conftest fixtures get a chance to set them, breaking later tests).
    """
    targets = _iter_smoke_targets(flask_app)
    assert targets, "no smoke targets discovered"

    all_failures: list[str] = []
    for path, endpoint in targets:
        all_failures.extend(_check_one(client, path, endpoint))

    if all_failures:
        pytest.fail(
            f"{len(all_failures)} route smoke failure(s):\n" + "\n\n".join(all_failures)
        )
