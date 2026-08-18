"""Background-colour resolution across image modes (JTN-768, upstream #568).

A colour resolved in ``RGB`` cannot be composited into an ``L`` (grayscale) or
``1`` (bi-level) image, and the failure surfaces inside ``ImageOps.pad`` rather
than anywhere that mentions colour.  Grayscale and bi-colour Waveshare panels
are exactly the configurations our fork supports, so these paths need cover.
"""

from typing import Any

import pytest
from PIL import Image, ImageOps

from utils.image_utils import resolve_background_color

# Modes a plugin can plausibly be asked to pad: colour, grayscale, bi-level.
PAD_MODES = ["RGB", "RGBA", "L", "1"]


class TestResolveBackgroundColor:
    @pytest.mark.parametrize("mode", PAD_MODES)
    def test_named_color_resolves_for_every_mode(self, mode: Any) -> None:
        assert resolve_background_color("white", mode) is not None

    @pytest.mark.parametrize("mode", PAD_MODES)
    def test_hex_color_resolves_for_every_mode(self, mode: Any) -> None:
        assert resolve_background_color("#336699", mode) is not None

    @pytest.mark.parametrize("mode", PAD_MODES)
    def test_unset_falls_back_to_white(self, mode: Any) -> None:
        assert resolve_background_color(None, mode) == resolve_background_color(
            "#ffffff", mode
        )
        assert resolve_background_color("", mode) == resolve_background_color(
            "#ffffff", mode
        )

    @pytest.mark.parametrize("mode", PAD_MODES)
    def test_malformed_color_falls_back_instead_of_raising(self, mode: Any) -> None:
        # The value comes from a free-text settings field, so garbage is a
        # normal input, not an exceptional one.
        assert resolve_background_color("not-a-color", mode) == (
            resolve_background_color("#ffffff", mode)
        )

    @pytest.mark.parametrize("mode", PAD_MODES)
    def test_non_string_setting_is_treated_as_unset(self, mode: Any) -> None:
        # Older settings shapes stored tuples; upstream #568 crashed on these.
        assert resolve_background_color((255, 255, 255), mode) == (
            resolve_background_color("#ffffff", mode)
        )

    def test_grayscale_returns_an_int_not_a_tuple(self) -> None:
        # An RGB tuple here is precisely what breaks ImageOps.pad on L images.
        assert isinstance(resolve_background_color("white", "L"), int)
        assert isinstance(resolve_background_color("white", "RGB"), tuple)

    @pytest.mark.parametrize("mode", PAD_MODES)
    @pytest.mark.parametrize("color", ["white", "#336699", None, "not-a-color"])
    def test_result_is_actually_paddable(self, mode: Any, color: Any) -> None:
        """The real contract: ImageOps.pad must accept what we return."""
        img = Image.new(mode, (4, 3))
        padded = ImageOps.pad(
            img, (8, 6), color=resolve_background_color(color, img.mode)
        )
        assert padded.size == (8, 6)
        assert padded.mode == mode


class TestPluginsUseModeAwareBackgrounds:
    """The three padding plugins must all go through the shared helper.

    They previously carried three separate copies of this logic — two with an
    invalid-input guard and one without — which is how image_album kept the
    ValueError path that the others had already fixed.
    """

    @pytest.mark.parametrize(
        "module_path",
        [
            "plugins.image_album.image_album",
            "plugins.image_folder.image_folder",
            "plugins.image_upload.image_upload",
        ],
    )
    def test_plugin_imports_the_shared_helper(self, module_path: Any) -> None:
        import importlib

        module = importlib.import_module(module_path)
        assert hasattr(
            module, "resolve_background_color"
        ), f"{module_path} should pad via utils.image_utils.resolve_background_color"

    @pytest.mark.parametrize(
        "module_path",
        [
            "plugins.image_album.image_album",
            "plugins.image_folder.image_folder",
            "plugins.image_upload.image_upload",
        ],
    )
    def test_plugin_no_longer_defines_a_private_copy(self, module_path: Any) -> None:
        import importlib

        module = importlib.import_module(module_path)
        assert not hasattr(
            module, "_resolve_background_color"
        ), f"{module_path} still defines a private background-color helper"


class TestUploadPadsInTheImageMode:
    """image_upload resolved its background in RGB regardless of image mode.

    The other two padding plugins already resolved against `img.mode`; this one
    was missed, which is the exact crash the shared helper exists to prevent.
    Reported by CodeRabbit on PR #632.
    """

    @pytest.mark.parametrize("mode", ["L", "1", "RGB"])
    def test_padding_a_non_rgb_upload_does_not_raise(self, mode: str) -> None:
        from plugins.image_upload.image_upload import ImageUpload

        source = Image.new(mode, (40, 40))

        class FakeDeviceConfig:
            def get_resolution(self) -> tuple[int, int]:
                return (80, 60)

            def get_config(self, _key: str, default: Any = None) -> Any:
                return default

        plugin = ImageUpload({"id": "image_upload"})
        plugin.open_image = lambda _i, _locs: source
        result = plugin.generate_image(
            {
                "imageFiles[]": ["a.png"],
                "padImage": "true",
                "backgroundColor": "#336699",
            },
            FakeDeviceConfig(),
        )
        assert result is not None
        assert result.size == (80, 60)
        assert result.mode == mode
