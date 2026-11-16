"""Tests for scripts/mutation_check.py, the narrow PR mutation gate (D8)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml
from scripts import mutation_check
from scripts.mutation_check import Mutant, MutantResult, check_mutant

ROOT = Path(__file__).resolve().parents[2]

# Exit 0 when flag.VALUE is 1, so a mutation of the value fails it.
CHECKS_FLAG = (
    sys.executable,
    "-c",
    "import sys, flag; sys.exit(0 if flag.VALUE == 1 else 1)",
)
ALWAYS_PASSES = (sys.executable, "-c", "pass")
ALWAYS_FAILS = (sys.executable, "-c", "raise SystemExit(3)")


@pytest.fixture
def tiny_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "flag.py").write_text("VALUE = 1\n", encoding="utf-8")
    return repo


def _mutant(*commands: tuple[str, ...], linux_only: bool = False) -> Mutant:
    return Mutant(
        name="flag-flipped",
        file="src/flag.py",
        old="VALUE = 1\n",
        new="VALUE = 2\n",
        commands=commands,
        linux_only=linux_only,
    )


def test_a_test_that_fails_only_with_the_mutation_kills_it(tiny_repo: Path) -> None:
    assert check_mutant(_mutant(CHECKS_FLAG), tiny_repo).status == "killed"


def test_a_command_that_passes_with_the_mutation_lets_it_survive(
    tiny_repo: Path,
) -> None:
    assert check_mutant(_mutant(ALWAYS_PASSES), tiny_repo).status == "survived"


def test_a_command_that_fails_without_the_mutation_is_broken_not_killed(
    tiny_repo: Path,
) -> None:
    result = check_mutant(_mutant(ALWAYS_FAILS), tiny_repo)
    assert result.status == "broken"
    assert "exited 3 on the unmutated code" in result.detail


def test_any_failing_command_kills_the_mutant(tiny_repo: Path) -> None:
    # The first command passes either way; the second one catches the bug.
    result = check_mutant(_mutant(ALWAYS_PASSES, CHECKS_FLAG), tiny_repo)
    assert result.status == "killed"


def test_same_length_mutation_is_not_masked_by_cached_bytecode(
    tiny_repo: Path,
) -> None:
    # "VALUE = 1" -> "VALUE = 2" keeps the file size, and the baseline run has
    # just compiled the unmutated file, so a stale .pyc could hide the change.
    mutant = _mutant(CHECKS_FLAG)
    assert len(mutant.old) == len(mutant.new)
    assert check_mutant(mutant, tiny_repo).status == "killed"


def test_linux_only_mutant_is_skipped_elsewhere(
    tiny_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    result = check_mutant(_mutant(ALWAYS_FAILS, linux_only=True), tiny_repo)
    assert result == MutantResult("flag-flipped", "skipped", "needs Linux")


def test_main_fails_on_a_broken_or_surviving_mutant(
    tiny_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert mutation_check.main([_mutant(CHECKS_FLAG)], tiny_repo) == 0
    assert mutation_check.main([_mutant(ALWAYS_PASSES)], tiny_repo) == 1
    assert mutation_check.main([_mutant(ALWAYS_FAILS)], tiny_repo) == 1
    err = capsys.readouterr().err
    assert "Add or fix a test" in err
    assert "the commands fail without the mutation" in err


def test_the_install_idempotency_mutant_is_linux_only() -> None:
    by_name = {mutant.name: mutant for mutant in mutation_check.MUTANTS}
    assert by_name["install-idempotency-assert-weakened"].linux_only
    assert not by_name["cache-hit-inverted"].linux_only


def test_preflash_job_turns_the_gate_on() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    steps = workflow["jobs"]["preflash-validate"]["steps"]
    run_step = next(s for s in steps if s.get("name") == "Run pre-flash validation")
    assert run_step["env"]["INKYPI_VALIDATE_MUTATION"] == "1"


def test_every_test_file_a_mutant_runs_exists() -> None:
    for mutant in mutation_check.MUTANTS:
        for command in mutant.commands:
            for arg in command:
                if arg.startswith(("tests/", "scripts/")):
                    assert (ROOT / arg).is_file(), f"{mutant.name}: {arg} is missing"
