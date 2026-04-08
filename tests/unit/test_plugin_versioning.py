# pyright: reportMissingImports=false
"""Tests for JTN-300: plugin api_version and version metadata."""

import json
import logging

# ---------------------------------------------------------------------------
# BasePlugin: version attributes exposed on instance
# ---------------------------------------------------------------------------


def test_base_plugin_exposes_version_from_config():
    """Plugin instance exposes version and api_version read from config."""
    from plugins.base_plugin.base_plugin import BasePlugin

    p = BasePlugin({"id": "ai_text", "version": "1.0.0", "api_version": "1.0"})
    assert p.version == "1.0.0"
    assert p.api_version == "1.0"


def test_base_plugin_version_none_when_missing():
    """Plugin instance version/api_version are None when not in config."""
    from plugins.base_plugin.base_plugin import BasePlugin

    p = BasePlugin({"id": "ai_text"})
    assert p.version is None
    assert p.api_version is None


def test_plugin_api_version_constant_defined():
    """PLUGIN_API_VERSION constant must be defined and equal '1.0'."""
    from plugins.base_plugin.base_plugin import PLUGIN_API_VERSION

    assert PLUGIN_API_VERSION == "1.0"


# ---------------------------------------------------------------------------
# Plugin registry: _check_plugin_version
# ---------------------------------------------------------------------------


def test_check_plugin_version_reads_fields(tmp_path):
    """_check_plugin_version returns (api_version, version) from plugin-info.json."""
    import plugins.plugin_registry as pr

    info = {
        "display_name": "Test",
        "id": "test_plugin",
        "class": "TestPlugin",
        "api_version": "1.0",
        "version": "1.0.0",
    }
    (tmp_path / "plugin-info.json").write_text(json.dumps(info), encoding="utf-8")

    api_ver, ver = pr._check_plugin_version("test_plugin", tmp_path)
    assert api_ver == "1.0"
    assert ver == "1.0.0"


def test_check_plugin_version_missing_fields_returns_none(tmp_path):
    """_check_plugin_version returns (None, None) when fields are absent (backward compat)."""
    import plugins.plugin_registry as pr

    info = {"display_name": "Old", "id": "old_plugin", "class": "OldPlugin"}
    (tmp_path / "plugin-info.json").write_text(json.dumps(info), encoding="utf-8")

    api_ver, ver = pr._check_plugin_version("old_plugin", tmp_path)
    assert api_ver is None
    assert ver is None


def test_check_plugin_version_no_info_file_returns_none(tmp_path, caplog):
    """_check_plugin_version returns (None, None) when plugin-info.json is absent."""
    import plugins.plugin_registry as pr

    with caplog.at_level(logging.DEBUG, logger="plugins.plugin_registry"):
        api_ver, ver = pr._check_plugin_version("ghost_plugin", tmp_path)

    assert api_ver is None
    assert ver is None


def test_check_plugin_version_major_mismatch_logs_warning(tmp_path, caplog):
    """Major api_version mismatch logs a warning but does not raise."""
    import plugins.plugin_registry as pr

    info = {
        "display_name": "Future",
        "id": "future_plugin",
        "class": "FuturePlugin",
        "api_version": "9.0",
        "version": "9.0.0",
    }
    (tmp_path / "plugin-info.json").write_text(json.dumps(info), encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger="plugins.plugin_registry"):
        api_ver, ver = pr._check_plugin_version("future_plugin", tmp_path)

    assert api_ver == "9.0"
    assert ver == "9.0.0"
    assert any("Major version mismatch" in r.getMessage() for r in caplog.records)


def test_check_plugin_version_same_major_no_warning(tmp_path, caplog):
    """Matching major version logs no warning."""
    import plugins.plugin_registry as pr

    info = {
        "display_name": "Current",
        "id": "current_plugin",
        "class": "CurrentPlugin",
        "api_version": "1.0",
        "version": "1.0.0",
    }
    (tmp_path / "plugin-info.json").write_text(json.dumps(info), encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger="plugins.plugin_registry"):
        pr._check_plugin_version("current_plugin", tmp_path)

    assert not any("Major version mismatch" in r.getMessage() for r in caplog.records)


