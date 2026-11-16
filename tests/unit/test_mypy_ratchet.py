"""scripts/mypy_ratchet.py: lint.sh's per-fingerprint mypy baselines."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load() -> ModuleType:
    path = ROOT / "scripts" / "mypy_ratchet.py"
    spec = importlib.util.spec_from_file_location("mypy_ratchet", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # dataclasses resolve the module's string annotations through sys.modules.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ratchet = _load()

HEADER = "# Baseline for tests/.\n#\n# History: kept by --update.\n"


def _record(
    file: str, line: int, code: str | None, *, severity: str = "error", hint: str = ""
) -> str:
    return json.dumps(
        {
            "file": file,
            "line": line,
            "column": 4,
            "message": f"problem at {line}",
            "hint": hint or None,
            "code": code,
            "severity": severity,
        }
    )


def _errors(*specs: tuple[str, int, str]) -> list[object]:
    return [
        ratchet.MypyError(file, line, 4, code, f"problem at {line}")
        for file, line, code in specs
    ]


def _baseline(tmp_path: Path, entries: str = "") -> Path:
    path = tmp_path / "baseline.txt"
    path.write_text(HEADER + ("\n" + entries if entries else ""))
    return path


def _main(baseline: Path, errors: list[object], *extra: str) -> tuple[int, list[str]]:
    targets: list[str] = []

    def run(target: str) -> list[object]:
        targets.append(target)
        return errors

    code = ratchet.main(["tests", str(baseline), *extra], run=run)
    assert targets == ["tests"]
    return code, targets


# ---------------------------------------------------------------------------
# Reading mypy's JSON output
# ---------------------------------------------------------------------------


def test_reads_errors_and_skips_notes() -> None:
    stdout = "\n".join(
        [
            _record("tests/a.py", 3, "arg-type", hint="Did you mean x?"),
            _record("tests/a.py", 3, None, severity="note"),
            "",
            _record(str(ROOT / "tests" / "b.py"), 9, "attr-defined"),
        ]
    )
    errors = ratchet.parse_mypy_output(stdout)
    assert [e.fingerprint for e in errors] == [
        "tests/a.py:arg-type",
        # An absolute path is made relative to the repo, as mypy usually prints.
        "tests/b.py:attr-defined",
    ]
    assert str(errors[0]) == (
        "tests/a.py:3:4: problem at 3  [arg-type]\n    Did you mean x?"
    )


def test_output_that_is_not_json_is_an_error() -> None:
    with pytest.raises(ratchet.RatchetError, match="isn't JSON"):
        ratchet.parse_mypy_output("mypy.ini: [mypy]: Unrecognized option")


@pytest.mark.parametrize(
    ("returncode", "stdout", "message"),
    [
        (2, "", "failed \\(exit 2\\)"),
        (1, "", "without reporting an error"),
    ],
)
def test_a_mypy_run_with_no_result_is_an_error(
    monkeypatch: pytest.MonkeyPatch, returncode: int, stdout: str, message: str
) -> None:
    def run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess([], returncode, stdout, "crash\n")

    monkeypatch.setattr(ratchet.subprocess, "run", run)
    with pytest.raises(ratchet.RatchetError, match=message):
        ratchet.run_mypy("tests")


def test_a_clean_run_has_no_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(ratchet.subprocess, "run", run)
    assert ratchet.run_mypy("src") == []
    assert calls == [[sys.executable, "-m", "mypy", "-O", "json", "src"]]


# ---------------------------------------------------------------------------
# The baseline file
# ---------------------------------------------------------------------------


def test_baseline_keeps_its_header_and_round_trips() -> None:
    counts = Counter({"tests/b.py:misc": 1, "tests/a.py:arg-type": 2})
    text = ratchet.render_baseline(HEADER.splitlines(), counts)
    assert text == HEADER + "\ntests/a.py:arg-type 2\ntests/b.py:misc 1\n"
    parsed = ratchet.parse_baseline(text, "baseline.txt")
    assert parsed.counts == counts
    assert ratchet.render_baseline(parsed.header, parsed.counts) == text
    # An empty list is just the header: src/ and scripts/ are clean.
    assert ratchet.render_baseline(HEADER.splitlines(), Counter()) == HEADER


@pytest.mark.parametrize(
    ("entries", "message"),
    [
        ("450\n", "expected 'path:error-code count'"),
        ("tests/a.py:misc\n", "expected 'path:error-code count'"),
        ("tests/a.py:misc 0\n", "expected 'path:error-code count'"),
        ("tests/a.py:misc 1\ntests/a.py:misc 2\n", "listed twice"),
        ("tests/a.py:misc 1\n# a note\n", "comments go in the header"),
    ],
)
def test_a_malformed_baseline_is_rejected(entries: str, message: str) -> None:
    with pytest.raises(ratchet.RatchetError, match=message):
        ratchet.parse_baseline(HEADER + entries, "baseline.txt")


# ---------------------------------------------------------------------------
# Comparing
# ---------------------------------------------------------------------------


def test_matching_fingerprints_pass(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    baseline = _baseline(tmp_path, "tests/a.py:arg-type 2\n")
    errors = _errors(("tests/a.py", 1, "arg-type"), ("tests/a.py", 5, "arg-type"))

    code, _ = _main(baseline, errors)

    assert code == 0
    assert "2 error(s) in 1 fingerprint(s)" in capsys.readouterr().out


def test_a_new_error_fails_even_when_another_was_fixed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The total stays at 2, which the old count-only ratchet accepted.
    baseline = _baseline(
        tmp_path, "tests/a.py:arg-type 1\ntests/b.py:misc 1\ntests/c.py:misc 1\n"
    )
    errors = _errors(
        ("tests/a.py", 1, "arg-type"),
        ("tests/a.py", 8, "arg-type"),
        ("tests/c.py", 2, "misc"),
    )

    code, _ = _main(baseline, errors)

    out = capsys.readouterr().out
    assert code == 1
    assert "tests/a.py:arg-type: 2 error(s), baseline 1" in out
    assert "tests/a.py:8:4: problem at 8  [arg-type]" in out
    assert "tests/b.py:misc: 0 error(s), baseline 1" in out
    assert "--update" in out
    # Unchanged fingerprints aren't printed.
    assert "tests/c.py" not in out


def test_a_vanished_fingerprint_fails_until_the_baseline_is_updated(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    baseline = _baseline(tmp_path, "tests/a.py:arg-type 1\ntests/b.py:misc 1\n")
    errors = _errors(("tests/a.py", 1, "arg-type"))

    assert _main(baseline, errors)[0] == 1
    assert "fixed errors still listed" in capsys.readouterr().out

    assert _main(baseline, errors, "--update")[0] == 0
    assert baseline.read_text() == HEADER + "\ntests/a.py:arg-type 1\n"
    assert _main(baseline, errors)[0] == 0


def test_an_empty_baseline_fails_on_any_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    baseline = _baseline(tmp_path)

    assert _main(baseline, [])[0] == 0
    assert "clean" in capsys.readouterr().out
    assert _main(baseline, _errors(("src/x.py", 3, "no-any-return")))[0] == 1
    assert "src/x.py:3:4" in capsys.readouterr().out


def test_a_mypy_failure_fails_the_ratchet(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def crash(target: str) -> list[object]:
        raise ratchet.RatchetError("mypy tests failed (exit 2)")

    code = ratchet.main(["tests", str(_baseline(tmp_path))], run=crash)

    assert code == 1
    assert "exit 2" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# The real baselines and lint.sh
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("target", ["src", "tests", "scripts"])
def test_checked_in_baselines_parse(target: str) -> None:
    path = ROOT / "scripts" / f"mypy_{target}_baseline.txt"
    baseline = ratchet.parse_baseline(path.read_text(), path.name)
    assert any("--update" in line for line in baseline.header)
    assert all(fp.startswith(f"{target}/") for fp in baseline.counts)
    if target in ("src", "scripts"):
        assert baseline.counts == Counter(), f"{target}/ must stay clean"


def test_lint_runs_one_ratchet_for_all_three_directories() -> None:
    lint = (ROOT / "scripts" / "lint.sh").read_text()
    assert lint.count("python scripts/mypy_ratchet.py") == 1
    for target in ("src", "tests", "scripts"):
        upper = target.upper()
        assert f'run_mypy_ratchet {target} "$MYPY_{upper}_BASELINE_FILE"' in lint
    assert "count_mypy_errors" not in lint
