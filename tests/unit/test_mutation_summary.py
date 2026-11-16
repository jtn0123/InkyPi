"""Tests for scripts/mutation_summary.py: the nightly's score and its floor."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.mutation_summary import (
    Floor,
    compare,
    load_floors,
    main,
    score_of,
    summarise,
)

ROOT = Path(__file__).resolve().parents[2]
COMPLETE = {"killed": 60, "timeout": 0, "survived": 40, "total": 100}
PARTIAL = {"killed": 60, "survived": 40, "total": 150}


def test_score_counts_only_mutants_that_ran() -> None:
    stats = {
        "killed": 70,
        "timeout": 5,
        "survived": 20,
        "no_tests": 5,
        "suspicious": 0,
        "segfault": 0,
        "check_was_interrupted_by_user": 0,
        "skipped": 10,
        "total": 210,
    }
    out = summarise(stats, "utils")
    # 210 total - 110 recorded = 100 never reached; 100 ran (10 skipped).
    assert out.startswith("### Mutation score (utils): 75.0%\n")
    assert "75 of 100 mutants that ran were caught by a test." in out
    assert "| Not run yet | 100 |" in out
    assert "| **Total** | 210 |" in out


def test_complete_run_has_no_not_run_row() -> None:
    stats = {"killed": 9, "survived": 1, "total": 10}
    out = summarise(stats, "blueprints")
    assert "90.0%" in out
    assert "Not run" not in out


def test_nothing_ran_reports_na() -> None:
    out = summarise({"total": 0}, "app-setup")
    assert "### Mutation score (app-setup): n/a" in out


def test_bad_counts_are_treated_as_zero() -> None:
    out = summarise({"killed": "x", "survived": None, "total": True}, "x")
    assert "| **Total** | 0 |" in out
    assert "n/a" in out


def test_main_reports_missing_stats_without_failing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([str(tmp_path / "missing.json"), "refresh-task"]) == 0
    assert "no results" in capsys.readouterr().out


def test_main_reports_unreadable_stats_without_failing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = tmp_path / "stats.json"
    bad.write_text("{not json", encoding="utf-8")
    assert main([str(bad), "utils"]) == 0
    assert "Could not read" in capsys.readouterr().out


def test_main_prints_the_summary(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stats = tmp_path / "stats.json"
    stats.write_text(json.dumps({"killed": 1, "total": 1}), encoding="utf-8")
    assert main([str(stats), "utils"]) == 0
    assert "100.0%" in capsys.readouterr().out


def test_main_without_arguments_is_a_usage_error() -> None:
    assert main([]) == 2


def test_complete_run_more_than_two_points_under_a_complete_floor_fails() -> None:
    verdict = compare(score_of(COMPLETE), "utils", Floor(62.1, True, "x"), 2.0)
    assert verdict.failed
    assert "fell to 60.0%, 2.1 points under its 62.1% floor" in verdict.message


def test_drop_of_exactly_the_allowance_passes() -> None:
    verdict = compare(score_of(COMPLETE), "utils", Floor(62.0, True, "x"), 2.0)
    assert not verdict.failed
    assert "within 2.0 points" in verdict.message


def test_score_above_the_floor_asks_to_raise_it() -> None:
    verdict = compare(score_of(COMPLETE), "utils", Floor(55.0, True, "x"), 2.0)
    assert not verdict.failed
    assert "Raise the floor" in verdict.message


def test_partial_run_is_never_compared() -> None:
    # 50 of 150 mutants have no result: the score covers the fastest ones
    # only, so even a large gap is not a regression.
    verdict = compare(score_of(PARTIAL), "utils", Floor(90.0, True, "x"), 2.0)
    assert not verdict.failed
    assert "50 of 150 mutants have no result yet" in verdict.message


def test_missing_floor_reports_the_score_to_record() -> None:
    verdict = compare(score_of(COMPLETE), "core", Floor(None, False, None), 2.0)
    assert not verdict.failed
    assert '"score": 60.0, "complete": true' in verdict.message


def test_floor_from_a_partial_run_is_not_enforced() -> None:
    floor = Floor(70.0, False, "nightly 2026-11-15: 559 of 1169 mutants ran")
    verdict = compare(score_of(COMPLETE), "app-setup", floor, 2.0)
    assert not verdict.failed
    assert "came from a partial run" in verdict.message
    assert '"score": 60.0, "complete": true' in verdict.message


def test_shard_without_an_entry_fails() -> None:
    verdict = compare(score_of(COMPLETE), "new-shard", None, 2.0)
    assert verdict.failed


def test_committed_floors_load() -> None:
    allowed_drop, floors = load_floors(ROOT / "scripts/mutation_scores.json")
    assert allowed_drop == 2.0
    assert floors["blueprints"] == Floor(
        61.7,
        False,
        "nightly 2026-11-15 (CI run 43733926724): 5615 of 5874 mutants ran",
    )
    assert floors["core"] == Floor(None, False, None)


def _floors_file(tmp_path: Path, score: float | None, complete: bool) -> Path:
    path = tmp_path / "floors.json"
    path.write_text(
        json.dumps(
            {
                "allowed_drop": 2.0,
                "shards": {
                    "utils": {"score": score, "complete": complete, "measured": "m"}
                },
            }
        ),
        encoding="utf-8",
    )
    return path


def _stats_file(tmp_path: Path, stats: dict[str, int]) -> Path:
    path = tmp_path / "stats.json"
    path.write_text(json.dumps(stats), encoding="utf-8")
    return path


def test_check_exits_1_with_an_error_annotation_on_a_drop(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stats = _stats_file(tmp_path, COMPLETE)
    floors = _floors_file(tmp_path, 65.0, True)
    assert main([str(stats), "utils", "--floors", str(floors), "--check"]) == 1
    assert capsys.readouterr().out.startswith("::error title=Mutation score (utils)::")


def test_check_passes_with_a_notice_when_there_is_no_floor(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stats = _stats_file(tmp_path, COMPLETE)
    floors = _floors_file(tmp_path, None, False)
    assert main([str(stats), "utils", "--floors", str(floors), "--check"]) == 0
    assert capsys.readouterr().out.startswith("::notice ")


def test_summary_with_floors_shows_the_verdict_and_never_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stats = _stats_file(tmp_path, COMPLETE)
    floors = _floors_file(tmp_path, 65.0, True)
    assert main([str(stats), "utils", "--floors", str(floors)]) == 0
    out = capsys.readouterr().out
    assert out.startswith("### Mutation score (utils): 60.0%\n")
    assert "5.0 points under its 65.0% floor" in out


def test_check_without_floors_is_a_usage_error(tmp_path: Path) -> None:
    stats = _stats_file(tmp_path, COMPLETE)
    assert main([str(stats), "utils", "--check"]) == 2


def test_check_without_stats_does_not_fail(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    floors = _floors_file(tmp_path, 65.0, True)
    missing = tmp_path / "missing.json"
    assert main([str(missing), "utils", "--floors", str(floors), "--check"]) == 0
    assert "no results" in capsys.readouterr().out