# ---------------------------------------------------------------------------
# load_plugins: version fields stored on config
# ---------------------------------------------------------------------------


def test_load_plugins_stores_version_fields_from_info_json(monkeypatch, tmp_path):
    """load_plugins copies api_version/version from plugin-info.json into stored config."""
    import plugins.plugin_registry as pr

    # resolve_path("plugins") → tmp_path/plugins; plugin dir under that
    plugins_root = tmp_path / "plugins"
    plugin_dir = plugins_root / "myplugin"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "myplugin.py").write_text("class MyPlugin: pass", encoding="utf-8")
    info = {
        "display_name": "My Plugin",
        "id": "myplugin",
        "class": "MyPlugin",
        "api_version": "1.0",
        "version": "1.0.0",
    }
    (plugin_dir / "plugin-info.json").write_text(json.dumps(info), encoding="utf-8")

    monkeypatch.setenv("SRC_DIR", str(tmp_path))
    pr.PLUGIN_CLASSES.clear()
    pr._PLUGIN_CONFIGS.clear()

    pr.load_plugins([{"id": "myplugin", "class": "MyPlugin"}])

    assert "myplugin" in pr._PLUGIN_CONFIGS
    stored = pr._PLUGIN_CONFIGS["myplugin"]
    assert stored.get("api_version") == "1.0"
    assert stored.get("version") == "1.0.0"


def test_load_plugins_backward_compat_no_version_fields(monkeypatch, tmp_path):
    """Plugin without version fields still loads successfully."""
    import plugins.plugin_registry as pr

    plugins_root = tmp_path / "plugins"
    plugin_dir = plugins_root / "legacyplugin"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "legacyplugin.py").write_text("class Legacy: pass", encoding="utf-8")
    info = {"display_name": "Legacy", "id": "legacyplugin", "class": "Legacy"}
    (plugin_dir / "plugin-info.json").write_text(json.dumps(info), encoding="utf-8")

    monkeypatch.setenv("SRC_DIR", str(tmp_path))
    pr.PLUGIN_CLASSES.clear()
    pr._PLUGIN_CONFIGS.clear()

    pr.load_plugins([{"id": "legacyplugin", "class": "Legacy"}])

    assert "legacyplugin" in pr._PLUGIN_CONFIGS
    stored = pr._PLUGIN_CONFIGS["legacyplugin"]
    # Fields should be absent (not injected) when not in info file
    assert stored.get("api_version") is None
    assert stored.get("version") is None


def test_load_plugins_major_mismatch_still_registers(monkeypatch, tmp_path, caplog):
    """Plugin with mismatched api_version major still gets registered (logs warning)."""
    import plugins.plugin_registry as pr

    plugins_root = tmp_path / "plugins"
    plugin_dir = plugins_root / "futureplugin"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "futureplugin.py").write_text("class Future: pass", encoding="utf-8")
    info = {
        "display_name": "Future",
        "id": "futureplugin",
        "class": "Future",
        "api_version": "99.0",
        "version": "99.0.0",
    }
    (plugin_dir / "plugin-info.json").write_text(json.dumps(info), encoding="utf-8")

    monkeypatch.setenv("SRC_DIR", str(tmp_path))
    pr.PLUGIN_CLASSES.clear()
    pr._PLUGIN_CONFIGS.clear()

    with caplog.at_level(logging.WARNING, logger="plugins.plugin_registry"):
        pr.load_plugins([{"id": "futureplugin", "class": "Future"}])

    assert "futureplugin" in pr._PLUGIN_CONFIGS
    assert any("Major version mismatch" in r.getMessage() for r in caplog.records)
