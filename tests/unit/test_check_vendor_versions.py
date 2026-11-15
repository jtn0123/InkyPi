"""The weekly vendor-version check reads the real pins and the right policy (F7)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load() -> ModuleType:
    path = ROOT / "scripts" / "check_vendor_versions.py"
    spec = importlib.util.spec_from_file_location("check_vendor_versions", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # dataclasses look the defining module up in sys.modules.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


cvv = _load()


def test_reads_every_vendored_library_from_the_real_files() -> None:
    packages = {pin.package for pin in cvv.all_pins()}

    assert {"chart.js", "fullcalendar", "swagger-ui-dist"} <= packages


def test_expands_version_variables_in_update_vendors() -> None:
    text = (
        'LIB_VERSION="1.2.3"\n'
        "declare -a VENDORS=(\n"
        '  "Lib|https://cdn.jsdelivr.net/npm/@scope/lib@${LIB_VERSION}/x.js|out.js|ab"\n'
        ")\n"
    )

    [pin] = cvv.pins_from_update_vendors(text)

    assert (pin.package, pin.version) == ("@scope/lib", "1.2.3")


def test_rejects_a_url_it_cannot_check() -> None:
    with pytest.raises(ValueError, match="not an npm CDN URL"):
        cvv.pins_from_cdn_manifest('{"x": {"url": "https://example.com/x.js"}}')


def _pin(version: str) -> object:
    return cvv.Pin("lib", version, "test")


def _releases(*versions: str) -> object:
    return lambda _package: list(versions)


def test_current_within_its_major_passes_and_lists_a_new_major() -> None:
    lines, code = cvv.check(
        [_pin("6.1.22")], _releases("6.1.17", "6.1.22", "7.0.0-beta.1", "7.1.5")
    )

    assert code == 0
    assert "| lib | 6.1.22 | 6.1.22 | 7.1.5 | test |" in lines


def test_a_newer_release_in_the_pinned_major_fails() -> None:
    lines, code = cvv.check([_pin("4.5.1")], _releases("4.5.1", "4.6.1", "4.10.0"))

    assert code == 1
    assert "| lib | 4.5.1 | **4.10.0** |  | test |" in lines


def test_prereleases_are_ignored() -> None:
    _lines, code = cvv.check([_pin("5.0.0")], _releases("5.0.0", "5.1.0-rc.1"))

    assert code == 0


def test_a_failed_lookup_is_reported_not_raised() -> None:
    def broken(_package: str) -> list[str]:
        raise OSError("offline")

    lines, code = cvv.check([_pin("1.0.0")], broken)

    assert code == 2
    assert any("lookup failed: offline" in line for line in lines)
