"""Tests for scripts/mutation_summary.py (D1: readable nightly mutation score)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.mutation_summary import main, summarise


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
    assert "| Not run (time budget) | 100 |" in out
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
