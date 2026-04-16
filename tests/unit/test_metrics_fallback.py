"""Coverage tests for Prometheus-missing fallback paths."""

from __future__ import annotations

import builtins
import importlib
import sys
from types import ModuleType


def _block_prometheus_imports(monkeypatch) -> None:
    real_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "prometheus_client" or name.startswith("prometheus_client."):
            raise ModuleNotFoundError("No module named 'prometheus_client'")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    for module_name in list(sys.modules):
        if module_name == "prometheus_client" or module_name.startswith(
            "prometheus_client."
        ):
            monkeypatch.delitem(sys.modules, module_name, raising=False)


def _import_fallback_modules(monkeypatch) -> tuple[ModuleType, ModuleType, callable]:
    original_metrics_module = sys.modules.get("utils.metrics")
    original_blueprints_metrics_module = sys.modules.get("blueprints.metrics")

    _block_prometheus_imports(monkeypatch)
    monkeypatch.delitem(sys.modules, "utils.metrics", raising=False)
    monkeypatch.delitem(sys.modules, "blueprints.metrics", raising=False)
    metrics_module = importlib.import_module("utils.metrics")
    blueprints_metrics_module = importlib.import_module("blueprints.metrics")

    def restore_modules() -> None:
        if original_metrics_module is None:
            sys.modules.pop("utils.metrics", None)
        else:
            sys.modules["utils.metrics"] = original_metrics_module

        if original_blueprints_metrics_module is None:
            sys.modules.pop("blueprints.metrics", None)
        else:
            sys.modules["blueprints.metrics"] = original_blueprints_metrics_module

    return metrics_module, blueprints_metrics_module, restore_modules


def test_metrics_helpers_work_without_prometheus(monkeypatch):
    metrics_module, _, restore_modules = _import_fallback_modules(monkeypatch)
    try:
        assert metrics_module._PROMETHEUS_AVAILABLE is False

        metrics_module.record_refresh_success()
        metrics_module.record_refresh_failure("fallback_plugin")
        metrics_module.set_circuit_breaker_open("fallback_plugin", True)
        metrics_module.update_uptime()
        metrics_module.record_http_request(
            method="GET",
            endpoint="/healthz",
            status_code="200",
            duration_seconds=0.01,
        )
    finally:
        restore_modules()


def test_metrics_endpoint_fallback_response_when_prometheus_missing(monkeypatch):
    _, blueprints_metrics_module, restore_modules = _import_fallback_modules(
        monkeypatch
    )
    try:
        response = blueprints_metrics_module.prometheus_metrics()
        assert response.status_code == 200
        assert b"prometheus_client not installed" in response.data
    finally:
        restore_modules()
