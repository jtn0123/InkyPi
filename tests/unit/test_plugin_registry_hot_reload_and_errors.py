import importlib
import sys
from types import SimpleNamespace


def test_plugin_registry_reports_missing_dir_and_module(monkeypatch, tmp_path):
    # Point PLUGINS_DIR to temp to force missing dirs
    import src.plugins.plugin_registry as pr

    monkeypatch.setattr(pr, "PLUGINS_DIR", "plugins", raising=True)
    # Override resolve_path to return temp path with no plugins
    monkeypatch.setattr(
        "src.plugins.plugin_registry.resolve_path", lambda p: str(tmp_path), raising=True
    )

    pr.PLUGIN_CLASSES.clear()
    # Two plugins that don't exist on disk
    pr.load_plugins([
        {"id": "fake_one", "class": "FakeOne"},
        {"id": "fake_two", "class": "FakeTwo"},
    ])
    # Nothing loaded
    assert not pr.PLUGIN_CLASSES


def test_plugin_registry_hot_reload_flag(monkeypatch, tmp_path):
    import types
    import src.plugins.plugin_registry as pr

    # Simulate dev mode for hot reload path
    monkeypatch.setenv("INKYPI_ENV", "dev")

    plugin_id = "sample"
    module_name = f"plugins.{plugin_id}.{plugin_id}"

    # Create a dummy module with a plugin class
    class DummyPlugin:
        def __init__(self, cfg):
            self.cfg = cfg
        def get_plugin_id(self):
            return plugin_id

    # Create a minimal module-like object
    mod = type(sys)(module_name)
    setattr(mod, "Sample", DummyPlugin)
    sys.modules[module_name] = mod

    # First load should import (not reload) → reloaded=False
    inst1 = pr._load_single_plugin_instance({"id": plugin_id, "class": "Sample"})
    assert inst1.get_plugin_id() == plugin_id
    info1 = pr.pop_hot_reload_info()
    assert info1 and info1.get("plugin_id") == plugin_id and info1.get("reloaded") is False

    # Second load: ensure sys.modules contains the module and that importlib.reload is used
    # Also, make sure _is_dev_mode() returns True by clearing PYTEST_CURRENT_TEST guard
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    def fake_reload(m):
        # Return the same module instance; mark that reload occurred by toggling attr
        setattr(m, "_reloaded", True)
        return m

    monkeypatch.setattr(importlib, "reload", fake_reload, raising=True)
    inst2 = pr._load_single_plugin_instance({"id": plugin_id, "class": "Sample"})
    assert inst2.get_plugin_id() == plugin_id
    info2 = pr.pop_hot_reload_info()
    assert info2 and info2.get("plugin_id") == plugin_id and info2.get("reloaded") is True

