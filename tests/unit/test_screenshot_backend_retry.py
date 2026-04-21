"""JTN-789: chromium screenshot retry + typed ``ScreenshotBackendError``.

On Pi Zero 2 W the chromium subprocess intermittently times out or exits
without producing output when the device is under memory pressure.  A
single retry with a short backoff absorbs ~all of those transient failures
without changing the error model for deterministic issues (no browser
installed, URL validation failure).

When both attempts still fail, :func:`utils.image_utils.take_screenshot`
must raise :class:`utils.plugin_errors.ScreenshotBackendError` so the
blueprint layer can translate it into an actionable HTTP 503
``backend_unavailable`` instead of the generic 500 ``internal_error`` a
bare ``None`` return would bubble up as.
"""

from __future__ import annotations

import pytest
from PIL import Image

import utils.image_utils as image_utils
from utils.plugin_errors import ScreenshotBackendError

# Capture the real ``take_screenshot`` at module-import time, *before* the
# conftest autouse ``mock_screenshot`` fixture runs and replaces it with a
# stub that returns a white image.  The fixture below rebinds this real
# implementation inside each test so we can observe the retry orchestrator.
_REAL_TAKE_SCREENSHOT = image_utils.take_screenshot


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_img() -> Image.Image:
    return Image.new("RGB", (80, 60), "white")


class _AttemptRecorder:
    """Records (target, dimensions, timeout_ms, attempt) for each invocation."""

    def __init__(self, outcomes):
        # outcomes is a list of (image, transient) tuples returned in order.
        self._outcomes = list(outcomes)
        self.calls: list[tuple] = []

    def __call__(self, target, dimensions, timeout_ms, attempt):
        self.calls.append((target, dimensions, timeout_ms, attempt))
        try:
            return self._outcomes.pop(0)
        except IndexError:  # pragma: no cover - defensive
            raise AssertionError(
                "take_screenshot called more times than outcomes provided"
            ) from None


@pytest.fixture(autouse=True)
def _restore_real_take_screenshot(monkeypatch):
    """Undo the global ``mock_screenshot`` conftest patch for these tests.

    The top-level conftest autouse ``mock_screenshot`` fixture replaces
    ``utils.image_utils.take_screenshot`` with a stub that returns a white
    image — great for the rest of the suite, but it means patching
    ``_take_screenshot_once`` in these retry-loop tests has no effect
    because the orchestrator is already gone.  We re-bind the real
    implementation here (import ordering guarantees the module attribute
    exists) so we can actually observe the retry loop.
    """
    monkeypatch.setattr(
        image_utils, "take_screenshot", _REAL_TAKE_SCREENSHOT, raising=True
    )
    # Collapse the inter-attempt backoff so the tests run fast.
    monkeypatch.setattr(image_utils.time, "sleep", lambda _s: None)


# ---------------------------------------------------------------------------
# Retry behaviour
# ---------------------------------------------------------------------------


