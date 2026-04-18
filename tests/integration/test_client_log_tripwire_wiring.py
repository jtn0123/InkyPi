# pyright: reportMissingImports=false
"""Wiring check: the integration ``flask_app`` fixture must route
``/api/client-log`` and ``/api/client-error`` so the autouse
``client_log_capture`` tripwire (JTN-680) is not a silent no-op.

Before this test existed, ``tests/conftest.py`` did not register
``client_log_bp`` or ``client_error_bp``, which meant POSTs returned 404
and no entry ever reached the capture buffer that the tripwire inspects.
If that regression reoccurs, the POST below 404s and this test fails
with a specific message — instead of the tripwire silently staying a
no-op forever.

Each test posts a payload the handler *rejects* at 400, so nothing
lands in the capture buffer and the autouse teardown stays quiet. The
signal we care about is "route exists" (400) vs "route missing" (404);
capture-hook mechanics themselves are exercised at unit level in
``tests/unit/test_client_log_capture.py``.
"""

from __future__ import annotations

import json
import os


def test_client_log_endpoint_routable_and_capture_env_set(client):
    # The autouse integration fixture (tests/integration/conftest.py) must
    # turn capture on — otherwise the tripwire cannot observe anything.
    assert os.environ.get("INKYPI_TEST_CAPTURE_CLIENT_LOG", "").lower() in {
        "1",
        "true",
        "yes",
    }, (
        "INKYPI_TEST_CAPTURE_CLIENT_LOG is not set — the autouse "
        "client_log_capture fixture in tests/integration/conftest.py is not "
        "active for this test."
    )

    # Invalid level → blueprint rejects with 400 (no capture, no teardown
    # trip). If the blueprint is not registered the response is 404 from
    # the catch-all handler instead.
    resp = client.post(
        "/api/client-log",
        data=json.dumps({"level": "info", "message": "wiring-check"}),
        content_type="application/json",
    )
    assert resp.status_code == 400, (
        "POST /api/client-log returned "
        f"{resp.status_code} (expected 400 from the blueprint's own "
        "validation). If the status is 404, client_log_bp is not "
        "registered on the integration flask_app fixture "
        "(tests/conftest.py) and the JTN-680 client-log tripwire is a "
        "silent no-op."
    )


def test_client_error_endpoint_routable(client):
    """Sibling /api/client-error blueprint must also be registered."""
    # Empty body → blueprint rejects with 400 for missing required "message".
    resp = client.post(
        "/api/client-error",
        data=json.dumps({}),
        content_type="application/json",
    )
    assert resp.status_code == 400, (
        "POST /api/client-error returned "
        f"{resp.status_code} (expected 400 from the blueprint's own "
        "validation). If the status is 404, client_error_bp is not "
        "registered on the integration flask_app fixture "
        "(tests/conftest.py)."
    )
