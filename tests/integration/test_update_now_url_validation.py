# pyright: reportMissingImports=false
"""JTN-776: /update_now URL validation errors must return HTTP 4xx, not 500.

Previously, plugins raised a bare ``RuntimeError("Invalid URL: ...")`` from
``generate_image`` when a user-supplied URL failed SSRF / scheme validation.
The plugin blueprint translated those into HTTP 500 ``internal_error``, which
hid the real reason from the user and polluted server-error metrics.

The fix is a typed ``URLValidationError`` (subclass of ``RuntimeError`` for
backwards compatibility) that the blueprint catches specifically and maps to
HTTP 422 ``validation_error`` with the validator message in ``error``.

Covers:
    - file:// scheme                     -> 422
    - 127.0.0.1 (loopback)               -> 422
    - 169.254.169.254 (link-local / IMDS) -> 422
    - malformed URL (missing hostname)   -> 422
    - private-range DNS resolution        -> 422
    - unexpected RuntimeError (post-URL-validation plugin failure) -> 400
      (unchanged JTN-326 behaviour — exception text is NOT echoed)
"""

from __future__ import annotations

import socket

# ---------------------------------------------------------------------------
# image_url plugin
# ---------------------------------------------------------------------------


class TestImageUrlValidation:
    """/update_now with plugin_id=image_url must reject unsafe URLs with 4xx."""

    def test_file_scheme_returns_422(self, client):
        """file:// URL is a validation error, not a server error."""
        resp = client.post(
            "/update_now",
            data={"plugin_id": "image_url", "url": "file:///etc/passwd"},
        )
        assert resp.status_code == 422
        body = resp.get_json()
        assert body["success"] is False
        assert body["code"] == "validation_error"
        # Validator message must reach the user verbatim.
        assert "Invalid URL" in body["error"]
        assert "scheme must be http or https" in body["error"]
        # Must NOT be the generic internal-error message.
        assert body["error"] != "An internal error occurred"

    def test_loopback_literal_returns_422(self, client):
        """http://127.0.0.1/... is SSRF-blocked -> 422, not 500."""
        resp = client.post(
            "/update_now",
            data={
                "plugin_id": "image_url",
                "url": "http://127.0.0.1:8080/image.png",
            },
        )
        assert resp.status_code == 422
        body = resp.get_json()
        assert body["code"] == "validation_error"
        assert "Invalid URL" in body["error"]
        assert "private" in body["error"] or "loopback" in body["error"]

    def test_link_local_imds_returns_422(self, client):
        """http://169.254.169.254/ (cloud metadata) must be rejected with 422."""
        resp = client.post(
            "/update_now",
            data={
                "plugin_id": "image_url",
                "url": "http://169.254.169.254/latest/meta-data/",
            },
        )
        assert resp.status_code == 422
        body = resp.get_json()
        assert body["code"] == "validation_error"
        assert "Invalid URL" in body["error"]

    def test_private_dns_returns_422(self, client, monkeypatch):
        """Hostname that resolves to a private IP must be rejected with 422."""
        # Resolve *any* hostname to 10.0.0.5 (RFC1918).
        monkeypatch.setattr(
            socket,
            "getaddrinfo",
            lambda *a, **kw: [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 0))
            ],
        )
        resp = client.post(
            "/update_now",
            data={
                "plugin_id": "image_url",
                "url": "http://intranet.example.com/img.png",
            },
        )
        assert resp.status_code == 422
        body = resp.get_json()
        assert body["code"] == "validation_error"
        assert "Invalid URL" in body["error"]

    def test_malformed_url_no_hostname_returns_422(self, client):
        """A URL missing a hostname (scheme-only) is a validation error."""
        resp = client.post(
            "/update_now",
            data={"plugin_id": "image_url", "url": "http://"},
        )
        assert resp.status_code == 422
        body = resp.get_json()
        assert body["code"] == "validation_error"
        assert "Invalid URL" in body["error"]

    def test_details_field_points_at_url(self, client):
        """Validation failures should identify the offending field for the UI."""
        resp = client.post(
            "/update_now",
            data={"plugin_id": "image_url", "url": "file:///etc/passwd"},
        )
        assert resp.status_code == 422
        body = resp.get_json()
        details = body.get("details") or {}
        assert details.get("field") == "url"

    def test_url_validation_failure_does_not_record_history_sidecar(
        self, client, device_config_dev
    ):
        """ISSUE-006 — a rejected URL must NOT bump Dashboard "Refreshes" /
        "Errors" KPIs.  The dashboard derives those numbers by counting
        history JSON sidecars in ``device_config.history_image_dir``;
        URL validation errors are user input rejected pre-render, so we
        push a fallback image to the device but skip the sidecar.
        """
        import json
        import os

        history_dir = device_config_dev.history_image_dir
        os.makedirs(history_dir, exist_ok=True)
        # Snapshot existing sidecars so the test isn't fragile to fixture state.
        sidecars_before = {
            name
            for name in os.listdir(history_dir)
            if name.endswith(".json")
        }

        resp = client.post(
            "/update_now",
            data={"plugin_id": "image_url", "url": "javascript:alert(1)"},
        )
        assert resp.status_code == 422

        sidecars_after = {
            name
            for name in os.listdir(history_dir)
            if name.endswith(".json")
        }
        new_sidecars = sidecars_after - sidecars_before
        assert not new_sidecars, (
            f"URL validation failure should not write a history sidecar — "
            f"would inflate Dashboard refresh/error counts. New: {new_sidecars}"
        )

        # And just to double-check: any sidecar that *would* have been
        # written would have included a Manual Update + URLValidationError
        # marker.  Make sure nothing matching that ended up on disk either.
        for name in sidecars_after:
            with open(os.path.join(history_dir, name), encoding="utf-8") as fh:
                payload = json.load(fh)
            assert payload.get("error_class") != "URLValidationError"


