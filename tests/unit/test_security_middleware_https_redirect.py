# pyright: reportMissingImports=false
"""Unit tests for the HTTPS upgrade middleware host allow-list (JTN-317).

Regression tests for the open-redirect vulnerability in
``setup_https_redirect`` flagged by CodeQL rule ``py/url-redirection``
(alert #52). An attacker could previously force a redirect to an
attacker-controlled domain by spoofing the ``Host`` header when
``INKYPI_FORCE_HTTPS=1`` was set.

These tests ensure that:

* Requests with a host that is not in the allow-list are rejected
  with HTTP 400, rather than being redirected to the spoofed host.
* Requests with an allowed host are still redirected from
  ``http://`` to ``https://`` (functionality preserved).
* ``X-Forwarded-Proto: https`` still bypasses the redirect cleanly.
* The allow-list is configurable via ``INKYPI_ALLOWED_HOSTS``.
"""

from __future__ import annotations

import importlib
import sys


def _reload_inkypi(monkeypatch, env):
    """Reload the inkypi module with a clean environment.

    Mirrors the helper in ``tests/unit/test_inkypi.py`` but local to
    this test file so the two stay independent.
    """
    for key in (
        "INKYPI_ENV",
        "FLASK_ENV",
        "INKYPI_CONFIG_FILE",
        "INKYPI_PORT",
        "PORT",
        "INKYPI_FORCE_HTTPS",
        "INKYPI_ALLOWED_HOSTS",
    ):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    monkeypatch.setattr(sys, "argv", ["inkypi.py"])

    if "inkypi" in sys.modules:
        del sys.modules["inkypi"]

    import inkypi  # noqa: F401

    mod = importlib.reload(sys.modules["inkypi"])
    mod.main([])
    return mod


# ---------------------------------------------------------------------------
# Open-redirect regression (JTN-317)
# ---------------------------------------------------------------------------


def test_spoofed_host_is_rejected_not_redirected(monkeypatch):
    """A spoofed Host header must NOT produce a Location: https://evil.com/.

    This is the core regression test for the CodeQL
    py/url-redirection alert #52.
    """
    mod = _reload_inkypi(
        monkeypatch,
        env={"INKYPI_FORCE_HTTPS": "1", "INKYPI_ENV": "production"},
    )
    app = mod.app

    client = app.test_client()
    resp = client.get("/", headers={"Host": "evil.com"})

    # Must NOT redirect to the attacker-controlled host.
    assert resp.status_code != 301, (
        f"Spoofed host was redirected (status {resp.status_code}, "
        f"location {resp.location!r}) — open-redirect regression"
    )
    if resp.location is not None:
        assert "evil.com" not in resp.location
    # The defensive behaviour is a 400 Bad Request.
    assert resp.status_code == 400


def test_spoofed_host_with_port_is_rejected(monkeypatch):
    """Host header including a port is still rejected when not allow-listed."""
    mod = _reload_inkypi(
        monkeypatch,
        env={"INKYPI_FORCE_HTTPS": "1", "INKYPI_ENV": "production"},
    )
    app = mod.app

    client = app.test_client()
    resp = client.get("/", headers={"Host": "attacker.example:8080"})

    assert resp.status_code == 400
    if resp.location is not None:
        assert "attacker.example" not in resp.location


def test_allowed_host_still_redirects(monkeypatch):
    """A request with an allow-listed host is still upgraded to HTTPS."""
    mod = _reload_inkypi(
        monkeypatch,
        env={"INKYPI_FORCE_HTTPS": "1", "INKYPI_ENV": "production"},
    )
    app = mod.app

    client = app.test_client()
    # Flask's test client defaults Host to "localhost" which is
    # in the default allow-list.
    resp = client.get("/settings", headers={"Host": "localhost"})

    assert resp.status_code == 301
    assert resp.location == "https://localhost/settings"


def test_default_allowed_hosts_include_inkypi_local(monkeypatch):
    """``inkypi.local`` is in the default allow-list."""
    mod = _reload_inkypi(
        monkeypatch,
        env={"INKYPI_FORCE_HTTPS": "1", "INKYPI_ENV": "production"},
    )
    app = mod.app

    client = app.test_client()
    resp = client.get("/settings", headers={"Host": "inkypi.local"})

    assert resp.status_code == 301
    assert resp.location == "https://inkypi.local/settings"


def test_x_forwarded_proto_https_bypass_still_works(monkeypatch):
    """TLS-terminating proxies using X-Forwarded-Proto: https are unaffected.

    The allow-list check must only apply when we are actually going
    to redirect; a request already coming in behind a TLS proxy
    should pass through without a host lookup.
    """
    mod = _reload_inkypi(
        monkeypatch,
        env={"INKYPI_FORCE_HTTPS": "1", "INKYPI_ENV": "production"},
    )
    app = mod.app

    client = app.test_client()
    resp = client.get(
        "/healthz",
        headers={"X-Forwarded-Proto": "https", "Host": "whatever.example"},
    )
    assert resp.status_code == 200


def test_custom_allowed_hosts_env_var(monkeypatch):
    """INKYPI_ALLOWED_HOSTS lets operators add their own hostnames."""
    mod = _reload_inkypi(
        monkeypatch,
        env={
            "INKYPI_FORCE_HTTPS": "1",
            "INKYPI_ENV": "production",
            "INKYPI_ALLOWED_HOSTS": "mypi.example.com,localhost",
        },
    )
    app = mod.app

    client = app.test_client()
    resp = client.get("/settings", headers={"Host": "mypi.example.com"})
    assert resp.status_code == 301
    assert resp.location == "https://mypi.example.com/settings"

    # A host not in the custom allow-list is still rejected.
    resp2 = client.get("/settings", headers={"Host": "evil.example"})
    assert resp2.status_code == 400


def test_redirect_preserves_path_and_query_string(monkeypatch):
    """The upgrade redirect must preserve the original path and query string."""
    mod = _reload_inkypi(
        monkeypatch,
        env={"INKYPI_FORCE_HTTPS": "1", "INKYPI_ENV": "production"},
    )
    app = mod.app

    client = app.test_client()
    resp = client.get("/settings?foo=bar&baz=1", headers={"Host": "localhost"})
    assert resp.status_code == 301
    assert resp.location == "https://localhost/settings?foo=bar&baz=1"


def test_redirect_omits_trailing_question_mark_when_no_query(monkeypatch):
    """A request with no query string must not end the Location in ``?``."""
    mod = _reload_inkypi(
        monkeypatch,
        env={"INKYPI_FORCE_HTTPS": "1", "INKYPI_ENV": "production"},
    )
    app = mod.app

    client = app.test_client()
    resp = client.get("/", headers={"Host": "localhost"})
    assert resp.status_code == 301
    assert resp.location == "https://localhost/"


def test_allowed_host_ignores_port_suffix(monkeypatch):
    """``localhost:5000`` should count as the allow-listed ``localhost``."""
    mod = _reload_inkypi(
        monkeypatch,
        env={"INKYPI_FORCE_HTTPS": "1", "INKYPI_ENV": "production"},
    )
    app = mod.app

    client = app.test_client()
    resp = client.get("/settings", headers={"Host": "localhost:5000"})

    assert resp.status_code == 301
    assert resp.location == "https://localhost:5000/settings"
