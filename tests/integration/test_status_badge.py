# pyright: reportMissingImports=false
"""Tests for the in-app status badge surface (JTN-709).

The badge is a tiny fixed-position element injected by `status_badge.js` on
every page. Playwright-level tests would add value but are deferred — these
server-rendered checks verify the script is wired in and that the diagnostics
contract the badge depends on is intact.
"""

from __future__ import annotations

import json


def test_every_page_loads_status_badge_script(client):
    """Every top-level page in the shared base template loads status_badge.js."""
    paths = ["/", "/playlist", "/history", "/settings", "/plugin/clock"]
    for path in paths:
        resp = client.get(path)
        assert resp.status_code == 200, f"{path}: expected 200"
        html = resp.data.decode()
        assert "scripts/status_badge.js" in html, (
            f"{path}: status_badge.js is not loaded — the base template must "
            "include it so the badge surfaces on every page"
        )


def test_diagnostics_exposes_badge_contract(client, flask_app):
    """The diagnostics endpoint exposes the keys the badge consumes."""
    import blueprints.client_log as cl_mod

    if "client_log" not in flask_app.blueprints:
        flask_app.register_blueprint(cl_mod.client_log_bp)
    cl_mod.reset_recent_errors()

    resp = client.get("/api/diagnostics")
    assert resp.status_code == 200
    data = resp.get_json()
    # Keys derived by deriveState() in status_badge.js
    assert "refresh_task" in data
    assert "plugin_health" in data
    assert "last_update_failure" in data
    assert "recent_client_log_errors" in data
    assert set(data["recent_client_log_errors"].keys()) >= {
        "count_5m",
        "warn_count_5m",
    }


def test_client_log_error_flips_recent_counter(client, flask_app):
    """Posting a client-log error shows up in the diagnostics payload the badge polls."""
    import blueprints.client_log as cl_mod

    if "client_log" not in flask_app.blueprints:
        flask_app.register_blueprint(cl_mod.client_log_bp)
    cl_mod.reset_recent_errors()

    # Baseline: zero errors.
    data = client.get("/api/diagnostics").get_json()
    assert data["recent_client_log_errors"]["count_5m"] == 0

    # Post a client-log error — badge should flip to "error" on the next poll.
    resp = client.post(
        "/api/client-log",
        data=json.dumps({"level": "error", "message": "boom"}),
        content_type="application/json",
    )
    assert resp.status_code == 204

    data = client.get("/api/diagnostics").get_json()
    assert data["recent_client_log_errors"]["count_5m"] == 1
    assert data["recent_client_log_errors"]["last_error_ts"] is not None

    # Clear the autouse client-log tripwire — we intentionally posted an
    # error as part of this test and don't want the teardown assertion to
    # fire. The tripwire is designed to catch stray console.warn/error from
    # browser JS, not deliberate server-side fixtures.
    cl_mod.reset_captured_reports()


def test_no_polling_in_test_mode_via_opt_out_meta(client):
    """The badge script respects the status-badge-disabled meta opt-out.

    Pages don't currently set this meta, but the script is expected to no-op
    when the meta is present — this protects future test pages that want to
    suppress the 30s poll.
    """
    import re
    from pathlib import Path

    js_path = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "static"
        / "scripts"
        / "status_badge.js"
    )
    text = js_path.read_text()
    # Opt-out check happens before any fetch/polling is scheduled.
    m_optout = re.search(r'status-badge-disabled', text)
    m_fetch = text.find("fetch(")
    assert m_optout is not None, "opt-out meta not referenced in status_badge.js"
    assert m_fetch > 0
    assert m_optout.start() < m_fetch, "opt-out must be checked before fetch runs"