# ---------------------------------------------------------------------------
# screenshot plugin
# ---------------------------------------------------------------------------


class TestScreenshotUrlValidation:
    """/update_now with plugin_id=screenshot must reject unsafe URLs with 4xx."""

    def test_file_scheme_returns_422(self, client):
        resp = client.post(
            "/update_now",
            data={"plugin_id": "screenshot", "url": "file:///etc/passwd"},
        )
        assert resp.status_code == 422
        body = resp.get_json()
        assert body["code"] == "validation_error"
        assert "Invalid URL" in body["error"]

    def test_malformed_url_returns_422(self, client):
        """Non-URL input like ``not-a-url-at-all`` is rejected as a validation error.

        urlparse treats this as a path-only URL (no scheme) so ``validate_url``
        raises ``URL scheme must be http or https``.
        """
        resp = client.post(
            "/update_now",
            data={"plugin_id": "screenshot", "url": "not-a-url-at-all"},
        )
        assert resp.status_code == 422
        body = resp.get_json()
        assert body["code"] == "validation_error"
        assert "Invalid URL" in body["error"]


# ---------------------------------------------------------------------------
# Regression: non-URL plugin failures still return the generic 400/500.
# ---------------------------------------------------------------------------


class TestNonUrlFailuresStillOpaque:
    """Ensure URL-validation fix does NOT widen the existing exception contract.

    JTN-326 requires that plugin RuntimeError text (e.g. missing API key) stays
    out of the HTTP response body — only URL validator messages may leak through.
    """

    def test_ai_image_missing_key_still_returns_400_generic(self, client):
        """ai_image without API key -> RuntimeError, must stay generic (JTN-326)."""
        resp = client.post(
            "/update_now",
            data={
                "plugin_id": "ai_image",
                "textPrompt": "hi",
                "imageModel": "gpt-image-1.5",
                "quality": "standard",
            },
        )
        assert resp.status_code == 400
        body = resp.get_json()
        assert body["code"] == "plugin_error"
        assert body["error"] == "An internal error occurred"
        # No plugin exception text should leak.
        assert "API Key" not in body["error"]

    def test_unexpected_exception_returns_500(self, client, monkeypatch):
        """Non-URL, non-RuntimeError plugin failures must still be 500 internal_error."""
        from plugins.plugin_registry import get_plugin_instance as _real_get

        def _boom(plugin_config):
            inst = _real_get(plugin_config)

            def _raise(*a, **kw):
                raise ValueError("unexpected internal failure")

            inst.generate_image = _raise  # type: ignore[method-assign]
            return inst

        # Monkey-patch the blueprint's imported symbol so _update_now_direct
        # (and _run_update_now) both see the wrapped factory.
        import blueprints.plugin as plugin_bp_mod

        monkeypatch.setattr(plugin_bp_mod, "get_plugin_instance", _boom)

        resp = client.post(
            "/update_now",
            data={"plugin_id": "clock"},  # clock doesn't need secrets
        )
        assert resp.status_code == 500
        body = resp.get_json()
        assert body["code"] == "internal_error"
        assert body["error"] == "An internal error occurred"
        # The raw exception message must not leak.
        assert "unexpected internal failure" not in body["error"]


# Note: unit-level tests for URLValidationError itself live in
# tests/unit/test_security_utils.py (TestURLValidationError) and
# tests/plugins/test_image_url.py (test_image_url_raises_url_validation_error)
# to keep this integration module focused on the HTTP contract.
