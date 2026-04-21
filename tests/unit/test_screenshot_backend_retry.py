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
