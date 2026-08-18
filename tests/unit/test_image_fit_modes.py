"""Fit modes and the padImage → fitMode migration (upstream fatihak#736).

Three image plugins previously each decided "crop or pad?" from their own copy
of a boolean. Centralising it means they cannot drift, and — more importantly —
the migration from the old setting happens in exactly one place.

The migration is the delicate part: existing instances must keep behaving
byte-for-byte as before. ``auto`` is opt-in and is never reached by migrating
an old setting.
"""

from __future__ import annotations

from typing import Any

import pytest
from PIL import Image

from utils.image_loader import (
    FIT_AUTO,
    FIT_CONTAIN,
    FIT_COVER,
    effective_fit_mode,
    resolve_fit_mode,
)

LANDSCAPE = (800, 480)
PORTRAIT = (480, 800)
SQUARE = (500, 500)


class TestLegacyMigration:
    def test_pad_image_true_becomes_contain(self) -> None:
        assert resolve_fit_mode({"padImage": "true"}) == FIT_CONTAIN

    def test_pad_image_false_becomes_cover(self) -> None:
        assert resolve_fit_mode({"padImage": "false"}) == FIT_COVER

    def test_neither_setting_defaults_to_cover(self) -> None:
        """What an instance with no fit setting has always done."""
        assert resolve_fit_mode({}) == FIT_COVER

    def test_explicit_fit_mode_wins_over_the_legacy_flag(self) -> None:
        settings = {"fitMode": "contain", "padImage": "false"}
        assert resolve_fit_mode(settings) == FIT_CONTAIN

    def test_migration_never_produces_auto(self) -> None:
        """Auto changes what users see, so it must be an explicit choice."""
        for legacy in ("true", "false", True, False, "TRUE", "garbage"):
            assert resolve_fit_mode({"padImage": legacy}) != FIT_AUTO

    @pytest.mark.parametrize("raw", ["cover", "contain", "auto", "  COVER  "])
    def test_valid_fit_modes_are_accepted_case_insensitively(self, raw: Any) -> None:
        assert resolve_fit_mode({"fitMode": raw}) in {FIT_COVER, FIT_CONTAIN, FIT_AUTO}

    def test_unknown_fit_mode_falls_back_to_cover(self) -> None:
        """The value comes from stored JSON an older version may have written."""
        assert resolve_fit_mode({"fitMode": "stretch"}) == FIT_COVER
        assert resolve_fit_mode({"fitMode": 42}) == FIT_COVER

    def test_empty_fit_mode_falls_through_to_the_legacy_flag(self) -> None:
        assert resolve_fit_mode({"fitMode": "", "padImage": "true"}) == FIT_CONTAIN


class TestAutoResolution:
    def test_landscape_image_on_landscape_display_covers(self) -> None:
        assert effective_fit_mode(FIT_AUTO, (1600, 900), LANDSCAPE) == FIT_COVER

    def test_portrait_image_on_landscape_display_contains(self) -> None:
        """A portrait photo keeps its head and feet instead of a letterbox crop."""
        assert effective_fit_mode(FIT_AUTO, (900, 1600), LANDSCAPE) == FIT_CONTAIN

    def test_portrait_image_on_portrait_display_covers(self) -> None:
        assert effective_fit_mode(FIT_AUTO, (900, 1600), PORTRAIT) == FIT_COVER

    def test_landscape_image_on_portrait_display_contains(self) -> None:
        assert effective_fit_mode(FIT_AUTO, (1600, 900), PORTRAIT) == FIT_CONTAIN

    def test_square_image_counts_as_landscape(self) -> None:
        """A square is treated as landscape, so it fills a landscape panel.

        Cropping a square to a landscape panel loses only top and bottom, which
        is usually what you want; on a portrait panel it pads instead.
        """
        assert effective_fit_mode(FIT_AUTO, SQUARE, LANDSCAPE) == FIT_COVER
        assert effective_fit_mode(FIT_AUTO, SQUARE, PORTRAIT) == FIT_CONTAIN

    @pytest.mark.parametrize("mode", [FIT_COVER, FIT_CONTAIN])
    def test_explicit_modes_pass_through_untouched(self, mode: Any) -> None:
        assert effective_fit_mode(mode, (900, 1600), LANDSCAPE) == mode
        assert effective_fit_mode(mode, (1600, 900), PORTRAIT) == mode


class TestPluginsShareTheResolver:
    @pytest.mark.parametrize(
        "module_path",
        [
            "plugins.image_album.image_album",
            "plugins.image_folder.image_folder",
            "plugins.image_upload.image_upload",
        ],
    )
    def test_plugin_uses_the_central_resolver(self, module_path: Any) -> None:
        import importlib

        module = importlib.import_module(module_path)
        assert hasattr(module, "resolve_fit_mode")
        assert hasattr(module, "effective_fit_mode")

    @pytest.mark.parametrize(
        "module_path",
        [
            "plugins.image_album.image_album",
            "plugins.image_folder.image_folder",
            "plugins.image_upload.image_upload",
        ],
    )
    def test_plugin_offers_the_fit_mode_setting(self, module_path: Any) -> None:
        import importlib
        import json

        module = importlib.import_module(module_path)
        plugin_id = module_path.split(".")[-1]
        plugin_class = next(
            value
            for name, value in vars(module).items()
            if isinstance(value, type)
            and name.lower() == plugin_id.replace("_", "")
            and hasattr(value, "build_settings_schema")
        )
        rendered = json.dumps(plugin_class({"id": plugin_id}).build_settings_schema())
        assert "fitMode" in rendered
        for expected in ("cover", "contain", "auto"):
            assert expected in rendered


class TestUploadRenderRespectsFitMode:
    """End-to-end on the one plugin that pads without a loader round-trip."""

    def _render(self, settings: Any, image_size: Any) -> Any:
        from plugins.image_upload.image_upload import ImageUpload

        source = Image.new("RGB", image_size, "red")

        class FakeDeviceConfig:
            def get_resolution(self) -> Any:
                return LANDSCAPE

            def get_config(self, key: Any, default: Any = None) -> Any:
                return default

        plugin = ImageUpload({"id": "image_upload"})
        plugin.open_image = lambda _i, _locs: source  # type: ignore[method-assign]
        return plugin.generate_image(
            {"imageFiles[]": ["a.png"], **settings}, FakeDeviceConfig()
        )

    def test_legacy_pad_true_still_pads(self) -> None:
        result = self._render({"padImage": "true"}, (400, 400))
        assert result.size == LANDSCAPE

    def test_legacy_pad_false_still_returns_the_source(self) -> None:
        """Cover previously left the loader to resize; behaviour is unchanged."""
        result = self._render({"padImage": "false"}, (400, 400))
        assert result.size == (400, 400)

    def test_auto_pads_a_portrait_image_on_a_landscape_display(self) -> None:
        result = self._render({"fitMode": "auto"}, (300, 900))
        assert result.size == LANDSCAPE

    def test_auto_leaves_a_landscape_image_to_the_cover_path(self) -> None:
        result = self._render({"fitMode": "auto"}, (1600, 900))
        assert result.size == (1600, 900)
