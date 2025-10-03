import os

import pytest


def test_generate_settings_template_defaults(monkeypatch):
    # Import within test to pick up runtime code changes
    from plugins.base_plugin.base_plugin import BasePlugin

    # Plugin without its own settings.html should fall back to base template
    p = BasePlugin({"id": "ai_text"})
    template = p.generate_settings_template()

    assert template["settings_template"] == "ai_text/settings.html" or template[
        "settings_template"
    ] == "base_plugin/settings.html"
    # Always include frame styles
    assert "frame_styles" in template
    assert isinstance(template["frame_styles"], list)


def test_render_image_with_base_template(monkeypatch, tmp_path):
    # This test verifies that render_image works even if the plugin has no custom render dir
    # by relying on the autouse fixture that patches take_screenshot_html to a fake image.
    from plugins.base_plugin.base_plugin import BasePlugin

    # Create a minimal fake plugin id with no render/ directory
    fake_plugin_id = "__fake__"

    # Ensure the fake plugin dir exists without render/
    plugins_root = os.path.join(os.path.dirname(__file__), "..", "..", "src", "plugins")
    plugins_root = os.path.abspath(plugins_root)
    os.makedirs(os.path.join(plugins_root, fake_plugin_id), exist_ok=True)

    p = BasePlugin({"id": fake_plugin_id})

    # Use the base plugin template to render
    out = p.render_image((100, 50), "plugin.html", template_params={"plugin_settings": {}})
    assert out is not None
    assert out.size == (100, 50)


# ---- Metadata hooks tests ----
def test_set_and_get_latest_metadata():
    from plugins.base_plugin.base_plugin import BasePlugin

    p = BasePlugin({"id": "test_plugin"})

    # Initially should be None
    assert p.get_latest_metadata() is None

    # Set metadata
    metadata = {"title": "Test", "date": "2024-01-01"}
    p.set_latest_metadata(metadata)
    assert p.get_latest_metadata() == metadata

    # Set to None
    p.set_latest_metadata(None)
    assert p.get_latest_metadata() is None


def test_set_latest_metadata_empty_dict():
    from plugins.base_plugin.base_plugin import BasePlugin

    p = BasePlugin({"id": "test_plugin"})
    p.set_latest_metadata({})
    # Empty dict should be converted to None
    assert p.get_latest_metadata() is None


def test_get_latest_metadata_never_crashes():
    """Ensure get_latest_metadata never raises even if attribute is corrupted."""
    from plugins.base_plugin.base_plugin import BasePlugin

    p = BasePlugin({"id": "test_plugin"})
    # Even if we manually corrupt the attribute, should return None
    delattr(p, "_latest_metadata") if hasattr(p, "_latest_metadata") else None
    assert p.get_latest_metadata() is None


# ---- URL/path conversion tests ----
def test_to_file_url_with_local_path():
    from plugins.base_plugin.base_plugin import BasePlugin

    p = BasePlugin({"id": "test_plugin"})
    result = p.to_file_url("/path/to/file.png")
    assert result == "file:///path/to/file.png"


def test_to_file_url_with_http_url():
    from plugins.base_plugin.base_plugin import BasePlugin

    p = BasePlugin({"id": "test_plugin"})
    url = "http://example.com/image.png"
    assert p.to_file_url(url) == url


def test_to_file_url_with_https_url():
    from plugins.base_plugin.base_plugin import BasePlugin

    p = BasePlugin({"id": "test_plugin"})
    url = "https://example.com/image.png"
    assert p.to_file_url(url) == url


def test_to_file_url_with_data_uri():
    from plugins.base_plugin.base_plugin import BasePlugin

    p = BasePlugin({"id": "test_plugin"})
    data_uri = "data:image/png;base64,iVBORw0KGgo="
    assert p.to_file_url(data_uri) == data_uri


def test_to_file_url_with_file_url():
    from plugins.base_plugin.base_plugin import BasePlugin

    p = BasePlugin({"id": "test_plugin"})
    file_url = "file:///path/to/file.png"
    assert p.to_file_url(file_url) == file_url


def test_path_to_data_uri_png(tmp_path):
    from plugins.base_plugin.base_plugin import BasePlugin

    p = BasePlugin({"id": "test_plugin"})

    # Create a fake PNG file
    test_file = tmp_path / "test.png"
    test_file.write_bytes(b"\x89PNG\r\n\x1a\n")

    result = p.path_to_data_uri(str(test_file))
    assert result.startswith("data:image/png;base64,")


