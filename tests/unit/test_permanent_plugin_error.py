"""Retry-policy tests for ``PermanentPluginError`` (JTN-778).

A plugin raising :class:`utils.plugin_errors.PermanentPluginError` must be
treated as a terminal failure by both the subprocess and in-process retry
loops — the error will never succeed on retry, so retrying only wastes
CPU cycles and log lines on every scheduled playlist tick.

Transient errors (``RuntimeError``, ``ConnectionError``, ``TimeoutError``)
must still honour ``INKYPI_PLUGIN_RETRY_MAX`` so intermittent network
hiccups continue to be papered over as before.
"""

import os
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from PIL import Image

from refresh_task import RefreshTask
from utils.plugin_errors import PermanentPluginError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_task(device_config_dev):
    dm = MagicMock()
    return RefreshTask(device_config_dev, dm)


def _fake_action(plugin_id: str = "image_url"):
    action = MagicMock()
    action.get_plugin_id.return_value = plugin_id
    return action


class _CountingPlugin:
    """Plugin that records how many times ``generate_image`` was called."""

    config = {"image_settings": []}

    def __init__(self, exc: BaseException):
        self.exc = exc
        self.calls = 0

    def generate_image(self, settings, cfg):
        self.calls += 1
        raise self.exc


class _EventuallySucceedingPlugin:
    """Fails with a transient error on the first call, succeeds on the second."""

    config = {"image_settings": []}

    def __init__(self, transient_exc: BaseException):
        self.transient_exc = transient_exc
        self.calls = 0

    def generate_image(self, settings, cfg):
        self.calls += 1
        if self.calls == 1:
            raise self.transient_exc
        return Image.new("RGB", (10, 10), "green")


# ---------------------------------------------------------------------------
# In-process path — direct and easiest to observe
# ---------------------------------------------------------------------------


class TestPermanentPluginErrorInProcess:
    """``_execute_inprocess`` must not retry ``PermanentPluginError``."""

    def test_permanent_error_runs_exactly_one_attempt(self, device_config_dev, caplog):
        """An ``Invalid URL`` failure must not trigger any retries."""
        task = _make_task(device_config_dev)
        action = _fake_action()
        plugin = _CountingPlugin(
            PermanentPluginError(
                "Invalid URL: URL must not resolve to a private, loopback, "
                "link-local, reserved, or multicast address"
            )
        )
        # Mirror the real subprocess-less execute(): just invoke the plugin.
        action.execute.side_effect = lambda p, cfg, dt: p.generate_image(None, cfg)

        caplog.set_level("INFO")

        with (
            patch("refresh_task.task.get_plugin_instance", return_value=plugin),
            patch.dict(
                os.environ,
                {
                    "INKYPI_PLUGIN_RETRY_MAX": "3",
                    "INKYPI_PLUGIN_RETRY_BACKOFF_MS": "1",
                },
            ),
        ):
            try:
                task._execute_inprocess(action, {"id": "image_url"}, datetime.now(UTC))
            except PermanentPluginError as exc:
                assert "Invalid URL" in str(exc)
            else:  # pragma: no cover
                raise AssertionError("Expected PermanentPluginError to propagate")

        assert plugin.calls == 1, (
            f"Expected exactly one attempt, got {plugin.calls} — "
            "PermanentPluginError should skip retries"
        )
        # The terminal log marker distinguishes this from attempt_retry.
        terminal_logs = [
            r for r in caplog.records if "attempt_terminal" in r.getMessage()
        ]
        assert terminal_logs, "expected an attempt_terminal log record"

    def test_transient_runtime_error_still_retries(self, device_config_dev):
        """A generic ``RuntimeError`` must honour ``INKYPI_PLUGIN_RETRY_MAX``."""
        task = _make_task(device_config_dev)
        action = _fake_action()
        plugin = _EventuallySucceedingPlugin(RuntimeError("transient blip"))
        action.execute.side_effect = lambda p, cfg, dt: p.generate_image(None, cfg)

        with (
            patch("refresh_task.task.get_plugin_instance", return_value=plugin),
            patch.dict(
                os.environ,
                {
                    "INKYPI_PLUGIN_RETRY_MAX": "1",
                    "INKYPI_PLUGIN_RETRY_BACKOFF_MS": "1",
                },
            ),
        ):
            image, _meta = task._execute_inprocess(
                action, {"id": "image_url"}, datetime.now(UTC)
            )

        assert image is not None
        assert plugin.calls == 2, (
            "Transient RuntimeError should have retried and succeeded on the "
            f"second attempt — observed {plugin.calls} call(s)"
        )

    def test_transient_connection_error_still_retries(self, device_config_dev):
        """``ConnectionError`` is the canonical transient failure — must retry."""
        task = _make_task(device_config_dev)
        action = _fake_action()
        plugin = _EventuallySucceedingPlugin(ConnectionError("name resolution failed"))
        action.execute.side_effect = lambda p, cfg, dt: p.generate_image(None, cfg)

        with (
            patch("refresh_task.task.get_plugin_instance", return_value=plugin),
            patch.dict(
                os.environ,
                {
                    "INKYPI_PLUGIN_RETRY_MAX": "1",
                    "INKYPI_PLUGIN_RETRY_BACKOFF_MS": "1",
                },
            ),
        ):
            image, _meta = task._execute_inprocess(
                action, {"id": "image_url"}, datetime.now(UTC)
            )

        assert image is not None
        assert plugin.calls == 2