class TestTakeScreenshotRetry:
    """``take_screenshot`` must retry exactly once on transient failure."""

    def test_success_first_attempt_no_retry(self, monkeypatch):
        """Image returned on the first call -> exactly one attempt, no sleep."""
        img = _make_img()
        rec = _AttemptRecorder([(img, False)])
        monkeypatch.setattr(image_utils, "_take_screenshot_once", rec)

        slept: list[float] = []
        monkeypatch.setattr(image_utils.time, "sleep", lambda s: slept.append(s))

        result = image_utils.take_screenshot("http://example.com", (80, 60))

        assert result is img
        assert len(rec.calls) == 1, "should not retry when first attempt succeeds"
        # attempt index passed through is 1-based for journalctl readability
        assert rec.calls[0][3] == 1
        assert slept == [], "no backoff should run when first attempt succeeds"

    def test_transient_none_then_image_returns_image(self, monkeypatch):
        """None+transient on attempt 1, image on attempt 2 -> image, exactly 2 calls."""
        img = _make_img()
        rec = _AttemptRecorder(
            [
                (None, True),  # transient flake (e.g. TimeoutExpired)
                (img, False),  # retry succeeds
            ]
        )
        monkeypatch.setattr(image_utils, "_take_screenshot_once", rec)

        result = image_utils.take_screenshot(
            "http://example.com", (80, 60), timeout_ms=5000
        )

        assert result is img
        assert len(rec.calls) == 2
        assert [c[3] for c in rec.calls] == [1, 2]

    def test_transient_none_both_attempts_raises(self, monkeypatch):
        """Transient None twice -> ScreenshotBackendError, exactly 2 calls."""
        rec = _AttemptRecorder([(None, True), (None, True)])
        monkeypatch.setattr(image_utils, "_take_screenshot_once", rec)

        with pytest.raises(ScreenshotBackendError) as excinfo:
            image_utils.take_screenshot("http://example.com", (80, 60))

        assert len(rec.calls) == 2, "must retry exactly once, not more"
        # The exception message must be a stable, user-facing string — not
        # a stringified traceback or env-dependent text.
        assert "retry" in str(excinfo.value).lower()

    def test_deterministic_failure_does_not_retry(self, monkeypatch):
        """``transient=False`` short-circuits the retry loop after one attempt."""
        rec = _AttemptRecorder([(None, False)])  # e.g. no browser installed
        monkeypatch.setattr(image_utils, "_take_screenshot_once", rec)

        result = image_utils.take_screenshot("http://example.com", (80, 60))

        assert result is None, (
            "deterministic failure must surface as None, not raise — existing "
            "callers (base_plugin fallback image path) rely on this shape."
        )
        assert len(rec.calls) == 1, (
            "deterministic failures must NOT retry; the missing browser "
            "won't magically appear 500ms later."
        )

    def test_retry_uses_short_bounded_backoff(self, monkeypatch):
        """Exactly one sleep, and its duration is the documented constant."""
        rec = _AttemptRecorder([(None, True), (_make_img(), False)])
        monkeypatch.setattr(image_utils, "_take_screenshot_once", rec)

        slept: list[float] = []
        monkeypatch.setattr(image_utils.time, "sleep", lambda s: slept.append(s))

        image_utils.take_screenshot("http://example.com", (80, 60))

        assert slept == [image_utils._SCREENSHOT_RETRY_BACKOFF_S]
        # Hard upper bound — we never want a long blocking sleep on a Pi.
        assert image_utils._SCREENSHOT_RETRY_BACKOFF_S <= 1.0


# ---------------------------------------------------------------------------
# Cross-subprocess type preservation
# ---------------------------------------------------------------------------


class TestWorkerRemoteExceptionAllowlist:
    """The subprocess worker must round-trip ``ScreenshotBackendError`` by name.

    Without this, a chromium flake inside the plugin subprocess would arrive
    at the parent as a bare ``RuntimeError`` and the blueprint would wrap it
    as HTTP 500, defeating the whole purpose of the new typed error.
    """

    def test_remote_exception_reconstructs_screenshot_backend_error(self):
        from refresh_task.worker import _remote_exception

        exc = _remote_exception(
            "ScreenshotBackendError",
            "Screenshot backend failed after retry: chromium subprocess "
            "did not produce an image.",
        )
        assert isinstance(exc, ScreenshotBackendError)
        # Subclass contract — existing ``except RuntimeError`` handlers
        # (e.g. plugin blueprint fallback from JTN-776) must still catch it.
        assert isinstance(exc, RuntimeError)
        assert "Screenshot backend" in str(exc)

    def test_remote_exception_unknown_type_still_falls_back_to_runtime(self):
        """Regression guard: the new allow-list entry must not change the default."""
        from refresh_task.worker import _remote_exception

        exc = _remote_exception("TotallyUnknownError", "boom")
        assert type(exc) is RuntimeError


