# pyright: reportMissingImports=false
"""Logs access journey: trigger error, download logs, verify payload (JTN-727).

End-to-end flow:
    1. Force dev-mode log capture so errors land in the in-memory buffer.
    2. POST a malformed body to /settings/client_log -> server returns 400.
    3. POST a valid level=error entry with a distinctive marker -> server logs it.
    4. Open /settings and click "Download Logs"; capture the /download-logs response.
    5. Verify attachment Content-Disposition, non-empty payload, and that the
       payload contains both the distinctive marker AND a timestamp whose month
       prefix (from LOG_TIMESTAMP_FORMAT) is within the test window.
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import UTC, datetime

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.journey,
    pytest.mark.skipif(
        os.getenv("SKIP_BROWSER", "").lower() in ("1", "true")
        or os.getenv("SKIP_UI", "").lower() in ("1", "true"),
        reason="Browser/UI tests skipped by env",
    ),
]

from tests.integration.browser_helpers import navigate_and_wait  # noqa: E402


@pytest.fixture
def dev_log_handler(monkeypatch):
    """Force dev-mode log path and attach DevModeLogHandler to the root logger.

    The default test app does not install the dev log handler, so error logs
    never reach ``_dev_log_buffer`` which ``/download-logs`` reads from in the
    no-journal path. This fixture wires both up and tears down cleanly.
    """
    import blueprints.settings as settings_mod

    monkeypatch.setattr(settings_mod, "JOURNAL_AVAILABLE", False)
    handler = settings_mod.DevModeLogHandler()
    handler.setLevel(logging.DEBUG)
    root = logging.getLogger()
    root.addHandler(handler)
    # Clear any stale buffer contents from earlier tests in the same process.
    with settings_mod._dev_log_lock:
        settings_mod._dev_log_buffer.clear()
    try:
        yield
    finally:
        root.removeHandler(handler)
        with settings_mod._dev_log_lock:
            settings_mod._dev_log_buffer.clear()


def test_logs_access_trigger_error_download_verify(
    live_server, browser_page, client, dev_log_handler
):
    marker = f"JTN-727 deliberate error {uuid.uuid4().hex[:8]}"
    window_start = datetime.now(tz=UTC)

    # ---- Step 1: trigger error — malformed POST returns 400; a follow-up
    # level=error entry is logged with our distinctive marker. ----
    bad = client.post(
        "/settings/client_log",
        data="[]",  # JSON array, not a dict — endpoint rejects with 400
        content_type="application/json",
    )
    assert (
        bad.status_code == 400
    ), f"expected 4xx on malformed body, got {bad.status_code}"
    logged = client.post(
        "/settings/client_log",
        json={"level": "error", "message": marker},
    )
    assert logged.status_code == 200, "error-level log entry should be accepted"

    # ---- Step 2: open settings, click Download Logs, capture response. ----
    page = browser_page
    navigate_and_wait(page, live_server, "/settings")
    with page.expect_response(
        lambda r: r.url.endswith("/download-logs?hours=24") and r.status == 200,
        timeout=10000,
    ) as info:
        page.locator("#downloadLogsBtn").click()
    resp = info.value

    # ---- Step 3: assert attachment headers + non-empty payload. ----
    disposition = resp.header_value("content-disposition") or ""
    assert disposition.startswith("attachment;"), f"bad disposition: {disposition!r}"
    assert 'filename="inkypi_' in disposition, f"bad filename: {disposition!r}"
    body = resp.text()
    assert body.strip(), "downloaded logs payload should not be empty"

    # ---- Step 4: payload contains the deliberate error string AND a
    # timestamp within the test window. LOG_TIMESTAMP_FORMAT is
    # "%b %d %H:%M:%S" so we check the month+day prefix from now. ----
    assert marker in body, "downloaded logs should contain the deliberate error marker"
    window_prefix = window_start.strftime("%b %d")
    assert (
        window_prefix in body
    ), f"expected a {window_prefix!r} timestamp within the test window in payload"
