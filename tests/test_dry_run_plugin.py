# pyright: reportMissingImports=false
"""Tests for scripts/dry_run_plugin.py — the offline plugin dry-run CLI."""

import importlib
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image

# ── helpers ─────────────────────────────────────────────────────────────────


def _import_dry_run():
    """Import the dry_run_plugin script as a module (adds src/ to sys.path)."""
    repo_root = Path(__file__).parent.parent
    script_path = repo_root / "scripts" / "dry_run_plugin.py"
    spec = importlib.util.spec_from_file_location("dry_run_plugin", script_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


@pytest.fixture(scope="session")
def dry_run_mod():
    """Session-scoped import of dry_run_plugin to share across tests."""
    return _import_dry_run()


# ── unit: _MockDeviceConfig ──────────────────────────────────────────────────


def test_mock_device_config_get_resolution(dry_run_mod):
    cfg = dry_run_mod._MockDeviceConfig(1200, 600, "horizontal", "UTC")
    assert cfg.get_resolution() == (1200, 600)


def test_mock_device_config_orientation(dry_run_mod):
    cfg = dry_run_mod._MockDeviceConfig(800, 480, "vertical", "UTC")
    assert cfg.get_config("orientation") == "vertical"


def test_mock_device_config_timezone(dry_run_mod):
    cfg = dry_run_mod._MockDeviceConfig(800, 480, "horizontal", "Europe/London")
    assert cfg.get_config("timezone") == "Europe/London"


def test_mock_device_config_missing_key_returns_default(dry_run_mod):
    cfg = dry_run_mod._MockDeviceConfig(800, 480, "horizontal", "UTC")
    assert cfg.get_config("does_not_exist", default="fallback") == "fallback"
    assert cfg.get_config("does_not_exist") is None


def test_mock_device_config_load_env_key(dry_run_mod, monkeypatch):
    monkeypatch.setenv("MY_TEST_KEY", "secret_value")
    cfg = dry_run_mod._MockDeviceConfig(800, 480, "horizontal", "UTC")
    assert cfg.load_env_key("MY_TEST_KEY") == "secret_value"


# ── unit: _discover_plugin_config ────────────────────────────────────────────


def test_discover_plugin_config_year_progress(dry_run_mod):
    cfg = dry_run_mod._discover_plugin_config("year_progress")
    assert cfg["id"] == "year_progress"
    assert cfg["class"] == "YearProgress"


def test_discover_plugin_config_missing_plugin_exits(dry_run_mod):
    with pytest.raises(SystemExit):
        dry_run_mod._discover_plugin_config("plugin_does_not_exist_xyz")


# ── unit: _load_settings ─────────────────────────────────────────────────────


def test_load_settings_no_config(dry_run_mod):
    assert dry_run_mod._load_settings(None) == {}


def test_load_settings_valid_json(dry_run_mod, tmp_path):
    cfg_file = tmp_path / "settings.json"
    cfg_file.write_text(json.dumps({"selectedFrame": "None", "style": "dark"}))
    result = dry_run_mod._load_settings(str(cfg_file))
    assert result == {"selectedFrame": "None", "style": "dark"}


def test_load_settings_missing_file_exits(dry_run_mod, tmp_path):
    with pytest.raises(SystemExit):
        dry_run_mod._load_settings(str(tmp_path / "nonexistent.json"))


def test_load_settings_non_object_exits(dry_run_mod, tmp_path):
    cfg_file = tmp_path / "bad.json"
    cfg_file.write_text(json.dumps(["a", "b", "c"]))
    with pytest.raises(SystemExit):
        dry_run_mod._load_settings(str(cfg_file))


# ── integration: year_progress generates a PNG ───────────────────────────────


def test_year_progress_produces_png(dry_run_mod, tmp_path):
    """Run generate_image() via the dry-run helpers and verify a PNG is created."""
    from plugins.plugin_registry import get_plugin_instance, load_plugins

    plugin_config = dry_run_mod._discover_plugin_config("year_progress")
    load_plugins([plugin_config])

    device_config = dry_run_mod._MockDeviceConfig(800, 480, "horizontal", "UTC")
    plugin_instance = get_plugin_instance(plugin_config)
    image = plugin_instance.generate_image({}, device_config)

    output = tmp_path / "out.png"
    image.save(str(output))

    assert output.exists(), "PNG was not saved"
    loaded = Image.open(output)
    assert loaded.width == 800
    assert loaded.height == 480


def test_year_progress_custom_dimensions(dry_run_mod, tmp_path):
    """Verify that the mock device config's resolution flows through to the image."""
    from plugins.plugin_registry import get_plugin_instance, load_plugins

    plugin_config = dry_run_mod._discover_plugin_config("year_progress")
    load_plugins([plugin_config])

    device_config = dry_run_mod._MockDeviceConfig(640, 400, "horizontal", "UTC")
    plugin_instance = get_plugin_instance(plugin_config)
    image = plugin_instance.generate_image({}, device_config)

    output = tmp_path / "out_640.png"
    image.save(str(output))

    assert output.exists()
    loaded = Image.open(output)
    assert loaded.width == 640
    assert loaded.height == 400


def test_year_progress_config_override(dry_run_mod, tmp_path):
    """--config JSON override is loaded and passed as settings to generate_image()."""
    from plugins.plugin_registry import get_plugin_instance, load_plugins

    # Write a settings file that year_progress will silently accept (unknown keys are ok)
    settings = {"selectedFrame": "None", "custom_option": "value"}
    cfg_file = tmp_path / "settings.json"
    cfg_file.write_text(json.dumps(settings))

    loaded_settings = dry_run_mod._load_settings(str(cfg_file))
    assert loaded_settings == settings

    plugin_config = dry_run_mod._discover_plugin_config("year_progress")
    load_plugins([plugin_config])

    device_config = dry_run_mod._MockDeviceConfig(800, 480, "horizontal", "UTC")
    plugin_instance = get_plugin_instance(plugin_config)

    # generate_image must succeed even with extra/unknown settings keys
    image = plugin_instance.generate_image(loaded_settings, device_config)
    assert isinstance(image, Image.Image)


# ── integration: main() end-to-end via argv patching ─────────────────────────


def test_main_writes_png_for_year_progress(tmp_path, monkeypatch):
    """Call main() directly with year_progress and verify the PNG is created."""
    output = tmp_path / "result.png"
    test_argv = [
        "dry_run_plugin.py",
        "--plugin",
        "year_progress",
        "--output",
        str(output),
        "--width",
        "800",
        "--height",
        "480",
        "--timezone",
        "UTC",
    ]
    with patch.object(sys, "argv", test_argv):
        mod = _import_dry_run()
        mod.main()

    assert output.exists(), f"Expected PNG at {output}"
    img = Image.open(output)
    assert img.width == 800
    assert img.height == 480


def test_main_respects_config_override(tmp_path, monkeypatch):
    """main() passes the --config JSON into generate_image settings."""
    output = tmp_path / "result_cfg.png"
    settings_file = tmp_path / "settings.json"
    settings_file.write_text(json.dumps({"selectedFrame": "None"}))

    test_argv = [
        "dry_run_plugin.py",
        "--plugin",
        "year_progress",
        "--output",
        str(output),
        "--config",
        str(settings_file),
    ]
    with patch.object(sys, "argv", test_argv):
        mod = _import_dry_run()
        mod.main()

    assert output.exists()


def test_main_default_output_path(tmp_path, monkeypatch):
    """When --output is omitted the file is created in the cwd."""
    # Change working directory to tmp_path so the default path lands there
    monkeypatch.chdir(tmp_path)

    test_argv = [
        "dry_run_plugin.py",
        "--plugin",
        "year_progress",
    ]
    with patch.object(sys, "argv", test_argv):
        mod = _import_dry_run()
        mod.main()

    pngs = list(tmp_path.glob("dry-run-year_progress-*.png"))
    assert len(pngs) == 1, f"Expected one auto-named PNG, found: {pngs}"
