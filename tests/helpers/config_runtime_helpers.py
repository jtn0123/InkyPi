"""Helpers that encapsulate runtime/config imports for regression tests."""

from __future__ import annotations

from pathlib import Path

from flask import Flask

import config as config_mod
from blueprints.diagnostics import diagnostics_bp
from display.display_manager import DisplayManager
from plugins.plugin_registry import load_plugins
from refresh_task import ManualRefresh, RefreshTask
from utils.config_schema import validate_device_config


def load_runtime_config(config_path: Path, monkeypatch) -> config_mod.Config:
    """Load a Config instance from an explicit path for test scenarios."""
    monkeypatch.setattr(config_mod.Config, "config_file", str(config_path))
    return config_mod.Config()


def assert_valid_device_config(config_payload: dict) -> None:
    """Keep config-schema imports out of test modules."""
    validate_device_config(config_payload)


def run_upgrade_hop(config_path: Path, monkeypatch) -> tuple[dict, dict]:
    """Load a migrated config and exercise diagnostics/refresh health checks."""
    cfg = load_runtime_config(config_path, monkeypatch)

    # Service healthy + config valid after migration load.
    assert_valid_device_config(cfg.get_config())
    assert cfg.get_playlist_manager().playlists

    display_manager = DisplayManager(cfg)
    refresh_task = RefreshTask(cfg, display_manager)
    load_plugins(cfg.get_plugins())

    app = Flask(__name__)
    app.config["DEVICE_CONFIG"] = cfg
    app.config["REFRESH_TASK"] = refresh_task
    app.config["AUTH_ENABLED"] = False

    @app.route("/healthz")
    def _healthz():
        return ("OK", 200)

    app.register_blueprint(diagnostics_bp)
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
