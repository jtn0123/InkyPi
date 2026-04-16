"""Coverage for metrics fallback behavior when prometheus_client is unavailable."""

from __future__ import annotations

import builtins
import importlib
import sys

import pytest
from flask import Flask


def _blocked_prometheus_import(name: str, *args, **kwargs):
    if name == "prometheus_client" or name.startswith("prometheus_client."):
        raise ModuleNotFoundError(name)
    return _ORIGINAL_IMPORT(name, *args, **kwargs)


_ORIGINAL_IMPORT = builtins.__import__


def _reload_metrics_modules_without_prometheus():
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(builtins, "__import__", _blocked_prometheus_import)
        for module_name in list(sys.modules):
            if module_name.startswith("prometheus_client"):
                sys.modules.pop(module_name, None)
        sys.modules.pop("utils.metrics", None)
        sys.modules.pop("blueprints.metrics", None)
        importlib.invalidate_caches()
        metrics_module = importlib.import_module("utils.metrics")
        blueprint_module = importlib.import_module("blueprints.metrics")
        return metrics_module, blueprint_module


def _restore_metrics_modules() -> None:
    sys.modules.pop("blueprints.metrics", None)
    sys.modules.pop("utils.metrics", None)
    importlib.invalidate_caches()
    importlib.import_module("utils.metrics")
    importlib.import_module("blueprints.metrics")


def test_metrics_noop_fallback_records_do_not_crash():
    metrics_module, _ = _reload_metrics_modules_without_prometheus()
    try:
        assert metrics_module._PROMETHEUS_AVAILABLE is False
        assert metrics_module.metrics_registry.__class__.__name__ == "_NoopRegistry"

        metric = metrics_module.refreshes_total.labels(status="success")
        assert metric is metrics_module.refreshes_total

        metrics_module.record_refresh_success()
        metrics_module.record_refresh_failure("clock")
        metrics_module.set_circuit_breaker_open("clock", is_open=True)
        metrics_module.update_uptime()
        metrics_module.record_http_request("GET", "/healthz", "200", 0.01)
    finally:
        _restore_metrics_modules()


def test_metrics_blueprint_returns_disabled_payload_without_prometheus():
    _, metrics_blueprint = _reload_metrics_modules_without_prometheus()
    try:
        app = Flask(__name__)
        app.register_blueprint(metrics_blueprint.metrics_bp)

        resp = app.test_client().get("/metrics")
        assert resp.status_code == 200
        assert resp.content_type.startswith("text/plain")
        assert b"metrics disabled" in resp.data
    finally:
        _restore_metrics_modules()
