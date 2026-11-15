"""mypy runs in strict mode, and the config says so in one place.

mypy applies ``strict = True`` from any section of mypy.ini to the whole run,
so a per-module ``[mypy-x] strict = True`` list looks selective but is not.
The repo once kept 22 such sections and documented them as "the strict
subset" while every module was strict. Removing the last of them would have
dropped the whole check to non-strict without a single failing test.
"""

from __future__ import annotations

import configparser
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MYPY_INI = ROOT / "mypy.ini"


def _config() -> configparser.ConfigParser:
    parser = configparser.ConfigParser()
    parser.read(MYPY_INI, encoding="utf-8")
    return parser


def test_strict_is_set_once_in_the_global_section() -> None:
    config = _config()

    assert config.getboolean("mypy", "strict", fallback=False)
    per_module = [s for s in config.sections() if s != "mypy" and "strict" in config[s]]
    assert per_module == [], (
        f"{per_module}: a per-module `strict` applies to every module; "
        "set strict once under [mypy]"
    )


def test_strict_flags_are_not_switched_back_off() -> None:
    relaxed = {
        f"[{section}] {key}"
        for section in _config().sections()
        for key, value in _config()[section].items()
        if key.startswith(("disallow_", "check_untyped", "warn_return_any"))
        and value.strip().lower() == "false"
    }

    assert relaxed == set()


def test_mypy_actually_reports_strict_errors(tmp_path: Path) -> None:
    """Run mypy with the repo config on an untyped function."""
    sample = tmp_path / "untyped_sample.py"
    sample.write_text("def f(x):\n    return x\n", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "mypy",
            "--config-file",
            str(MYPY_INI),
            "--no-incremental",
            str(sample),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )

    assert "[no-untyped-def]" in result.stdout, result.stdout + result.stderr
