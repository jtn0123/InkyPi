"""Upgrade-chain regression suite (JTN-734)."""

from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

import pytest
import yaml
from flask import Flask
from tests.helpers.path_utils import _assert_baseline_preserved, _path_get

import config as config_mod
from blueprints.diagnostics import diagnostics_bp
from display.display_manager import DisplayManager
from plugins.plugin_registry import load_plugins
from refresh_task import ManualRefresh, RefreshTask
from utils.config_schema import validate_device_config

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
CHAIN_FILE = FIXTURES_DIR / "version_chain.yml"


def _load_chain_spec() -> dict:
    return yaml.safe_load(CHAIN_FILE.read_text(encoding="utf-8"))


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _make_diag_app(device_config, refresh_task) -> Flask:
    app = Flask(__name__)
    app.config["DEVICE_CONFIG"] = device_config
    app.config["REFRESH_TASK"] = refresh_task
    app.config["AUTH_ENABLED"] = False

    @app.route("/healthz")
    def _healthz():
        return ("OK", 200)

    app.register_blueprint(diagnostics_bp)
    return app


def _run_upgrade_hop(config_path: Path, monkeypatch) -> tuple[dict, dict]:
    monkeypatch.setattr(config_mod.Config, "config_file", str(config_path))
    cfg = config_mod.Config()

    # Service healthy + config valid after migration load.
    validate_device_config(cfg.get_config())
    assert cfg.get_playlist_manager().playlists

    display_manager = DisplayManager(cfg)
    refresh_task = RefreshTask(cfg, display_manager)
    load_plugins(cfg.get_plugins())

    app = _make_diag_app(cfg, refresh_task)
    with app.test_client() as client:
        refresh_task.start()
        try:
            assert client.get("/healthz").status_code == 200
            metrics = refresh_task.manual_update(ManualRefresh("clock", {}))
            assert metrics is not None

            diag_resp = client.get("/api/diagnostics")
            assert diag_resp.status_code == 200
            diagnostics = diag_resp.get_json()
            assert diagnostics["refresh_task"]["running"] is True
            assert diagnostics["refresh_task"]["last_error"] is None
        finally:
            refresh_task.stop()

    return cfg.get_config(), diagnostics


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

        loaded_config, diagnostics = _run_upgrade_hop(runtime_config, monkeypatch)
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

    loaded_config, _diagnostics = _run_upgrade_hop(runtime_config, monkeypatch)

    with pytest.raises((AssertionError, KeyError), match="timezone"):
        _assert_baseline_preserved(
            baseline_values,
            loaded_config,
            preserved_paths,
            version=chain[1]["version"],
        )
