"""Exercise serial success/failure and process cleanup with a real subprocess."""

import importlib.util
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "verify_pi_image_boot", ROOT / "scripts/verify_pi_image_boot.py"
)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.mark.parametrize(
    ("serial", "expected"),
    [
        ("Debian GNU/Linux\ninkypi login: ", True),
        ("kernel panic", False),
        ("command: echo login:\n", False),
    ],
)
def test_serial_result(tmp_path: Path, serial: str, expected: bool) -> None:
    assert (
        module.verify_boot(
            [sys.executable, "-c", f"print({serial!r}, flush=True)"],
            tmp_path / "serial.log",
            2,
        )
        is expected
    )


@pytest.mark.parametrize("serial", ["inkypi login: ", "starting boot"])
def test_live_process_is_reaped(tmp_path: Path, serial: str) -> None:
    pid_path = tmp_path / "pid"
    code = (
        "import os,time; from pathlib import Path; "
        f"Path({str(pid_path)!r}).write_text(str(os.getpid())); "
        f"print({serial!r},flush=True); time.sleep(30)"
    )
    expected = "login:" in serial
    assert (
        module.verify_boot([sys.executable, "-c", code], tmp_path / "serial.log", 0.5)
        is expected
    )
    pid = int(pid_path.read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
