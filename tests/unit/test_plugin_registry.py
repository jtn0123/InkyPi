# pyright: reportMissingImports=false
import importlib
import logging
import os
import subprocess
import sys
from pathlib import Path

from plugins.plugin_registry import (
    _PLUGIN_CONFIGS,
    PLUGIN_CLASSES,
    get_plugin_instance,
    get_registered_plugin_ids,
    load_plugins,
)

# ---------------------------------------------------------------------------
# Core registry tests
# ---------------------------------------------------------------------------


def test_load_and_get_plugin_instance():
    PLUGIN_CLASSES.clear()
    _PLUGIN_CONFIGS.clear()
    plugins = [
        {"id": "ai_text", "class": "AIText"},
        {"id": "ai_image", "class": "AIImage"},
        {"id": "apod", "class": "Apod"},
    ]

    load_plugins(plugins)
    registered = get_registered_plugin_ids()
    assert "ai_text" in registered
    assert "ai_image" in registered
    assert "apod" in registered

    inst = get_plugin_instance(plugins[0])
    assert inst.get_plugin_id() == "ai_text"
    # After first access, instance should be cached
    assert "ai_text" in PLUGIN_CLASSES


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _base_env() -> dict[str, str]:
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env["INKYPI_PYTHONPATH_ONLY"] = "1"
    return env


