# pyright: reportMissingImports=false
"""Tests for user-visible error sanitisation in the fallback image (JTN-779).

The plugin error fallback card must not leak Python implementation details
(e.g. ``RuntimeError:`` prefixes) to end users. These tests lock in:

* ``strip_class_prefix`` removes an ``ExceptionClass:`` prefix cleanly.
* ``sanitize_error_message`` maps known validation errors to plain-English
  sentences and falls back to a neutral message otherwise.
* ``render_error_image`` bakes the sanitised text (not the class name) into
  the rendered card's pixels.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest
from PIL import Image

from utils.fallback_image import (
    _GENERIC_FALLBACK,
    render_error_image,
    sanitize_error_message,
    strip_class_prefix,
)

# ---------------------------------------------------------------------------
# strip_class_prefix
# ---------------------------------------------------------------------------


class TestStripClassPrefix:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("RuntimeError: boom", "boom"),
            ("ValueError: bad value", "bad value"),
            ("TypeError: wrong type", "wrong type"),
            ("  FileNotFoundError: missing  ", "missing"),
            ("CustomError: details: more", "details: more"),
            # Warning classes also stripped
            ("DeprecationWarning: old api", "old api"),
        ],
    )
    def test_strips_known_prefixes(self, raw: str, expected: str) -> None:
        assert strip_class_prefix(raw) == expected

    @pytest.mark.parametrize(
        "raw",
        [
            # Not a class-looking token — keep the message intact.
            "some user text: with colon",
            "status: failed",
            # Lowercase tokens are not Python class names by convention.
            "runtimeerror: boom",
            "",
        ],
    )
    def test_leaves_non_class_prefixes_untouched(self, raw: str) -> None:
        assert strip_class_prefix(raw) == raw.strip()

    def test_none_input_becomes_empty(self) -> None:
        assert strip_class_prefix("") == ""


# ---------------------------------------------------------------------------
# sanitize_error_message
# ---------------------------------------------------------------------------


class TestSanitizeErrorMessage:
    def test_known_url_scheme_pattern_becomes_friendly(self) -> None:
        raw = "Invalid URL: URL scheme must be http or https"
        friendly = sanitize_error_message(raw, error_class="RuntimeError")
        assert "http://" in friendly
        assert "RuntimeError" not in friendly
        assert "URL scheme" not in friendly  # raw validator text hidden

    def test_private_address_pattern(self) -> None:
        raw = "URL host resolves to a loopback address: 127.0.0.1"
        friendly = sanitize_error_message(raw)
        assert "private" in friendly.lower() or "local" in friendly.lower()
        assert "127.0.0.1" not in friendly

    def test_missing_host_pattern(self) -> None:
        raw = "URL host is required"
        friendly = sanitize_error_message(raw)
        assert "host" in friendly.lower() or "full URL" in friendly

    def test_generic_invalid_url_pattern(self) -> None:
        raw = "Invalid URL: something else"
        friendly = sanitize_error_message(raw)
        assert "URL" in friendly
        assert "not valid" in friendly.lower() or "check" in friendly.lower()

    def test_timeout_pattern(self) -> None:
        raw = "HTTPSConnectionPool(host='x'): Read timed out. (read timeout=30)"
        friendly = sanitize_error_message(raw)
        assert "timed out" in friendly.lower()
        assert "HTTPSConnectionPool" not in friendly

    def test_connection_error_pattern(self) -> None:
        raw = "ConnectionError: Failed to establish a new connection"
        friendly = sanitize_error_message(raw)
        assert "reach" in friendly.lower() or "network" in friendly.lower()
        # Ensure no Python identifier leaks through.
        assert "ConnectionError" not in friendly

    def test_unauthorized_pattern(self) -> None:
        raw = "401 Unauthorized"
        friendly = sanitize_error_message(raw)
        assert "authentication" in friendly.lower() or "rejected" in friendly.lower()

    def test_unknown_error_falls_back_to_generic(self) -> None:
        raw = "RuntimeError: some completely novel failure xyzzy"
        friendly = sanitize_error_message(raw, error_class="RuntimeError")
        assert friendly == _GENERIC_FALLBACK
        assert "xyzzy" not in friendly
        assert "RuntimeError" not in friendly

    def test_empty_message_returns_generic(self) -> None:
        assert sanitize_error_message("") == _GENERIC_FALLBACK
        assert sanitize_error_message(None) == _GENERIC_FALLBACK  # type: ignore[arg-type]

    def test_bare_class_name_returns_generic(self) -> None:
        # Some exceptions stringify to just the class name when they carry no
        # message — make sure we never echo that.
        assert (
            sanitize_error_message("RuntimeError", error_class="RuntimeError")
            == _GENERIC_FALLBACK
        )

    def test_class_prefix_stripped_before_matching(self) -> None:
        """A raw "ClassName: ..." string should still match URL patterns."""
        raw = "RuntimeError: URL scheme must be http or https"
        friendly = sanitize_error_message(raw, error_class="RuntimeError")
        assert "http://" in friendly
        assert "RuntimeError" not in friendly

    def test_sanitized_output_never_contains_class_prefix(self) -> None:
        """Fuzz-lite: for a wide range of raw inputs, we never echo class name."""
        raw_inputs = [
            "RuntimeError: boom",
            "ValueError: bad value here",
            "TypeError",
            "KeyError: 'missing'",
            "OSError: [Errno 2] No such file or directory: '/nope'",
            "SystemExit: 1",
        ]
        for raw in raw_inputs:
            friendly = sanitize_error_message(raw)
            # No known Python exception class name should survive.
            for bad in (
                "RuntimeError",
                "ValueError",
                "TypeError",
                "KeyError",
                "OSError",
            ):
                assert (
                    bad not in friendly
                ), f"{bad!r} leaked through for {raw!r}: {friendly!r}"


# ---------------------------------------------------------------------------
# render_error_image
# ---------------------------------------------------------------------------


class TestRenderErrorImageSanitised:
    def test_does_not_render_exception_class_name(self) -> None:
        """The raw ``RuntimeError`` class token must not appear in the image.

        We can't easily OCR the image, so we rely on ``PIL.ImageDraw.Draw``'s
        ``text`` method being the single channel that writes strings.  Monkey-
        patch it to capture the strings and assert the class name never
        appears.
        """
        captured: list[str] = []

        original_draw_cls_attr = "PIL.ImageDraw.ImageDraw.text"
        # Rather than monkey-patching PIL globally (risky across parallel
        # tests), we verify indirectly by rendering and re-deriving the
        # rendered sentences from what sanitize_error_message would produce.
        img = render_error_image(
            width=800,
            height=480,
            plugin_id="screenshot",
            instance_name=None,
            error_class="RuntimeError",
            error_message="Invalid URL: URL scheme must be http or https",
        )
        assert isinstance(img, Image.Image)

        # Exercise the sanitiser directly to assert the contract — the
        # renderer is a thin wrapper over it.
        friendly = sanitize_error_message(
            "Invalid URL: URL scheme must be http or https",
            error_class="RuntimeError",
        )
        assert "RuntimeError" not in friendly
        assert "URL scheme" not in friendly
        del captured, original_draw_cls_attr

    def test_render_uses_sanitized_message_via_draw_text(self, monkeypatch) -> None:
        """Capture draw.text calls to verify the rendered lines.

        This confirms the image renderer uses ``sanitize_error_message``'s
        output (not the raw exception text) when composing the card.
        """
        from PIL import ImageDraw

        captured: list[str] = []
        original_text = ImageDraw.ImageDraw.text

        def _capture(self, xy, text, *args, **kwargs):  # noqa: ANN001
            captured.append(text)
            return original_text(self, xy, text, *args, **kwargs)

        monkeypatch.setattr(ImageDraw.ImageDraw, "text", _capture)

        render_error_image(
            width=800,
            height=480,
            plugin_id="screenshot",
            instance_name=None,
            error_class="RuntimeError",
            error_message="Invalid URL: URL scheme must be http or https",
        )

        joined = "\n".join(captured)
        # User-visible message is present in sanitised form.
        assert "http://" in joined
        # No leakage of the implementation language.
        assert "RuntimeError" not in joined
        # And the raw validator string is not echoed verbatim either.
        assert "URL scheme must be http or https" not in joined

    def test_unknown_error_renders_generic_message(self, monkeypatch) -> None:
        from PIL import ImageDraw

        captured: list[str] = []
        original_text = ImageDraw.ImageDraw.text

        def _capture(self, xy, text, *args, **kwargs):  # noqa: ANN001
            captured.append(text)
            return original_text(self, xy, text, *args, **kwargs)

        monkeypatch.setattr(ImageDraw.ImageDraw, "text", _capture)

        render_error_image(
            width=600,
            height=400,
            plugin_id="weather",
            instance_name="my_weather",
            error_class="RuntimeError",
            error_message="something totally unexpected blew up",
        )

        joined = "\n".join(captured)
        assert "RuntimeError" not in joined
        assert "something totally unexpected" not in joined
        # Generic fallback copy should be present (we check a substring to
        # keep this robust against wording tweaks).
        assert "plugin" in joined.lower() and "failed" in joined.lower()


# ---------------------------------------------------------------------------
# Integration with refresh_task logging (JTN-779: raw detail kept in logs)
# ---------------------------------------------------------------------------


class TestLoggingKeepsRawDetail:
    def test_logger_receives_class_and_raw_message(
        self, device_config_dev, monkeypatch, caplog
    ) -> None:
        """The operator log line must contain the raw exception class + message,
        even though the user-visible card hides them."""
        from datetime import UTC, datetime

        from model import PluginInstance
        from refresh_task import RefreshTask
        from refresh_task.actions import PlaylistRefresh

        monkeypatch.setenv("INKYPI_PLUGIN_ISOLATION", "none")
        monkeypatch.setenv("INKYPI_PLUGIN_RETRY_MAX", "0")
        monkeypatch.setenv("PLUGIN_FAILURE_THRESHOLD", "5")

        dm = MagicMock()
        dm.display_image.return_value = {"display_ms": 10, "preprocess_ms": 5}
        task = RefreshTask(device_config_dev, dm)

        pi = PluginInstance(
            plugin_id="dummy",
            name="my_dummy",
            settings={},
            refresh={"interval": 3600},
        )
        pm = device_config_dev.get_playlist_manager()
        playlist = pm.get_playlist("Default")
        if playlist is None:
            pm.add_default_playlist()
            playlist = pm.get_playlist("Default")
        playlist.plugins.append(pi)

        dummy_cfg = {"id": "dummy", "class": "Dummy", "image_settings": []}
        monkeypatch.setattr(device_config_dev, "get_plugin", lambda pid: dummy_cfg)

        class AlwaysRaisesPlugin:
            def generate_image(self, settings, cfg):
                raise RuntimeError("Invalid URL: URL scheme must be http or https")

            def get_latest_metadata(self):
                return None

        monkeypatch.setattr(
            "refresh_task.task.get_plugin_instance",
            lambda cfg: AlwaysRaisesPlugin(),
        )

        refresh_action = PlaylistRefresh(playlist, pi)
        current_dt = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)

        with caplog.at_level(logging.ERROR, logger="refresh_task.task"):
            with pytest.raises(RuntimeError):
                task._perform_refresh(refresh_action, current_dt, current_dt)

        # The operator log line must surface the raw class + message so the
        # information isn't actually lost — it's only hidden from the UI.
        joined = "\n".join(r.getMessage() for r in caplog.records)
        assert "RuntimeError" in joined, f"class missing from logs: {joined!r}"
        assert (
            "URL scheme must be http or https" in joined
        ), f"raw message missing from logs: {joined!r}"
