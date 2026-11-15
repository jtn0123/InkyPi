"""The alternate client must fetch the URL successfully, never accept a 429/503.

The only exception is a store on the bot-hostile list refusing both checkers,
which is reported as unverifiable rather than passed or failed.
"""

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


@pytest.mark.parametrize("reported", [429, 503])
@pytest.mark.parametrize("status", [200, 204, 302, 404, 429, 500])
def test_real_get_must_succeed(
    checker: ModuleType, status: int, reported: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(checker, "CURL_RETRIES", 0)
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
        failures = checker.check_report(error_report(url, reported))
        assert bool(failures) == (not 200 <= status < 300)
        assert requests == ["/resource"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


def test_transient_503_is_retried_until_success(
    checker: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(checker, "CURL_RETRIES", 1)
    monkeypatch.setattr(checker, "CURL_RETRY_DELAY_S", 1)
    statuses = [503, 200]

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(statuses.pop(0))
            self.end_headers()

        def log_message(self, format: str, *args: Any) -> None:
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/flaky"
        assert checker.check_report(error_report(url, 503)) == []
        assert statuses == []
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


def test_other_errors_cannot_be_overridden(checker: ModuleType) -> None:
    def unexpected_fetch(url: str) -> int:
        pytest.fail("Only HTTP 429/503 results may use the independent GET")

    for status in (404, 500, 502):
        assert checker.check_report(
            error_report("https://example.test/missing", status), unexpected_fetch
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


_STORE = "https://www.waveshare.com/7.5inch-e-paper-hat.htm?&aff_id=111126"


@pytest.mark.parametrize("checker_status", [403, 503, 522])
@pytest.mark.parametrize("curl_status", [403, 429, 503])
def test_a_store_refusing_both_checkers_is_unverifiable(
    checker: ModuleType, checker_status: int, curl_status: int
) -> None:
    unverifiable: list[str] = []
    failures = checker.check_report(
        error_report(_STORE, checker_status), lambda url: curl_status, unverifiable
    )
    assert failures == []
    assert unverifiable == [f"{_STORE} (checker {checker_status}, curl {curl_status})"]


@pytest.mark.parametrize("curl_status", [404, 410, 0])
def test_a_store_page_that_is_gone_or_unreachable_still_fails(
    checker: ModuleType, curl_status: int
) -> None:
    unverifiable: list[str] = []
    failures = checker.check_report(
        error_report(_STORE, 403), lambda url: curl_status, unverifiable
    )
    assert failures == [f"Link validation failed: {_STORE} (403)"]
    assert unverifiable == []


def test_a_store_404_fails_without_a_recheck(checker: ModuleType) -> None:
    def unexpected_fetch(url: str) -> int:
        pytest.fail("A 404 is not a refusal, so it must not be rechecked")

    assert checker.check_report(error_report(_STORE, 404), unexpected_fetch)


def test_a_store_that_answers_curl_is_verified(checker: ModuleType) -> None:
    unverifiable: list[str] = []
    assert (
        checker.check_report(error_report(_STORE, 403), lambda url: 200, unverifiable)
        == []
    )
    assert unverifiable == []


@pytest.mark.parametrize(
    "url", ["https://amzn.to/3HPRTEZ", "https://collabs.shop/q2jmza"]
)
def test_every_listed_store_is_treated_alike(checker: ModuleType, url: str) -> None:
    unverifiable: list[str] = []
    assert (
        checker.check_report(error_report(url, 503), lambda u: 503, unverifiable) == []
    )
    assert len(unverifiable) == 1


def test_other_hosts_keep_the_strict_rule(checker: ModuleType) -> None:
    def unexpected_fetch(url: str) -> int:
        pytest.fail("A 403 from an unlisted host must not be rechecked")

    unverifiable: list[str] = []
    url = "https://example.test/page"
    assert checker.check_report(error_report(url, 403), unexpected_fetch, unverifiable)
    assert checker.check_report(error_report(url, 503), lambda u: 503, unverifiable)
    assert unverifiable == []


def test_lookalike_hosts_are_not_on_the_store_list(checker: ModuleType) -> None:
    assert checker.is_bot_hostile("https://shop.waveshare.com.evil.test/x") is False
    assert checker.is_bot_hostile("https://notwaveshare.com/x") is False
    assert checker.is_bot_hostile("https://WWW.WAVESHARE.COM/x") is True


@pytest.mark.parametrize("status", [404, 503])
def test_curl_status_keeps_the_http_error_code(
    checker: ModuleType, status: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(checker, "CURL_RETRIES", 0)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(status)
            self.end_headers()

        def log_message(self, format: str, *args: Any) -> None:
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/x"
        assert checker.curl_status(url) == status
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


def test_main_reports_store_refusals_as_warnings(
    checker: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = tmp_path / "links.json"
    report.write_text(json.dumps(error_report(_STORE, 403)))
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
    monkeypatch.setattr(checker, "curl_status", lambda url: 403)

    assert checker.main() == 0
    written = json.loads(report.read_text())
    assert written["unverifiable"] == [f"{_STORE} (checker 403, curl 403)"]
    assert written["validation_errors"] == []
    out = capsys.readouterr().out
    assert f"::warning::Store refused the link checker, not verified: {_STORE}" in out
