"""The alternate client must fetch the URL successfully, never accept a 429."""

import importlib.util
import json
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread
from types import ModuleType
from typing import Any

import pytest


@pytest.fixture
def checker() -> ModuleType:
    path = Path(__file__).parents[2] / "scripts/check_links.py"
    spec = importlib.util.spec_from_file_location("check_links", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def error_report(url: str, status: int = 429) -> dict[str, Any]:
    return {
        "total": 1,
        "errors": 1,
        "error_map": {"README.md": [{"url": url, "status": {"code": status}}]},
    }


@pytest.mark.parametrize("status", [200, 204, 302, 404, 429, 500])
def test_real_get_must_succeed(checker: ModuleType, status: int) -> None:
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            requests.append(self.path)
            self.send_response(status)
            self.end_headers()

        def log_message(self, format: str, *args: Any) -> None:
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/resource"
        failures = checker.check_report(error_report(url))
        assert bool(failures) == (not 200 <= status < 300)
        assert requests == ["/resource"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


def test_other_errors_cannot_be_overridden(checker: ModuleType) -> None:
    def unexpected_fetch(url: str) -> int:
        pytest.fail("Only HTTP 429 results may use the independent GET")

    assert checker.check_report(
        error_report("https://example.test/missing", 404), unexpected_fetch
    )


def test_duplicate_urls_are_fetched_once(checker: ModuleType) -> None:
    calls = []
    report = error_report("https://example.test/rate-limited")
    report["total"] = report["errors"] = 2
    report["error_map"]["README.md"] *= 2

    def fetch(url: str) -> int:
        calls.append(url)
        return 200

    assert checker.check_report(report, fetch) == []
    assert calls == ["https://example.test/rate-limited"]


@pytest.mark.parametrize(
    "report",
    [
        {},
        {"total": 0, "errors": 0, "error_map": {}},
        {"total": 1, "errors": 1, "error_map": {}},
        {"total": 1, "errors": 0, "error_map": {"README.md": None}},
        {"total": 1, "errors": 0, "error_map": {}, "timeouts": 1},
    ],
)
def test_empty_and_incomplete_reports_fail(
    checker: ModuleType, report: dict[str, Any]
) -> None:
    assert checker.check_report(report)


def test_non_http_urls_are_not_fetched(checker: ModuleType) -> None:
    assert checker.curl_status("file:///etc/passwd") == 0


def test_failed_tool_cannot_use_a_stale_success_report(
    checker: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = tmp_path / "links.json"
    report.write_text(json.dumps({"total": 1, "errors": 0, "error_map": {}}))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "check_links.py",
            "--report",
            str(report),
            "--cookie-jar",
            str(tmp_path / "cookies"),
            "README.md",
        ],
    )
    monkeypatch.setattr(
        checker.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args=[], returncode=2),
    )
    assert checker.main() == 1


@pytest.mark.parametrize(
    "status,title,text,valid",
    [
        (200, "Real resource", "Public resource content " * 10, True),
        (403, "Real resource", "Public resource content " * 10, False),
        (429, "Real resource", "Public resource content " * 10, False),
        (200, "Just a moment...", "Verify your browser " * 10, False),
        (200, "Page not found", "Missing resource " * 10, False),
        (200, "Sign in", "Account credentials required " * 10, False),
        (200, "", "Public resource content " * 10, False),
        (200, "Resource", "", False),
    ],
)
def test_browser_requires_successful_content(
    checker: ModuleType, status: int, title: str, text: str, valid: bool
) -> None:
    assert checker.browser_document_valid(status, title, text) is valid


@pytest.mark.parametrize("status", [403, 429])
@pytest.mark.parametrize("verified", [True, False])
def test_browser_rejection_recheck_is_fail_closed(
    checker: ModuleType, status: int, verified: bool
) -> None:
    url = "https://example.test/resource"
    failures = checker.check_report(
        error_report(url, status),
        lambda url: 0,
        {url: {"verified": verified, "status": 200 if verified else status}},
    )
    assert bool(failures) is (not verified)
