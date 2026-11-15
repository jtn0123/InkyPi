"""Make test retries visible, and fail the run when too many tests need one.

Integration tests get one automatic retry (``tests/integration/conftest.py``).
pytest-rerunfailures only prints a ``RERUN <nodeid>`` line for a test that
failed and then passed, and drops the first attempt's error, so nobody can see
why it flaked. New flakiness then piles up unnoticed.

This plugin records every retried test and its first failure, prints them in
the terminal summary and the GitHub Actions job summary, and turns a passing
run into a failure when more distinct tests needed a retry than
``INKYPI_MAX_TEST_RERUNS`` allows (default :data:`DEFAULT_BUDGET`).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

import pytest

DEFAULT_BUDGET = 2
BUDGET_ENV = "INKYPI_MAX_TEST_RERUNS"
_ERROR_LINES = 15


def budget_from_env() -> int:
    raw = os.getenv(BUDGET_ENV, "").strip()
    if not raw:
        return DEFAULT_BUDGET
    try:
        return max(0, int(raw))
    except ValueError as exc:
        raise pytest.UsageError(
            f"{BUDGET_ENV} must be a whole number, got {raw!r}"
        ) from exc


def _last_lines(text: str, count: int) -> str:
    lines = [line for line in text.rstrip().splitlines() if line.strip()]
    return "\n".join(lines[-count:])


@dataclass
class RerunBudget:
    """Collects ``rerun`` reports on the controlling pytest process."""

    budget: int
    first_failures: dict[str, str] = field(default_factory=dict)
    over_budget: bool = False

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        # pytest types outcome as passed/failed/skipped; rerunfailures adds
        # "rerun" at runtime.
        outcome: str = report.outcome
        if outcome != "rerun":
            return
        # Keep the first failure: it is the one the retry hid.
        self.first_failures.setdefault(
            report.nodeid, _last_lines(report.longreprtext, _ERROR_LINES)
        )

    @pytest.hookimpl(tryfirst=True)
    def pytest_sessionfinish(self, session: pytest.Session, exitstatus: int) -> None:
        if len(self.first_failures) > self.budget and exitstatus == pytest.ExitCode.OK:
            self.over_budget = True
            session.exitstatus = pytest.ExitCode.TESTS_FAILED

    def pytest_terminal_summary(self, terminalreporter: Any) -> None:
        if not self.first_failures:
            return
        count = len(self.first_failures)
        terminalreporter.section("tests that passed only on a retry", sep="=")
        for nodeid, error in self.first_failures.items():
            terminalreporter.write_line(f"RETRIED {nodeid}")
            for line in error.splitlines():
                terminalreporter.write_line(f"    {line}")
        verdict = (
            f"{count} tests needed a retry; at most {self.budget} may "
            f"({BUDGET_ENV}). Failing the run."
            if self.over_budget
            else f"{count} of at most {self.budget} allowed retries used."
        )
        terminalreporter.write_line(verdict, red=self.over_budget, bold=True)
        self._write_step_summary(verdict)

    def _write_step_summary(self, verdict: str) -> None:
        path = os.getenv("GITHUB_STEP_SUMMARY")
        if not path:
            return
        parts = ["### Tests that passed only on a retry", "", verdict, ""]
        for nodeid, error in self.first_failures.items():
            parts += [
                "<details>",
                f"<summary><code>{nodeid}</code></summary>",
                "",
                "```text",
                error.replace("```", "'''"),
                "```",
                "</details>",
                "",
            ]
        try:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write("\n".join(parts) + "\n")
        except OSError:
            pass


def register(config: pytest.Config) -> None:
    """Install the plugin on the controlling process (not on xdist workers)."""
    if hasattr(config, "workerinput"):
        return
    config.pluginmanager.register(RerunBudget(budget_from_env()), "inkypi-rerun-budget")
