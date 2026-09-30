#!/usr/bin/env python3
"""Validate Lychee results, independently fetching HTTP 429 URLs with curl.

Some storefronts reject Lychee's requests while the same-runner curl GET
succeeds. A 429 is never accepted: curl must fetch that exact URL with valid
TLS and finish with HTTP 2xx. All other errors remain failures.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


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
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return 0
    status = result.stdout.strip()
    return int(status) if result.returncode == 0 and status.isdigit() else 0


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
    report: dict[str, Any], fetch_status: Callable[[str], int] = curl_status
) -> list[str]:
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
        if status.get("code") == 429:
            if url not in verified:
                verified[url] = fetch_status(url)
            if 200 <= verified[url] < 300:
                print(f"Verified with curl HTTP {verified[url]}: {url}")
                continue
        failures.append(f"Link validation failed: {url} ({status.get('code')})")
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

        failures = check_report(report, verify)
        report["curl_verification"] = verified
        report["validation_errors"] = failures
        args.report.write_text(json.dumps(report, indent=2) + "\n")
    except (OSError, ValueError) as error:
        print(f"Unable to validate link report: {error}")
        return 1
    for failure in failures:
        print(failure)
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
