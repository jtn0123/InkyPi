"""Background-colour resolution across image modes (JTN-768, upstream #568).

A colour resolved in ``RGB`` cannot be composited into an ``L`` (grayscale) or
``1`` (bi-level) image, and the failure surfaces inside ``ImageOps.pad`` rather
than anywhere that mentions colour.  Grayscale and bi-colour Waveshare panels
are exactly the configurations our fork supports, so these paths need cover.
"""

import pytest
from PIL import Image, ImageOps

from utils.image_utils import resolve_background_color

# Modes a plugin can plausibly be asked to pad: colour, grayscale, bi-level.
PAD_MODES = ["RGB", "RGBA", "L", "1"]


class TestResolveBackgroundColor:
    @pytest.mark.parametrize("mode", PAD_MODES)
    def test_named_color_resolves_for_every_mode(self, mode):
        assert resolve_background_color("white", mode) is not None

    @pytest.mark.parametrize("mode", PAD_MODES)
    def test_hex_color_resolves_for_every_mode(self, mode):
        assert resolve_background_color("#336699", mode) is not None

    @pytest.mark.parametrize("mode", PAD_MODES)
    def test_unset_falls_back_to_white(self, mode):
        assert resolve_background_color(None, mode) == resolve_background_color(
            "#ffffff", mode
        )
        assert resolve_background_color("", mode) == resolve_background_color(
            "#ffffff", mode
        )

    @pytest.mark.parametrize("mode", PAD_MODES)
    def test_malformed_color_falls_back_instead_of_raising(self, mode):
        # The value comes from a free-text settings field, so garbage is a
        # normal input, not an exceptional one.
        assert resolve_background_color("not-a-color", mode) == (
            resolve_background_color("#ffffff", mode)
        )

    @pytest.mark.parametrize("mode", PAD_MODES)
    def test_non_string_setting_is_treated_as_unset(self, mode):
        # Older settings shapes stored tuples; upstream #568 crashed on these.
        assert resolve_background_color((255, 255, 255), mode) == (
            resolve_background_color("#ffffff", mode)
        )

    def test_grayscale_returns_an_int_not_a_tuple(self):
        # An RGB tuple here is precisely what breaks ImageOps.pad on L images.
        assert isinstance(resolve_background_color("white", "L"), int)
        assert isinstance(resolve_background_color("white", "RGB"), tuple)

    @pytest.mark.parametrize("mode", PAD_MODES)
    @pytest.mark.parametrize("color", ["white", "#336699", None, "not-a-color"])
    def test_result_is_actually_paddable(self, mode, color):
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
    def test_plugin_imports_the_shared_helper(self, module_path):
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
    def test_plugin_no_longer_defines_a_private_copy(self, module_path):
        import importlib

        module = importlib.import_module(module_path)
        assert not hasattr(
            module, "_resolve_background_color"
        ), f"{module_path} still defines a private background-color helper"
