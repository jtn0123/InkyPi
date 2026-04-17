"""Upgrade-chain regression suite (JTN-734)."""

from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

import pytest
import yaml
from tests.helpers.config_runtime_helpers import (
    assert_valid_device_config,
    load_runtime_config,
    run_upgrade_hop,
)
from tests.helpers.path_utils import _assert_baseline_preserved, _path_get

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
CHAIN_FILE = FIXTURES_DIR / "version_chain.yml"


def _load_chain_spec() -> dict:
    return yaml.safe_load(CHAIN_FILE.read_text(encoding="utf-8"))


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_upgrade_chain_preserves_user_state_and_diagnostics_clean(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("INKYPI_ENV", "dev")

    spec = _load_chain_spec()
    chain = spec["chain"]
    preserved_paths = spec["preserved_paths"]

    baseline_fixture = _load_json(FIXTURES_DIR / chain[0]["fixture"])
    baseline_values = {
        dotted_path: _path_get(baseline_fixture, dotted_path)
        for dotted_path in preserved_paths
    }

    runtime_config = tmp_path / "device.json"
    for step in chain:
        fixture_path = FIXTURES_DIR / step["fixture"]
        shutil.copyfile(fixture_path, runtime_config)

        loaded_config, diagnostics = run_upgrade_hop(runtime_config, monkeypatch)
        _assert_baseline_preserved(
            baseline_values,
            loaded_config,
            preserved_paths,
            version=step["version"],
        )
        assert diagnostics["plugin_health"].get("clock") in {"ok", "unknown"}


def test_upgrade_chain_detects_key_drop_at_specific_hop(monkeypatch, tmp_path):
    monkeypatch.setenv("INKYPI_ENV", "dev")

    spec = _load_chain_spec()
    chain = spec["chain"]
    preserved_paths = spec["preserved_paths"]

    baseline_fixture = _load_json(FIXTURES_DIR / chain[0]["fixture"])
    baseline_values = {
        dotted_path: _path_get(baseline_fixture, dotted_path)
        for dotted_path in preserved_paths
    }

    # Simulate a migration regression at the N-1 hop by dropping timezone.
    broken = copy.deepcopy(_load_json(FIXTURES_DIR / chain[1]["fixture"]))
    broken.pop("timezone", None)
    runtime_config = tmp_path / "broken-device.json"
    runtime_config.write_text(json.dumps(broken), encoding="utf-8")

    cfg = load_runtime_config(runtime_config, monkeypatch)
    loaded_config = cfg.get_config()
    assert_valid_device_config(loaded_config)

    with pytest.raises((AssertionError, KeyError), match="timezone"):
        _assert_baseline_preserved(
            baseline_values,
            loaded_config,
            preserved_paths,
            version=chain[1]["version"],
        )
