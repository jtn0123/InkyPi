# pyright: reportMissingImports=false
"""Wiring check: the integration fixture stack must actually capture
/api/client-log POSTs.

Before this test existed, ``tests/conftest.py`` did not register
``client_log_bp`` on the integration ``flask_app`` fixture, which meant
POSTs to ``/api/client-log`` returned 404 and the autouse
``client_log_capture`` tripwire in ``tests/integration/conftest.py`` was
a silent no-op.

This test proves end-to-end that:

    1. ``/api/client-log`` is routable on the integration app (not 404).
    2. ``INKYPI_TEST_CAPTURE_CLIENT_LOG`` is set by the autouse fixture.
    3. A valid ``warn``/``error`` report lands in
       ``get_captured_reports()`` — so the tripwire would fire on
       teardown if the test itself did not clear it.

We clear the captured list at the end so the autouse teardown
assertion does not flag *this* test as a failure.
"""

from __future__ import annotations

import json
import os


def test_client_log_blueprint_is_registered_and_captured(client):
    from blueprints.client_log import (
        get_captured_reports,
        reset_captured_reports,
    )

    # 1. Env var is set by the autouse integration fixture.
    assert os.environ.get("INKYPI_TEST_CAPTURE_CLIENT_LOG", "").lower() in {
        "1",
        "true",
        "yes",
    }

    # 2. Route exists on the integration flask_app (regression: was 404).
    resp = client.post(
        "/api/client-log",
        data=json.dumps({"level": "error", "message": "tripwire-wiring-check"}),
        content_type="application/json",
    )
    assert resp.status_code == 204, (
        "POST /api/client-log returned "
        f"{resp.status_code} — client_log_bp may not be registered on flask_app"
    )

    # 3. The report landed in the capture buffer that the tripwire inspects.
    reports = get_captured_reports()
    assert any(
        r.get("message") == "tripwire-wiring-check" and r.get("level") == "error"
        for r in reports
    ), f"captured reports missing expected entry: {reports!r}"

    # Clear before teardown so the autouse tripwire does not flag this test.
    reset_captured_reports()


def test_client_error_blueprint_is_registered(client):
    """Sibling endpoint /api/client-error must also be routable on flask_app."""
    resp = client.post(
        "/api/client-error",
        data=json.dumps({"message": "wiring-check"}),
        content_type="application/json",
    )
    assert resp.status_code == 204, (
        "POST /api/client-error returned "
        f"{resp.status_code} — client_error_bp may not be registered on flask_app"
    )
