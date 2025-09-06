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


