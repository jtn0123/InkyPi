# pyright: reportMissingImports=false
import logging

from plugins.plugin_registry import PLUGIN_CLASSES, get_plugin_instance, load_plugins


def test_load_plugins_skips_disabled_and_missing_paths(monkeypatch, tmp_path):
    # Force resolve_path to use tmp dir with no plugin subdirs
    monkeypatch.setenv("SRC_DIR", str(tmp_path))
    (tmp_path / "plugins").mkdir(parents=True, exist_ok=True)

    PLUGIN_CLASSES.clear()
    plugins = [
        {"id": "nonexistent", "class": "X"},
        {"id": "skipme", "class": "X", "disabled": True},
    ]
    load_plugins(plugins)

    assert "nonexistent" not in PLUGIN_CLASSES
    assert "skipme" not in PLUGIN_CLASSES


def test_load_plugins_logs_error_for_missing_dir(monkeypatch, tmp_path, caplog):
    monkeypatch.setenv("SRC_DIR", str(tmp_path))
    (tmp_path / "plugins").mkdir(parents=True, exist_ok=True)

    PLUGIN_CLASSES.clear()
    plugins = [{"id": "missing", "class": "X"}]
    with caplog.at_level(logging.ERROR, logger="plugins.plugin_registry"):
        load_plugins(plugins)

    assert any(
        record.name == "plugins.plugin_registry"
            and "Could not find plugin directory" in record.getMessage()
        for record in caplog.records
    )


def test_get_plugin_instance_raises_for_unregistered():
    PLUGIN_CLASSES.clear()
    try:
        get_plugin_instance({"id": "unknown"})
        assert False, "Expected ValueError"
    except ValueError:
        pass
