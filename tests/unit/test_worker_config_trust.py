"""A render worker trusts the parent's validation of identical config content.

Every worker rebuilds ``Config`` from device.json. It used to run the full
JSON Schema validation each time, and importing jsonschema for it cost a Pi
Zero ~8 MB and up to 0.7 s per render. The parent now passes the hash of the
content it validated; the worker skips validating those exact bytes and still
validates anything else.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

import config as config_mod
from refresh_task.context import RefreshContext
from utils.config_schema import ConfigValidationError

SRC_DIR = Path(__file__).resolve().parents[2] / "src"


def _file_digest(path: str) -> str:
    with open(path) as fh:
        return hashlib.sha256(fh.read().encode()).hexdigest()


def _count_validations(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    calls: list[object] = []
    real = config_mod.validate_device_config

    def _counting(config: Any) -> None:
        calls.append(config)
        real(config)

    monkeypatch.setattr(config_mod, "validate_device_config", _counting)
    return calls


def test_parent_digest_follows_reads_and_writes(device_config_dev: Any) -> None:
    path = device_config_dev.config_file
    assert device_config_dev.validated_config_digest() == _file_digest(path)

    device_config_dev.update_value("name", "Kitchen frame", write=True)

    assert device_config_dev.validated_config_digest() == _file_digest(path)


def test_worker_skips_validation_only_for_the_validated_bytes(
    device_config_dev: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = dataclasses.replace(
        RefreshContext.from_config(device_config_dev),
        validated_config_digest=device_config_dev.validated_config_digest(),
    )
    calls = _count_validations(monkeypatch)

    child = context.restore_child_config()

    assert calls == []
    assert child.config == device_config_dev.config

    # Content the parent never validated is checked as before...
    path = Path(device_config_dev.config_file)
    data = json.loads(path.read_text())
    data["name"] = "Changed on disk"
    path.write_text(json.dumps(data))
    child = context.restore_child_config()
    assert len(calls) == 1
    assert child.get_config("name") == "Changed on disk"

    # ...and still rejected when invalid.
    data["resolution"] = "not a resolution"
    path.write_text(json.dumps(data))
    with pytest.raises(ConfigValidationError):
        context.restore_child_config()


def test_executor_hands_each_worker_the_current_digest(device_config_dev: Any) -> None:
    from display.display_manager import DisplayManager
    from refresh_task import RefreshTask

    task = RefreshTask(device_config_dev, DisplayManager(device_config_dev))
    device_config_dev.update_value("name", "After start-up", write=True)

    context = task.executor.attempt_context()

    assert context.validated_config_digest == _file_digest(
        device_config_dev.config_file
    )
    assert context.config_file == task.refresh_context.config_file


def test_worker_never_imports_jsonschema(
    device_config_dev: Any, tmp_path: Path
) -> None:
    """The worker's imports and its Config rebuild leave jsonschema unloaded."""
    context = RefreshContext.from_config(device_config_dev)
    script = f"""
import sys
import refresh_task.worker
from refresh_task.context import RefreshContext
context = RefreshContext(
    config_file={context.config_file!r},
    current_image_file={context.current_image_file!r},
    processed_image_file={context.processed_image_file!r},
    plugin_image_dir={context.plugin_image_dir!r},
    history_image_dir={context.history_image_dir!r},
    resolution={context.resolution!r},
    timezone={context.timezone!r},
    validated_config_digest={device_config_dev.validated_config_digest()!r},
)
config = context.restore_child_config()
config.get_plugins()
assert config.get_config("name") == "InkyPi Test"
print("jsonschema" in sys.modules)
"""
    env = {
        **os.environ,
        "PYTHONPATH": str(SRC_DIR),
        "PROJECT_DIR": str(tmp_path),
    }
    env.pop("INKYPI_CONFIG_FILE", None)
    env.pop("INKYPI_RUNTIME_DIR", None)
    result = subprocess.run(
        [sys.executable, "-c", script],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False"
