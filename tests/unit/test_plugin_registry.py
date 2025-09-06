# pyright: reportMissingImports=false
from plugins.plugin_registry import load_plugins, get_plugin_instance, PLUGIN_CLASSES


def test_load_and_get_plugin_instance():
    PLUGIN_CLASSES.clear()
    plugins = [
        {"id": "ai_text", "class": "AIText"},
        {"id": "ai_image", "class": "AIImage"},
        {"id": "apod", "class": "Apod"},
    ]

    load_plugins(plugins)
    assert "ai_text" in PLUGIN_CLASSES
    assert "ai_image" in PLUGIN_CLASSES
    assert "apod" in PLUGIN_CLASSES

    inst = get_plugin_instance(plugins[0])
    assert inst.get_plugin_id() == "ai_text"


