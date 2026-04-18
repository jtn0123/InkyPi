"""Upgrade-chain regression suite (JTN-734).

This test walks every pinned historical ``device.json`` fixture through the
current loader and asserts that user-facing state survives migration. We
deliberately keep the test at the *config-loader* layer:

* ``config.Config()`` already calls ``validate_device_config()`` internally,
  so a broken schema at any hop fails construction with
  ``ConfigValidationError`` and the test aborts loudly.
* The refresh pipeline, display manager, plugin registry, and diagnostics
  blueprint are exercised by their own dedicated suites — duplicating that
  end-to-end wiring here would pull tests across the architecture boundary
  (Sonar ``pythonarchitecture:S7788``) without adding upgrade-specific
  coverage.
"""

from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

import pytest
import yaml

import config as config_mod

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
CHAIN_FILE = FIXTURES_DIR / "version_chain.yml"


def _load_chain_spec() -> dict:
    return yaml.safe_load(CHAIN_FILE.read_text(encoding="utf-8"))


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _path_get(payload: object, dotted_path: str) -> object:
    node: object = payload
    for segment in dotted_path.split("."):
        if isinstance(node, list):
            node = node[int(segment)]
            continue
        if not isinstance(node, dict):
            raise KeyError(f"{dotted_path}: expected mapping at '{segment}'")
        node = node[segment]
    return node


def _assert_baseline_preserved(
    baseline_values: dict[str, object],
    actual_payload: dict,
    paths: list[str],
    version: str,
) -> None:
    for dotted_path in paths:
        actual_value = _path_get(actual_payload, dotted_path)
        assert actual_value == baseline_values[dotted_path], (
            f"Upgrade hop {version} dropped/changed '{dotted_path}': "
            f"expected={baseline_values[dotted_path]!r} actual={actual_value!r}"
        )


def _load_upgrade_hop(config_path: Path, monkeypatch) -> dict:
    """Load ``config_path`` through :class:`config.Config` and return its dict.

    ``Config.__init__`` reads the file and runs ``validate_device_config``
    against it, so a successful return proves *both* that the migration
    loader accepted the fixture and that the resulting shape still matches
    the current JSON Schema. The playlist manager is also exercised here to
    guard against silent playlist-collection drops during migration.
    """
    monkeypatch.setattr(config_mod.Config, "config_file", str(config_path))
    cfg = config_mod.Config()

    # Re-run validation through the loader's own re-exported symbol so
    # this test does not add a new tests→``utils.config_schema`` edge.
    config_mod.validate_device_config(cfg.get_config())

    assert cfg.get_playlist_manager().playlists, (
        "Migration produced a Config with no playlists — user state lost."
    )
    return cfg.get_config()


def test_upgrade_chain_preserves_user_state(monkeypatch, tmp_path):
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

        loaded_config = _load_upgrade_hop(runtime_config, monkeypatch)
        _assert_baseline_preserved(
            baseline_values,
            loaded_config,
            preserved_paths,
            version=step["version"],
        )


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

    loaded_config = _load_upgrade_hop(runtime_config, monkeypatch)

    with pytest.raises((AssertionError, KeyError), match="timezone"):
        _assert_baseline_preserved(
            baseline_values,
            loaded_config,
            preserved_paths,
            version=chain[1]["version"],
        )