class TestRunSingleAttemptTransientDetection:
    """JTN-789 regression: non-zero chromium exits must be classified correctly.

    The tempfile pre-created by ``_take_screenshot_once`` exists as a 0-byte
    placeholder before chromium runs, so ``os.path.exists`` alone cannot
    distinguish "chromium died without producing bytes" (transient — worth a
    retry) from "chromium emitted a real error page" (deterministic). The
    implementation uses ``os.path.getsize == 0`` as the signal; these tests
    pin that.
    """

    @staticmethod
    def _run_once_with_fake_subprocess(monkeypatch, returncode, write_bytes):
        """Invoke `_take_screenshot_once` with a patched subprocess.run whose
        side effect writes *write_bytes* to the output tempfile and returns
        *returncode*. Returns the ``(image, transient)`` tuple under test."""
        import subprocess
        import sys
        from types import SimpleNamespace

        from utils import image_utils as iu

        monkeypatch.setattr(
            iu,
            "_find_browser_command",
            lambda target, out, dims, timeout_ms: [sys.executable, "-c", "pass", out],
        )

        real_run = subprocess.run

        def fake_run(command, **kwargs):
            # command[-1] is the tempfile path the wrapper injected.
            out = command[-1]
            with open(out, "wb") as f:
                f.write(write_bytes)
            return SimpleNamespace(returncode=returncode, stderr=b"", stdout=b"")

        monkeypatch.setattr(iu.subprocess, "run", fake_run)
        try:
            return iu._take_screenshot_once(
                target="http://example.invalid",
                dimensions=(800, 480),
                timeout_ms=5_000,
                attempt=1,
            )
        finally:
            monkeypatch.setattr(iu.subprocess, "run", real_run)

    def test_nonzero_exit_empty_file_is_transient(self, monkeypatch):
        """Chromium OOM-exit with no PNG bytes should retry."""
        image, transient = self._run_once_with_fake_subprocess(
            monkeypatch, returncode=1, write_bytes=b""
        )
        assert image is None
        assert transient is True

    def test_nonzero_exit_nonempty_file_is_deterministic(self, monkeypatch):
        """Chromium exit with some bytes on disk is NOT a memory-pressure flake."""
        image, transient = self._run_once_with_fake_subprocess(
            monkeypatch, returncode=2, write_bytes=b"<not a valid png>"
        )
        assert image is None
        assert transient is False


