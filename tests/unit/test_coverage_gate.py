"""Tests for scripts/coverage_gate.py (per-file and per-package floors)."""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

GATE = Path(__file__).resolve().parents[2] / "scripts" / "coverage_gate.py"


def _load_gate() -> ModuleType:
    spec = importlib.util.spec_from_file_location("_inkypi_coverage_gate", GATE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolve annotations via it
    spec.loader.exec_module(module)
    return module


gate = _load_gate()


def _line(number: int, hits: int, branch: str | None = None) -> str:
    if branch is None:
        return f'<line number="{number}" hits="{hits}"/>'
    return (
        f'<line number="{number}" hits="{hits}" branch="true" '
        f'condition-coverage="{branch}"/>'
    )


def _write_xml(tmp_path: Path, files: dict[str, list[str]]) -> Path:
    classes = "".join(
        f'<class name="{Path(name).name}" filename="{name}" line-rate="0" '
        f'branch-rate="0"><methods/><lines>{"".join(lines)}</lines></class>'
        for name, lines in files.items()
    )
    xml = (
        '<?xml version="1.0" ?><coverage version="7"><packages>'
        f'<package name="src"><classes>{classes}</classes></package>'
        "</packages></coverage>"
    )
    path = tmp_path / "coverage.xml"
    path.write_text(xml, encoding="utf-8")
    return path


def test_file_floor_passes_and_fails(tmp_path: Path) -> None:
    xml = _write_xml(
        tmp_path,
        {"a.py": [_line(1, 1), _line(2, 1), _line(3, 0, "50% (1/2)"), _line(4, 1)]},
    )
    failures, report = gate.check(xml, {"a.py": (0.75, 0.5)})
    assert failures == []
    assert report and report[0].startswith("a.py: line=75.0%")

    failures, _ = gate.check(xml, {"a.py": (0.80, 0.6)})
    assert len(failures) == 2
    assert "line-rate 75.0% < required 80.0%" in failures[0]
    assert "branch-rate 50.0% < required 60.0%" in failures[1]


def test_package_floor_sums_files_including_subpackages(tmp_path: Path) -> None:
    xml = _write_xml(
        tmp_path,
        {
            "pkg/a.py": [_line(1, 1), _line(2, 1), _line(3, 1)],
            "pkg/sub/b.py": [_line(1, 0)],
            "other.py": [_line(1, 0), _line(2, 0)],
        },
    )
    # pkg/ = 3 of 4 lines covered; other.py must not be counted.
    failures, report = gate.check(xml, {"pkg/": (0.75, 1.0)})
    assert failures == []
    assert "pkg/: line=75.0%" in report[0]

    failures, _ = gate.check(xml, {"pkg/": (0.76, 1.0)})
    assert failures and "pkg/: line-rate 75.0%" in failures[0]


def test_missing_target_fails(tmp_path: Path) -> None:
    xml = _write_xml(tmp_path, {"a.py": [_line(1, 1)]})
    failures, _ = gate.check(xml, {"b.py": (0.1, 0.1), "nope/": (0.1, 0.1)})
    assert failures == [
        "b.py: missing from coverage report",
        "nope/: missing from coverage report",
    ]


def test_main_profiles_and_exit_codes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Coverage that clears the preflash subset floors but not the full ones.
    lines = [_line(i, 1 if i <= 85 else 0) for i in range(1, 101)]
    lines.append(_line(101, 1, "75% (3/4)"))
    xml = _write_xml(
        tmp_path,
        {
            "refresh_task/task.py": lines,
            "refresh_task/refresh_cycle.py": lines,
            "refresh_task/command_queue.py": lines,
            "refresh_task/loop_scheduling.py": lines,
            "display/display_manager.py": lines,
            "config.py": lines,
        },
    )
    assert gate.main(["--profile", "preflash", str(xml)]) == 0
    assert gate.main([str(xml)]) == 1
    err = capsys.readouterr().err
    assert "refresh_task/task.py: line-rate" in err
    assert "app_setup/auth.py: missing from coverage report" in err


def test_full_floors_cover_critical_modules() -> None:
    floors = gate.FULL_THRESHOLDS
    for target in (
        "refresh_task/",
        "display/",
        "blueprints/",
        "app_setup/",
        "app_setup/auth.py",
        "app_setup/security_middleware.py",
        "utils/boot_self_test.py",
        "utils/blackout.py",
        "utils/asset_check.py",
    ):
        assert target in floors
    for min_line, min_branch in floors.values():
        assert 0 < min_line <= 1 and 0 < min_branch <= 1


def test_main_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="coverage xml not found"):
        gate.main([str(tmp_path / "absent.xml")])
