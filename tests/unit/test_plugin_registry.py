# pyright: reportMissingImports=false
import os
import subprocess
import sys
from pathlib import Path

import pytest

from plugins.plugin_registry import (
    PLUGIN_CLASSES,
    _PLUGIN_CONFIGS,
    get_plugin_instance,
    get_registered_plugin_ids,
    load_plugins,
)


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


def _read_pythonpath_from_shell(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
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
    expected_entries = [str(_repo_root()), str(_repo_root() / "src")]
    # On case-insensitive filesystems (macOS), pwd may return different case
    assert pythonpath.lower() == os.pathsep.join(expected_entries).lower()


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
