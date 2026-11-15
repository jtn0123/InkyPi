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


def _run_mypy(sample: Path) -> str:
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
    return result.stdout + result.stderr


def test_mypy_actually_reports_strict_errors(tmp_path: Path) -> None:
    """Run mypy with the repo config on an untyped function."""
    sample = tmp_path / "untyped_sample.py"
    sample.write_text("def f(x):\n    return x\n", encoding="utf-8")

    assert "[no-untyped-def]" in _run_mypy(sample)


def test_missing_imports_are_not_ignored_wholesale() -> None:
    """Untyped libraries are named in mypy.ini, one section per group.

    A global ``ignore_missing_imports`` turns every new import without types
    into a silent ``Any``, including a library whose stub package was simply
    never added to requirements-dev.
    """
    assert not _config().getboolean("mypy", "ignore_missing_imports", fallback=False)


def test_an_unlisted_import_without_types_fails(tmp_path: Path) -> None:
    sample = tmp_path / "unlisted_import.py"
    sample.write_text("import inkypi_no_such_library\n", encoding="utf-8")

    assert "[import-not-found]" in _run_mypy(sample)


_EXTRA_CHECKS_SAMPLE = """\
from warnings import deprecated


class Thing:
    pass


def redundant(s: str) -> bool:
    return isinstance(s, str) and bool(s)


def truthy(t: Thing) -> int:
    return 1 if t else 0


def maybe_unbound(flag: bool) -> int:
    if flag:
        n = 1
    return n


@deprecated("use something else")
def old() -> None:
    pass


old()
x: int = "a"  # type: ignore
"""


def test_checks_beyond_strict_are_enabled(tmp_path: Path) -> None:
    """mypy.ini turns on error codes that ``strict`` leaves off.

    Each has found dead or misleading code in this repo; dropping one from
    ``enable_error_code`` should fail here rather than pass unnoticed.
    """
    sample = tmp_path / "extra_checks_sample.py"
    sample.write_text(_EXTRA_CHECKS_SAMPLE, encoding="utf-8")
    output = _run_mypy(sample)

    for code in (
        "redundant-expr",
        "truthy-bool",
        "possibly-undefined",
        "deprecated",
        "ignore-without-code",
    ):
        assert f"[{code}]" in output, f"[{code}] not reported:\n{output}"
