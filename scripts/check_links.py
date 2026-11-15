#!/usr/bin/env python3
"""Validate Lychee results, independently refetching throttled URLs with curl.

Some storefronts reject Lychee's requests (HTTP 429) or shed load with a
transient 503 while the same-runner curl GET succeeds. Neither status is ever
accepted on its own: curl must fetch that exact URL with valid TLS and finish
with HTTP 2xx. All other errors remain failures.

The one exception is a short list of stores that refuse automated requests
from CI runners outright (Cloudflare bot challenges, Amazon's robot check).
From a runner their 403/429/5xx says nothing about whether the page exists,
so when curl is refused too the link is reported as unverifiable, as a
warning. A 404 or 410, a DNS or TLS failure, or any other status from those
hosts is still a failure, and every other host keeps the strict rule.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

# Statuses that signal "try again later" rather than a broken link.
RECHECK_STATUSES = frozenset({429, 503})
# Stores whose bot protection refuses CI runners. Between 2026-10-25 and
# 2026-11-15 they caused all 10 failed link checks out of 57 runs. Add a host
# here only when its refusals are a runner block, not a dead page.
BOT_HOSTILE_HOSTS = frozenset(
    {"waveshare.com", "www.waveshare.com", "amzn.to", "collabs.shop"}
)
# How those stores refuse a runner: a bot challenge (403), throttling (429),
# or an error page from the store or its CDN (5xx, Cloudflare 52x).
REFUSAL_STATUSES = frozenset({403, 429, 500, 502, 503, 504, 520, 521, 522, 523, 524})
# curl itself retries 429/5xx responses before giving up on a URL.
CURL_RETRIES = 2
CURL_RETRY_DELAY_S = 5


def curl_status(url: str) -> int:
    if urlsplit(url).scheme not in {"http", "https"}:
        return 0
    try:
        result = subprocess.run(
            [
                "curl",
                "--silent",
                "--show-error",
                "--fail",
                "--location",
                "--max-redirs",
                "10",
                "--max-time",
                "25",
                "--retry",
                str(CURL_RETRIES),
                "--retry-delay",
                str(CURL_RETRY_DELAY_S),
                "--proto",
                "=http,https",
                "--proto-redir",
                "=http,https",
                "--output",
                "/dev/null",
                "--write-out",
                "%{http_code}",
                "--url",
                url,
            ],
            capture_output=True,
            text=True,
            timeout=100,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return 0
    status = result.stdout.strip()
    if not status.isdigit():
        return 0
    code = int(status)
    if result.returncode == 0:
        return code
    # --fail exits non-zero on an HTTP error; keep that status so callers can
    # tell a refusal from a missing page. Anything else (DNS, TLS, timeout,
    # a cut-off body) is 0, never a success.
    return code if code >= 400 else 0


def is_bot_hostile(url: str) -> bool:
    return (urlsplit(url).hostname or "").lower() in BOT_HOSTILE_HOSTS


def report_errors(report: dict[str, Any]) -> list[dict[str, Any]] | None:
    buckets = report.get("error_map")
    if not isinstance(buckets, dict):
        return None
    errors = []
    for entries in buckets.values():
        if not isinstance(entries, list) or any(
            not isinstance(entry, dict) for entry in entries
        ):
            return None
        errors.extend(entries)
    return errors


def check_report(
    report: dict[str, Any],
    fetch_status: Callable[[str], int] = curl_status,
    unverifiable: list[str] | None = None,
) -> list[str]:
    """Return the failures; links a store refused are appended to *unverifiable*."""
    total = report.get("total")
    errors = report_errors(report)
    if not isinstance(total, int) or total <= 0:
        return ["No links were found; refusing an empty validation pass."]
    if errors is None or report.get("errors") != len(errors):
        return ["Link error report is incomplete or malformed."]
    failures = []
    if any(report.get(key, 0) for key in ("timeouts", "unknown", "unsupported")):
        failures.append("Link checker reported timeouts or unresolved results.")
    verified: dict[str, int] = {}
    for error in errors:
        url = error.get("url")
        status = error.get("status")
        if not isinstance(url, str) or not isinstance(status, dict):
            failures.append("Malformed link error entry.")
            continue
        code = status.get("code")
        store = is_bot_hostile(url)
        if code in RECHECK_STATUSES or (store and code in REFUSAL_STATUSES):
            if url not in verified:
                verified[url] = fetch_status(url)
            if 200 <= verified[url] < 300:
                print(f"Verified with curl HTTP {verified[url]}: {url}")
                continue
            if store and verified[url] in REFUSAL_STATUSES:
                note = f"{url} (checker {code}, curl {verified[url]})"
                if unverifiable is not None and note not in unverifiable:
                    unverifiable.append(note)
                continue
        failures.append(f"Link validation failed: {url} ({code})")
    print(f"Checked {total} link occurrences; {len(failures)} failures remain.")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--cookie-jar", required=True)
    parser.add_argument("inputs", nargs="+")
    args = parser.parse_args()
    result = subprocess.run(
        [
            "lychee",
            "--no-progress",
            "--verbose",
            "--max-concurrency",
            "4",
            "--retry-wait-time",
            "5",
            "--cookie-jar",
            args.cookie_jar,
            "--format",
            "json",
            "--output",
            str(args.report),
            *args.inputs,
        ],
        timeout=600,
        check=False,
    )
    # Lychee uses exit 2 for rejected links; other exits are tool failures.
    if result.returncode not in {0, 2}:
        return 1
    try:
        report = json.loads(args.report.read_text())
        if not isinstance(report, dict):
            raise ValueError("Expected a link report object")
        if result.returncode == 2 and not report.get("errors"):
            raise ValueError("Failed checker did not provide its rejected links")
        verified: dict[str, int] = {}

        def verify(url: str) -> int:
            verified[url] = curl_status(url)
            return verified[url]

        refused: list[str] = []
        failures = check_report(report, verify, refused)
        report["curl_verification"] = verified
        report["unverifiable"] = refused
        report["validation_errors"] = failures
        args.report.write_text(json.dumps(report, indent=2) + "\n")
    except (OSError, ValueError) as error:
        print(f"Unable to validate link report: {error}")
        return 1
    for note in refused:
        # A GitHub Actions annotation, so the skipped check stays visible.
        print(f"::warning::Store refused the link checker, not verified: {note}")
    for failure in failures:
        print(failure)
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
