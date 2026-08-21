"""Screenshot render wait and blank detection (upstream fatihak#683).

Headless Chrome captures as soon as load fires, which is too early for pages
that paint from JavaScript — they screenshot blank or half-built. Two settings
address that: give the page virtual time to finish, and decline to push a frame
that still came back empty.
"""

from __future__ import annotations

import sys
from typing import Any

import pytest
from PIL import Image

import utils.image_utils as image_utils
from plugins.screenshot.screenshot import Screenshot


class TestRenderWaitParsing:
    @pytest.mark.parametrize("raw", [None, "", "abc", "0", "-1", 0, -5])
    def test_absent_or_junk_means_no_wait(self, raw: Any) -> None:
        """A bad value must not fail the render; it just means "no wait"."""
        assert Screenshot._render_wait_ms({"renderWaitMs": raw}) is None

    def test_missing_key_means_no_wait(self) -> None:
        assert Screenshot._render_wait_ms({}) is None

    @pytest.mark.parametrize(
        ("raw", "expected"), [("2000", 2000), (1500, 1500), ("1500.7", 1500)]
    )
    def test_valid_values_are_parsed(self, raw: Any, expected: Any) -> None:
        assert Screenshot._render_wait_ms({"renderWaitMs": raw}) == expected

    def test_absurd_values_are_capped(self) -> None:
        """An unbounded budget lets a runaway timer hold the subprocess open."""
        assert Screenshot._render_wait_ms({"renderWaitMs": "999999999"}) == 30_000


class TestBrowserCommandCarriesTheWait:
    def _command(self, render_wait_ms: Any) -> Any:
        return image_utils._find_browser_command(
            "http://example.com",
            "/tmp/out.png",
            (800, 480),
            40000,
            render_wait_ms,
        )

    @pytest.fixture(autouse=True)
    def _fake_browser(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Pretend the first candidate browser exists so a command is built.
        monkeypatch.setattr(image_utils.shutil, "which", lambda _n: sys.executable)

    def test_wait_becomes_a_virtual_time_budget(self) -> None:
        command = self._command(2500)
        assert command is not None
        assert "--virtual-time-budget=2500" in command

    def test_no_flag_when_no_wait_requested(self) -> None:
        command = self._command(None)
        assert command is not None
        assert not any(arg.startswith("--virtual-time-budget") for arg in command)

    def test_flag_is_omitted_for_zero(self) -> None:
        command = self._command(0)
        assert command is not None
        assert not any(arg.startswith("--virtual-time-budget") for arg in command)


class TestBlankDetection:
    def test_flat_image_is_blank(self) -> None:
        assert Screenshot._is_blank(Image.new("RGB", (40, 30), "white")) is True
        assert Screenshot._is_blank(Image.new("RGB", (40, 30), "black")) is True

    def test_image_with_content_is_not_blank(self) -> None:
        image = Image.new("RGB", (40, 30), "white")
        image.putpixel((5, 5), (0, 0, 0))
        assert Screenshot._is_blank(image) is False

    def test_photographic_image_is_not_blank(self) -> None:
        """Many colours must short-circuit cheaply rather than scanning it all."""
        image = Image.new("RGB", (40, 30))
        for x in range(40):
            for y in range(30):
                image.putpixel((x, y), (x * 6 % 256, y * 8 % 256, (x + y) % 256))
        assert Screenshot._is_blank(image) is False


class TestSkipIfBlankBehaviour:
    def _generate(
        self, monkeypatch: pytest.MonkeyPatch, *, captured: Any, settings: Any
    ) -> Any:
        monkeypatch.setattr(
            "plugins.screenshot.screenshot.take_screenshot",
            lambda *_a, **_kw: captured,
        )

        class FakeDeviceConfig:
            def get_resolution(self) -> Any:
                return (40, 30)

            def get_config(self, _key: Any, default: Any = None) -> Any:
                return default

        plugin = Screenshot({"id": "screenshot"})
        return plugin, plugin.generate_image(
            {"url": "http://example.com", **settings}, FakeDeviceConfig()
        )

    def test_blank_capture_returns_none_when_enabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """None leaves the display on its previous content — the desired outcome."""
        blank = Image.new("RGB", (40, 30), "white")
        plugin, result = self._generate(
            monkeypatch, captured=blank, settings={"skipIfBlank": "true"}
        )
        assert result is None
        meta = plugin.get_latest_metadata()
        assert meta, "the plugin reported no metadata at all"
        assert meta.get("skipped") is True
        assert "blank" in str(meta.get("reason")).lower()

    def test_blank_capture_is_still_displayed_when_disabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Opt-in only — existing instances must be unaffected."""
        blank = Image.new("RGB", (40, 30), "white")
        _plugin, result = self._generate(
            monkeypatch, captured=blank, settings={"skipIfBlank": "false"}
        )
        assert result is blank

    def test_default_is_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        blank = Image.new("RGB", (40, 30), "white")
        _plugin, result = self._generate(monkeypatch, captured=blank, settings={})
        assert result is blank

    def test_non_blank_capture_is_displayed_with_the_setting_on(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        image = Image.new("RGB", (40, 30), "white")
        image.putpixel((1, 1), (255, 0, 0))
        _plugin, result = self._generate(
            monkeypatch, captured=image, settings={"skipIfBlank": "true"}
        )
        assert result is image

    def test_failed_capture_still_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A missing image is an error, distinct from a blank one."""
        with pytest.raises(RuntimeError):
            self._generate(monkeypatch, captured=None, settings={"skipIfBlank": "true"})

    def test_render_wait_is_passed_to_the_backend(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> Any:
        seen = {}

        def fake_take_screenshot(*_args: Any, **kwargs: Any) -> Any:
            seen.update(kwargs)
            return Image.new("RGB", (40, 30), "white")

        monkeypatch.setattr(
            "plugins.screenshot.screenshot.take_screenshot", fake_take_screenshot
        )

        class FakeDeviceConfig:
            def get_resolution(self) -> Any:
                return (40, 30)

            def get_config(self, _key: Any, default: Any = None) -> Any:
                return default

        Screenshot({"id": "screenshot"}).generate_image(
            {"url": "http://example.com", "renderWaitMs": "3000"}, FakeDeviceConfig()
        )
        assert seen.get("render_wait_ms") == 3000


class TestRenderWaitRejectsOverflow:
    """`int(float("1e999"))` raises OverflowError, not ValueError.

    The original guard caught only (TypeError, ValueError), so a junk setting
    escaped as an unhandled exception and failed the whole render instead of
    being ignored. Reported by CodeRabbit on PR #632.
    """

    @pytest.mark.parametrize("raw", ["1e999", "inf", "-inf", "Infinity"])
    def test_overflow_values_are_ignored_not_raised(self, raw: str) -> None:
        assert Screenshot._render_wait_ms({"renderWaitMs": raw}) is None
