import importlib
import os
import sys
from pathlib import Path

import pytest
from tests.unit.test_secret_key import _write_min_device_config


def test_import_does_not_parse(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["inkypi.py", "--dev"])
    monkeypatch.delenv("INKYPI_ENV", raising=False)
    sys.modules.pop("inkypi", None)
    import inkypi

    # Importing must not act on argv: --dev would set INKYPI_ENV, and there
    # is no module-level app or options to fill in.
    assert "INKYPI_ENV" not in os.environ
    assert not hasattr(inkypi, "app")
    assert not hasattr(inkypi, "args")


def test_main_invocation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg_path = tmp_path / "device.json"
    _write_min_device_config(cfg_path)
    monkeypatch.setenv("INKYPI_CONFIG_FILE", str(cfg_path))
    monkeypatch.setenv("PROJECT_DIR", str(tmp_path))
    monkeypatch.setattr(sys, "argv", ["inkypi.py", "--web-only"])
    sys.modules.pop("inkypi", None)
    inkypi = importlib.import_module("inkypi")
    app = inkypi.main(["--web-only"])
    assert app.config["RUNTIME_OPTIONS"].web_only is True
    assert app.config["WEB_ONLY"] is True
