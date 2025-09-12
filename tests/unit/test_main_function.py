import importlib
import sys
from tests.unit.test_secret_key import _write_min_device_config


def test_import_does_not_parse(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["inkypi.py", "--dev"])
    sys.modules.pop("inkypi", None)
    import inkypi
    assert inkypi.args is None
    assert inkypi.app is None


def test_main_invocation(tmp_path, monkeypatch):
    cfg_path = tmp_path / "device.json"
    _write_min_device_config(cfg_path)
    monkeypatch.setenv("INKYPI_CONFIG_FILE", str(cfg_path))
    monkeypatch.setenv("PROJECT_DIR", str(tmp_path))
    monkeypatch.setattr(sys, "argv", ["inkypi.py", "--web-only"])
    sys.modules.pop("inkypi", None)
    inkypi = importlib.import_module("inkypi")
    inkypi.main(["--web-only"])
    assert inkypi.args.web_only is True
    assert inkypi.app is not None
