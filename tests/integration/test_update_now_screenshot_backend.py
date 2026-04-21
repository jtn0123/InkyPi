# pyright: reportMissingImports=false
"""JTN-789: ``ScreenshotBackendError`` from /update_now must become HTTP 503.

When the chromium screenshot subprocess fails twice in a row (initial
attempt + one retry) on Pi Zero 2 W under memory pressure,
``utils.image_utils.take_screenshot`` raises a typed
``ScreenshotBackendError``.  The plugin blueprint must catch it and return
HTTP 503 with ``code: "backend_unavailable"`` so operators see an
actionable error — not the generic 500 ``internal_error`` that a bare
``None`` return previously surfaced.
"""

from __future__ import annotations


class TestUpdateNowScreenshotBackend:
    """/update_now must map ``ScreenshotBackendError`` to HTTP 503."""

    def test_screenshot_backend_error_returns_503(self, client, monkeypatch):
        """Plugin raising ``ScreenshotBackendError`` -> 503 backend_unavailable."""
        from plugins.plugin_registry import get_plugin_instance as _real_get
        from utils.plugin_errors import ScreenshotBackendError

        def _boom(plugin_config):
            inst = _real_get(plugin_config)

            def _raise(*a, **kw):
                raise ScreenshotBackendError(
                    "Screenshot backend failed after retry: chromium subprocess "
                    "did not produce an image."
                )

            inst.generate_image = _raise  # type: ignore[method-assign]
            return inst

        import blueprints.plugin as plugin_bp_mod

        monkeypatch.setattr(plugin_bp_mod, "get_plugin_instance", _boom)

        resp = client.post(
            "/update_now",
            data={"plugin_id": "clock"},  # clock needs no secrets
        )

        assert resp.status_code == 503, (
            "ScreenshotBackendError must map to 503 backend_unavailable, "
            f"got {resp.status_code}: {resp.get_data(as_text=True)}"
        )
        body = resp.get_json()
        assert body["success"] is False
        assert body["code"] == "backend_unavailable"
        # The response body must come from the module-level constant
        # ``SCREENSHOT_BACKEND_UNAVAILABLE_MSG`` rather than ``str(exc)`` —
        # this is what clears CodeQL's ``py/stack-trace-exposure`` rule.
        # Mirrors the URLValidationError.safe_message() pattern (JTN-776).
        from utils.plugin_errors import SCREENSHOT_BACKEND_UNAVAILABLE_MSG

        assert body["error"] == SCREENSHOT_BACKEND_UNAVAILABLE_MSG
        assert body["error"] != "An internal error occurred"


class TestUpdateNowScreenshotBackendViaRefreshTask:
    """/update_now's *outer* except block (the async refresh-task path)
    must also map ``ScreenshotBackendError`` to HTTP 503.

    The test above covers the ``_update_now_direct`` in-process path. This
    one covers the alternate path where ``refresh_task.running`` is True and
    ``manual_update`` re-raises ``ScreenshotBackendError`` from the
    subprocess worker (preserved via ``_remote_exception`` since JTN-789
    added it to the allow-list).
    """

    def test_screenshot_backend_error_from_refresh_task_returns_503(
        self, client, flask_app, monkeypatch
    ):
        from utils.plugin_errors import (
            SCREENSHOT_BACKEND_UNAVAILABLE_MSG,
            ScreenshotBackendError,
        )

        # Force the outer path: refresh_task.running=True + manual_update raises.
        refresh_task = flask_app.config["REFRESH_TASK"]
        monkeypatch.setattr(refresh_task, "running", True)

        def _raise(_refresh_action):
            raise ScreenshotBackendError(
                "Screenshot backend failed after retry: chromium subprocess "
                "did not produce an image."
            )

        monkeypatch.setattr(refresh_task, "manual_update", _raise)

        resp = client.post("/update_now", data={"plugin_id": "clock"})
        assert resp.status_code == 503, (
            "outer refresh-task path must map ScreenshotBackendError to 503, "
            f"got {resp.status_code}: {resp.get_data(as_text=True)}"
        )
        body = resp.get_json()
        assert body["code"] == "backend_unavailable"
        assert body["error"] == SCREENSHOT_BACKEND_UNAVAILABLE_MSG