def _read_pythonpath_from_shell(
    env: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    command = (
        "source scripts/venv.sh >/dev/null 2>&1 && "
        "python - <<'PY'\n"
        "import os\n"
        "print(os.environ.get('PYTHONPATH', ''))\n"
        "PY\n"
    )
    return subprocess.run(
        ["/bin/bash", "-c", command],
        cwd=str(_repo_root()),
        env=env,
        capture_output=True,
        text=True,
    )


def test_venv_shell_sets_pythonpath():
    """Ensure scripts/venv.sh can be sourced to set PYTHONPATH without side effects."""

    env = _base_env()
    result = _read_pythonpath_from_shell(env)

    assert result.returncode == 0, result.stderr

    pythonpath = result.stdout.strip()
    # Compare case-insensitively so that macOS case-insensitive-but-preserving
    # filesystems don't produce a spurious mismatch between the Python-resolved
    # path (InkyPi) and the shell pwd path (inkypi).
    actual_entries = [p.lower() for p in pythonpath.split(os.pathsep) if p]
    expected_entries = [
        str(_repo_root()).lower(),
        str(_repo_root() / "src").lower(),
    ]
    assert actual_entries == expected_entries


def test_plugin_import_with_pythonpath():
    """Simulate a fresh process using scripts/venv.sh output and ensure ai_image imports."""

    env = _base_env()
    result = _read_pythonpath_from_shell(env)
    assert result.returncode == 0, result.stderr

    pythonpath = result.stdout.strip()
    assert pythonpath

    env["PYTHONPATH"] = pythonpath

    proc = subprocess.run(
        [sys.executable, "-c", "import plugins.ai_image.ai_image"],
        cwd=str(_repo_root()),
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr


# ---------------------------------------------------------------------------
# Error-path tests (from test_plugin_registry_errors.py)
# ---------------------------------------------------------------------------


def test_load_plugins_skips_disabled_and_missing_paths(monkeypatch, tmp_path):
    # Force resolve_path to use tmp dir with no plugin subdirs
    monkeypatch.setenv("SRC_DIR", str(tmp_path))
    (tmp_path / "plugins").mkdir(parents=True, exist_ok=True)

    PLUGIN_CLASSES.clear()
    _PLUGIN_CONFIGS.clear()
    plugins = [
        {"id": "nonexistent", "class": "X"},
        {"id": "skipme", "class": "X", "disabled": True},
    ]
    load_plugins(plugins)

    registered = get_registered_plugin_ids()
    assert "nonexistent" not in registered
    assert "skipme" not in registered


def test_load_plugins_logs_error_for_missing_module_file(monkeypatch, tmp_path, caplog):
    """Plugin directory exists but module .py file is missing."""
    monkeypatch.setenv("SRC_DIR", str(tmp_path))
    plugins_dir = tmp_path / "plugins" / "myplugin"
    plugins_dir.mkdir(parents=True, exist_ok=True)
    # Directory exists but no myplugin.py inside it

    PLUGIN_CLASSES.clear()
    _PLUGIN_CONFIGS.clear()
    plugins = [{"id": "myplugin", "class": "X"}]
    with caplog.at_level(logging.ERROR, logger="plugins.plugin_registry"):
        load_plugins(plugins)

    assert "myplugin" not in get_registered_plugin_ids()
    assert any(
        "Could not find module path" in record.getMessage() for record in caplog.records
    )


def test_load_plugins_logs_error_for_missing_dir(monkeypatch, tmp_path, caplog):
    monkeypatch.setenv("SRC_DIR", str(tmp_path))
    (tmp_path / "plugins").mkdir(parents=True, exist_ok=True)

    PLUGIN_CLASSES.clear()
    _PLUGIN_CONFIGS.clear()
    plugins = [{"id": "missing", "class": "X"}]
    with caplog.at_level(logging.ERROR, logger="plugins.plugin_registry"):
        load_plugins(plugins)

    assert any(
        record.name == "plugins.plugin_registry"
        and "Could not find plugin directory" in record.getMessage()
        for record in caplog.records
    )


def test_get_plugin_instance_returns_cached_instance():
    """Second call should return the same cached instance."""
    PLUGIN_CLASSES.clear()
    _PLUGIN_CONFIGS.clear()
    plugins = [{"id": "ai_text", "class": "AIText"}]
    load_plugins(plugins)

    inst1 = get_plugin_instance(plugins[0])
    inst2 = get_plugin_instance(plugins[0])
    assert inst1 is inst2


def test_get_plugin_instance_raises_for_unregistered():
    PLUGIN_CLASSES.clear()
    _PLUGIN_CONFIGS.clear()
    try:
        get_plugin_instance({"id": "unknown"})
        assert False, "Expected ValueError"
    except ValueError:
        pass


# ---------------------------------------------------------------------------
# Hot-reload and additional error tests (from test_plugin_registry_hot_reload_and_errors.py)
# ---------------------------------------------------------------------------


def test_plugin_registry_reports_missing_dir_and_module(monkeypatch, tmp_path):
    # Point PLUGINS_DIR to temp to force missing dirs
    import src.plugins.plugin_registry as pr

    monkeypatch.setattr(pr, "PLUGINS_DIR", "plugins", raising=True)
    # Override resolve_path to return temp path with no plugins
    monkeypatch.setattr(
        "src.plugins.plugin_registry.resolve_path",
        lambda p: str(tmp_path),
        raising=True,
    )

    pr.PLUGIN_CLASSES.clear()
    pr._PLUGIN_CONFIGS.clear()
    # Two plugins that don't exist on disk
    pr.load_plugins(
        [
            {"id": "fake_one", "class": "FakeOne"},
            {"id": "fake_two", "class": "FakeTwo"},
        ]
    )
    # Nothing registered (dirs don't exist)
    assert not pr.get_registered_plugin_ids()


def test_plugin_registry_hot_reload_flag(monkeypatch, tmp_path):
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
    mod.Sample = DummyPlugin
    sys.modules[module_name] = mod

    # First load should import (not reload) → reloaded=False
    inst1 = pr._load_single_plugin_instance({"id": plugin_id, "class": "Sample"})
    assert inst1.get_plugin_id() == plugin_id
    info1 = pr.pop_hot_reload_info()
    assert (
        info1 and info1.get("plugin_id") == plugin_id and info1.get("reloaded") is False
    )

    # Second load: ensure sys.modules contains the module and that importlib.reload is used
    # Also, make sure _is_dev_mode() returns True by clearing PYTEST_CURRENT_TEST guard
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    def fake_reload(m):
        # Return the same module instance; mark that reload occurred by toggling attr
        m._reloaded = True
        return m

    monkeypatch.setattr(importlib, "reload", fake_reload, raising=True)
    inst2 = pr._load_single_plugin_instance({"id": plugin_id, "class": "Sample"})
    assert inst2.get_plugin_id() == plugin_id
    info2 = pr.pop_hot_reload_info()
    assert (
        info2 and info2.get("plugin_id") == plugin_id and info2.get("reloaded") is True
    )
