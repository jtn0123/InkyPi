"""Dev mode re-reads edited page templates; production keeps them cached."""

from __future__ import annotations

import importlib
from typing import Any

import pytest
from flask import Flask


@pytest.mark.parametrize("dev_mode", [True, False])
def test_templates_reload_only_in_dev_mode(
    dev_mode: bool, device_config_dev: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import inkypi

    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-template-reload")
    inkypi = importlib.reload(inkypi)

    def _fake_init_core_services(app: Flask) -> Any:
        app.config["DEVICE_CONFIG"] = device_config_dev
        app.config["WEB_ONLY"] = True
        return device_config_dev

    monkeypatch.setattr(inkypi, "_init_core_services", _fake_init_core_services)
    monkeypatch.setattr(inkypi, "setup_signal_handlers", lambda app: None)

    app = inkypi.create_app(inkypi.RuntimeOptions(dev_mode=dev_mode, web_only=True))

    assert app.jinja_env.auto_reload is dev_mode