class TestTakeScreenshotOnceBranchCoverage:
    """JTN-789 + SonarCloud ``new_coverage``: exercise every branch of
    ``_take_screenshot_once`` directly, so the quality gate clears 80% on the
    PR diff. The retry orchestrator above (``TestTakeScreenshotRetry``) uses
    injected outcomes; this suite drives the real helper.
    """

    def _base_patches(self, monkeypatch):
        """Install the minimal monkeypatches to call ``_take_screenshot_once``
        without invoking a real browser. Returns the module under test."""
        import sys

        from utils import image_utils as iu

        monkeypatch.setattr(
            iu,
            "_find_browser_command",
            lambda target, out, dims, timeout_ms: [sys.executable, "-c", "pass", out],
        )
        return iu

    def test_missing_browser_returns_deterministic(self, monkeypatch):
        """No browser on the system is deterministic — don't retry."""
        from utils import image_utils as iu

        monkeypatch.setattr(iu, "_find_browser_command", lambda *a, **kw: None)
        image, transient = iu._take_screenshot_once(
            "http://example.invalid", (800, 480), None, attempt=1
        )
        assert image is None
        assert transient is False

    def test_timeout_expired_is_transient(self, monkeypatch):
        """subprocess.TimeoutExpired should retry."""
        import subprocess

        iu = self._base_patches(monkeypatch)

        def fake_run(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd="chromium", timeout=1)

        monkeypatch.setattr(iu.subprocess, "run", fake_run)
        image, transient = iu._take_screenshot_once(
            "http://example.invalid", (800, 480), None, attempt=1
        )
        assert image is None
        assert transient is True

    def test_file_not_found_is_deterministic(self, monkeypatch):
        """FileNotFoundError on subprocess.run = binary vanished between
        probe and invocation, deterministic (don't retry)."""
        iu = self._base_patches(monkeypatch)

        def fake_run(*args, **kwargs):
            raise FileNotFoundError("browser")

        monkeypatch.setattr(iu.subprocess, "run", fake_run)
        image, transient = iu._take_screenshot_once(
            "http://example.invalid", (800, 480), None, attempt=1
        )
        assert image is None
        assert transient is False

    def test_zero_exit_empty_file_is_transient(self, monkeypatch):
        """Clean exit but no PNG bytes — retry."""
        from types import SimpleNamespace

        iu = self._base_patches(monkeypatch)

        def fake_run(command, **kwargs):
            # leave tempfile empty
            return SimpleNamespace(returncode=0, stderr=b"", stdout=b"")

        monkeypatch.setattr(iu.subprocess, "run", fake_run)
        image, transient = iu._take_screenshot_once(
            "http://example.invalid", (800, 480), None, attempt=1
        )
        assert image is None
        assert transient is True

    def test_loader_returns_none_is_transient(self, monkeypatch):
        """Chromium succeeded, wrote bytes, but PIL can't decode — retry
        once because PNG decode is deterministic in theory, but real-world
        tempfile races can leave incomplete data."""
        from types import SimpleNamespace

        iu = self._base_patches(monkeypatch)

        def fake_run(command, **kwargs):
            out = command[-1]
            with open(out, "wb") as f:
                f.write(b"some bytes")
            return SimpleNamespace(returncode=0, stderr=b"", stdout=b"")

        monkeypatch.setattr(iu.subprocess, "run", fake_run)
        monkeypatch.setattr(iu, "load_image_from_path", lambda p: None)
        image, transient = iu._take_screenshot_once(
            "http://example.invalid", (800, 480), None, attempt=1
        )
        assert image is None
        assert transient is True

    def test_unexpected_exception_is_transient(self, monkeypatch):
        """Any unexpected exception inside the happy path is treated as
        transient so we at least retry once before surfacing."""
        from types import SimpleNamespace

        iu = self._base_patches(monkeypatch)

        def fake_run(command, **kwargs):
            out = command[-1]
            with open(out, "wb") as f:
                f.write(b"some bytes")
            return SimpleNamespace(returncode=0, stderr=b"", stdout=b"")

        def boom(_path):
            raise RuntimeError("decoder exploded")

        monkeypatch.setattr(iu.subprocess, "run", fake_run)
        monkeypatch.setattr(iu, "load_image_from_path", boom)
        image, transient = iu._take_screenshot_once(
            "http://example.invalid", (800, 480), None, attempt=1
        )
        assert image is None
        assert transient is True


class TestTempfileIsEmpty:
    """Direct unit tests for the tempfile-empty helper."""

    def test_none_path_is_empty(self):
        from utils.image_utils import _tempfile_is_empty

        assert _tempfile_is_empty(None) is True

    def test_missing_file_is_empty(self, tmp_path):
        from utils.image_utils import _tempfile_is_empty

        assert _tempfile_is_empty(str(tmp_path / "nonexistent.png")) is True

    def test_zero_byte_file_is_empty(self, tmp_path):
        from utils.image_utils import _tempfile_is_empty

        p = tmp_path / "empty.png"
        p.write_bytes(b"")
        assert _tempfile_is_empty(str(p)) is True

    def test_nonempty_file_is_not_empty(self, tmp_path):
        from utils.image_utils import _tempfile_is_empty

        p = tmp_path / "content.png"
        p.write_bytes(b"chromium-output")
        assert _tempfile_is_empty(str(p)) is False

    def test_oserror_treated_as_empty(self, monkeypatch, tmp_path):
        """If getsize raises (e.g. permissions), err on the side of transient."""
        from utils import image_utils as iu

        def raise_os(_path):
            raise OSError("fake permission error")

        monkeypatch.setattr(iu.os.path, "getsize", raise_os)
        p = tmp_path / "content.png"
        p.write_bytes(b"anything")
        assert iu._tempfile_is_empty(str(p)) is True
