"""The installer's own requirement files must agree with uv.lock (F2)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]
H1 = "sha256:" + "1" * 64
H2 = "sha256:" + "2" * 64


def _load() -> ModuleType:
    path = ROOT / "scripts" / "check_install_pins.py"
    spec = importlib.util.spec_from_file_location("check_install_pins", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


cip = _load()


def test_the_committed_files_agree_with_the_lock() -> None:
    assert cip.main() == 0


def test_reads_versions_and_every_hash() -> None:
    pins = cip.read_pins(
        f"RPi.GPIO==0.7.1 \\\n    --hash={H1} \\\n    --hash={H2}\nuv==1.0 \\\n"
        f"    --hash={H2}\n"
    )
    assert pins == {"rpi-gpio": ("0.7.1", {H1, H2}), "uv": ("1.0", {H2})}


def test_a_pin_behind_the_lock_fails() -> None:
    # pip 26.2.1 in bootstrap-requirements.txt while the lock had 26.3.
    lock = cip.read_lock((ROOT / "uv.lock").read_text(encoding="utf-8"))
    old = cip.read_pins(f"pip==26.2.1 \\\n    --hash={H1}\n")
    [problem] = cip.check({"bootstrap": old}, lock)
    assert "pip==26.2.1, but uv.lock has" in problem


def test_a_hash_the_lock_does_not_list_fails() -> None:
    problems = cip.check({"f": {"uv": ("1.0", {H1, H2})}}, {"uv": ("1.0", {H1})})
    assert problems == [f"f: uv==1.0 has hashes uv.lock doesn't list: {H2}"]


def test_two_files_pinning_one_package_differently_fails() -> None:
    files = {
        "bootstrap": {"setuptools": ("84.2.1", {H1})},
        "ws": {"setuptools": ("84.0.0", {H2})},
    }
    assert cip.check(files, {}) == ["ws: setuptools==84.0.0, but bootstrap pins 84.2.1"]
