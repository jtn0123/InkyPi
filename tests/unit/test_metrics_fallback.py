"""Coverage tests for Prometheus-missing fallback paths."""

from __future__ import annotations

import builtins
import importlib
import sys
from collections.abc import Callable
from types import ModuleType
from typing import Any

import pytest


def _block_prometheus_imports(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = builtins.__import__

    def guarded_import(
        name: Any,
        globals: Any = None,
        locals: Any = None,
        fromlist: Any = (),
        level: Any = 0,
    ) -> Any:
        if name == "prometheus_client" or name.startswith("prometheus_client."):
            raise ModuleNotFoundError("No module named 'prometheus_client'")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    for module_name in list(sys.modules):
        if module_name == "prometheus_client" or module_name.startswith(
            "prometheus_client."
        ):
            monkeypatch.delitem(sys.modules, module_name, raising=False)


def _import_fallback_modules(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[ModuleType, ModuleType, Callable[[], None]]:
    original_metrics_module = sys.modules.get("utils.metrics")
    original_blueprints_metrics_module = sys.modules.get("blueprints.metrics")
    missing = object()
    original_parent_attributes = []
    for package_name in ("utils", "blueprints"):
        parent = importlib.import_module(package_name)
        original_parent_attributes.append(
            (parent, vars(parent).get("metrics", missing))
        )

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

        for parent, original_attribute in original_parent_attributes:
            if original_attribute is missing:
                vars(parent).pop("metrics", None)
            else:
                vars(parent)["metrics"] = original_attribute

    return metrics_module, blueprints_metrics_module, restore_modules


def test_metrics_helpers_work_without_prometheus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metrics_module, _, restore_modules = _import_fallback_modules(monkeypatch)
    try:
        assert metrics_module._PROMETHEUS_AVAILABLE is False

        assert (
            metrics_module.refreshes_total.labels("success")
            is metrics_module.refreshes_total
        )
        metrics_module.refreshes_total.inc(amount=2.0, exemplar={"trace_id": "123"})
        metrics_module.last_successful_refresh_timestamp.set(value=1.0)
        metrics_module.http_request_duration_seconds.observe(
            amount=0.01, exemplar={"trace_id": "123"}
        )
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


def test_metrics_endpoint_fallback_response_when_prometheus_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, blueprints_metrics_module, restore_modules = _import_fallback_modules(
        monkeypatch
    )
    try:
        response = blueprints_metrics_module.prometheus_metrics()
        assert response.status_code == 200
        assert b"prometheus_client not installed" in response.data
    finally:
        restore_modules()


@pytest.mark.parametrize("package_name", ["utils", "blueprints"])
@pytest.mark.parametrize("attribute_present", [False, True])
def test_fallback_import_restores_parent_package_attribute(
    package_name: str, attribute_present: bool
) -> None:
    """Restoring sys.modules must also restore dotted-import package lookup."""
    module_name = f"{package_name}.metrics"
    original_module = importlib.import_module(module_name)
    parent = importlib.import_module(package_name)
    with pytest.MonkeyPatch.context() as original_attribute:
        if attribute_present:
            original_attribute.setattr(
                parent, "metrics", original_module, raising=False
            )
        else:
            original_attribute.delattr(parent, "metrics", raising=False)
        with pytest.MonkeyPatch.context() as isolated:
            _, _, restore_modules = _import_fallback_modules(isolated)
            restore_modules()
            assert sys.modules[module_name] is original_module
            if attribute_present:
                assert vars(parent)["metrics"] is original_module
            else:
                assert not hasattr(parent, "metrics")