# ---------------------------------------------------------------------------
# Subprocess / policy path — exercises the _execute_with_policy retry loop
# directly without spawning a child process.
# ---------------------------------------------------------------------------


class TestPermanentPluginErrorPolicy:
    """``_execute_with_policy`` must re-raise ``PermanentPluginError`` after one attempt.

    The autouse ``disable_plugin_process_isolation`` conftest fixture pins
    ``INKYPI_PLUGIN_ISOLATION=none`` so the policy layer delegates to
    ``_execute_inprocess``.  These tests explicitly switch back to the
    subprocess-style code path by setting the env var to ``"process"`` and
    mocking ``_run_subprocess_attempt`` so no real child process is spawned.
    """

    def test_policy_skips_retry_on_permanent_error(self, device_config_dev):
        task = _make_task(device_config_dev)
        action = _fake_action()

        call_counter = {"n": 0}

        def _fake_attempt(
            refresh_action, plugin_config, current_dt, plugin_id, timeout_s, attempt
        ):
            call_counter["n"] += 1
            return None, PermanentPluginError(
                "Invalid URL: scheme must be http or https"
            )

        with (
            patch.object(task, "_run_subprocess_attempt", side_effect=_fake_attempt),
            patch.dict(
                os.environ,
                {
                    "INKYPI_PLUGIN_ISOLATION": "process",
                    "INKYPI_PLUGIN_RETRY_MAX": "3",
                    "INKYPI_PLUGIN_RETRY_BACKOFF_MS": "1",
                },
            ),
        ):
            try:
                task._execute_with_policy(
                    action, {"id": "image_url"}, datetime.now(UTC)
                )
            except PermanentPluginError as exc:
                assert "Invalid URL" in str(exc)
            else:  # pragma: no cover
                raise AssertionError("Expected PermanentPluginError to propagate")

        assert call_counter["n"] == 1, (
            "PermanentPluginError must short-circuit the retry loop after a "
            f"single attempt — got {call_counter['n']}"
        )

    def test_policy_retries_transient_errors(self, device_config_dev):
        task = _make_task(device_config_dev)
        action = _fake_action()

        call_counter = {"n": 0}
        success_image = Image.new("RGB", (10, 10), "blue")

        def _fake_attempt(
            refresh_action, plugin_config, current_dt, plugin_id, timeout_s, attempt
        ):
            call_counter["n"] += 1
            if call_counter["n"] == 1:
                return None, ConnectionError("temporary DNS failure")
            return success_image, None

        with (
            patch.object(task, "_run_subprocess_attempt", side_effect=_fake_attempt),
            patch.dict(
                os.environ,
                {
                    "INKYPI_PLUGIN_ISOLATION": "process",
                    "INKYPI_PLUGIN_RETRY_MAX": "1",
                    "INKYPI_PLUGIN_RETRY_BACKOFF_MS": "1",
                },
            ),
        ):
            image, _meta = task._execute_with_policy(
                action, {"id": "image_url"}, datetime.now(UTC)
            )

        assert image is success_image
        assert call_counter["n"] == 2


# ---------------------------------------------------------------------------
# Exception-type plumbing across subprocess boundary
# ---------------------------------------------------------------------------


class TestRemoteExceptionPreservesPermanentType:
    def test_remote_exception_reconstructs_permanent_plugin_error(self):
        """Worker must round-trip ``PermanentPluginError`` by class name."""
        from refresh_task.worker import _remote_exception

        exc = _remote_exception("PermanentPluginError", "Invalid URL: bad scheme")
        assert isinstance(exc, PermanentPluginError)
        assert isinstance(exc, RuntimeError)  # subclass contract
        assert "Invalid URL" in str(exc)

    def test_remote_exception_unknown_type_falls_back_to_runtime(self):
        from refresh_task.worker import _remote_exception

        exc = _remote_exception("SomeUnknownError", "boom")
        assert type(exc) is RuntimeError