def test_path_to_data_uri_jpeg(tmp_path):
    from plugins.base_plugin.base_plugin import BasePlugin

    p = BasePlugin({"id": "test_plugin"})

    # Create a fake JPEG file
    test_file = tmp_path / "test.jpg"
    test_file.write_bytes(b"\xff\xd8\xff")

    result = p.path_to_data_uri(str(test_file))
    assert result.startswith("data:image/jpeg;base64,")


def test_path_to_data_uri_gif(tmp_path):
    from plugins.base_plugin.base_plugin import BasePlugin

    p = BasePlugin({"id": "test_plugin"})

    # Create a fake GIF file
    test_file = tmp_path / "test.gif"
    test_file.write_bytes(b"GIF89a")

    result = p.path_to_data_uri(str(test_file))
    assert result.startswith("data:image/gif;base64,")


def test_path_to_data_uri_fallback_on_error():
    from plugins.base_plugin.base_plugin import BasePlugin

    p = BasePlugin({"id": "test_plugin"})

    # Non-existent file should fall back to file:// URL
    result = p.path_to_data_uri("/nonexistent/file.png")
    assert result == "file:///nonexistent/file.png"


# ---- Plugin ID and directory tests ----
def test_get_plugin_id():
    from plugins.base_plugin.base_plugin import BasePlugin

    p = BasePlugin({"id": "weather"})
    assert p.get_plugin_id() == "weather"


def test_get_plugin_dir_no_path():
    from plugins.base_plugin.base_plugin import BasePlugin

    p = BasePlugin({"id": "weather"})
    result = p.get_plugin_dir()
    assert result.endswith("plugins/weather")


def test_get_plugin_dir_with_path():
    from plugins.base_plugin.base_plugin import BasePlugin

    p = BasePlugin({"id": "weather"})
    result = p.get_plugin_dir("render")
    assert result.endswith("plugins/weather/render")


# ---- render_image edge cases ----
def test_render_image_with_extra_css_files():
    from plugins.base_plugin.base_plugin import BasePlugin

    p = BasePlugin({"id": "clock"})

    # Create the extra CSS file in clock's render directory
    render_dir = p.get_plugin_dir("render")
    os.makedirs(render_dir, exist_ok=True)
    extra_css_path = os.path.join(render_dir, "extra.css")
    with open(extra_css_path, "w") as f:
        f.write("/* test extra css */")

    try:
        # Render with extra CSS files parameter
        out = p.render_image(
            (100, 50),
            "plugin.html",
            template_params={"extra_css_files": ["extra.css"], "plugin_settings": {}},
        )
        assert out is not None
        assert out.size == (100, 50)
    finally:
        # Clean up
        if os.path.exists(extra_css_path):
            os.remove(extra_css_path)


def test_render_image_with_extra_css_string(tmp_path):
    from plugins.base_plugin.base_plugin import BasePlugin

    p = BasePlugin({"id": "clock"})

    # Render with extra CSS in plugin_settings
    out = p.render_image(
        (100, 50),
        "plugin.html",
        template_params={
            "plugin_settings": {"extra_css": "body { background: red; }"}
        },
    )
    assert out is not None
    assert out.size == (100, 50)


def test_render_image_screenshot_returns_none(monkeypatch):
    from plugins.base_plugin.base_plugin import BasePlugin

    # Mock screenshot to return None to test fallback
    def mock_screenshot_none(html, dimensions, timeout_ms=None):
        return None

    monkeypatch.setattr(
        "plugins.base_plugin.base_plugin.take_screenshot_html", mock_screenshot_none
    )

    p = BasePlugin({"id": "clock"})

    # Should create fallback white image
    out = p.render_image((100, 50), "plugin.html", template_params={"plugin_settings": {}})
    assert out is not None
    assert out.size == (100, 50)


def test_render_image_with_screenshot_timeout(monkeypatch):
    from plugins.base_plugin.base_plugin import BasePlugin
    from PIL import Image

    # Set environment variable for screenshot timeout
    monkeypatch.setenv("INKYPI_SCREENSHOT_TIMEOUT_MS", "5000")

    captured_timeout = []

    def mock_screenshot_with_timeout(html, dimensions, timeout_ms=None):
        captured_timeout.append(timeout_ms)
        return Image.new("RGB", dimensions, "white")

    monkeypatch.setattr(
        "plugins.base_plugin.base_plugin.take_screenshot_html",
        mock_screenshot_with_timeout,
    )

    p = BasePlugin({"id": "clock"})
    out = p.render_image((100, 50), "plugin.html", template_params={"plugin_settings": {}})

    assert out is not None
    assert captured_timeout[0] == 5000


