# pyright: reportMissingImports=false
"""JTN-K4: ``TimeoutError`` from /update_now must become HTTP 504.

When ``refresh_task.manual_update`` exceeds ``INKYPI_PLUGIN_TIMEOUT_S``
(default 60 s), it raises :class:`TimeoutError`.  Prior to this fix,
``TimeoutError`` was not in the blueprint's typed-except chain
(TimeoutError inherits from OSError, *not* RuntimeError, so it fell
through to the generic ``except Exception`` and produced HTTP 500
``internal_error`` — giving operators no signal that the problem was
transient and retryable.

This mirrors the JTN-789 pattern that mapped ``ScreenshotBackendError``
to a typed 503 ``backend_unavailable``.
"""

from __future__ import annotations


class TestUpdateNowTimeoutDirect:
    """/update_now must map ``TimeoutError`` to HTTP 504 on the direct path."""

    def test_timeout_error_returns_504(self, client, monkeypatch):
        """Plugin raising ``TimeoutError`` -> 504 ``manual_update_timeout``."""
        from plugins.plugin_registry import get_plugin_instance as _real_get

        def _boom(plugin_config):
            inst = _real_get(plugin_config)

            def _raise(*a, **kw):
                raise TimeoutError("Plugin 'clock' timed out after 60s")

            inst.generate_image = _raise  # type: ignore[method-assign]
            return inst

        import blueprints.plugin as plugin_bp_mod

        monkeypatch.setattr(plugin_bp_mod, "get_plugin_instance", _boom)

        resp = client.post(
            "/update_now",
            data={"plugin_id": "clock"},  # clock needs no secrets
        )

        assert resp.status_code == 504, (
            "TimeoutError must map to 504 manual_update_timeout, "
            f"got {resp.status_code}: {resp.get_data(as_text=True)}"
        )
        body = resp.get_json()
        assert body["success"] is False
        assert body["code"] == "manual_update_timeout"
        # Response body must come from the module-level
        # ``MANUAL_UPDATE_TIMEOUT_MSG`` constant, not ``str(exc)`` — same
        # py/stack-trace-exposure rationale as JTN-789 +
        # JTN-776 URLValidationError.safe_message.
        from utils.plugin_errors import MANUAL_UPDATE_TIMEOUT_MSG

        assert body["error"] == MANUAL_UPDATE_TIMEOUT_MSG
        assert body["error"] != "An internal error occurred"


class TestUpdateNowTimeoutViaRefreshTask:
    """/update_now's *outer* except block (async refresh-task path) must
    also map ``TimeoutError`` to HTTP 504.

    Covers the alternate path where ``refresh_task.running`` is True and
    ``manual_update`` re-raises TimeoutError from the subprocess worker
    (preserved via ``_remote_exception`` — already on the allow-list).
    """

    def test_timeout_error_from_refresh_task_returns_504(
        self, client, flask_app, monkeypatch
    ):
        from utils.plugin_errors import MANUAL_UPDATE_TIMEOUT_MSG

        # Force the outer path: refresh_task.running=True + manual_update raises.
        refresh_task = flask_app.config["REFRESH_TASK"]
        monkeypatch.setattr(refresh_task, "running", True)

        def _raise(_refresh_action):
            raise TimeoutError("Plugin 'clock' timed out after 60s")

        monkeypatch.setattr(refresh_task, "manual_update", _raise)

        resp = client.post("/update_now", data={"plugin_id": "clock"})
        assert resp.status_code == 504, (
            "outer refresh-task path must map TimeoutError to 504, "
            f"got {resp.status_code}: {resp.get_data(as_text=True)}"
        )
        body = resp.get_json()
        assert body["code"] == "manual_update_timeout"
        assert body["error"] == MANUAL_UPDATE_TIMEOUT_MSG
