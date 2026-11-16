#!/usr/bin/env python3
"""Report one mutmut shard's results, and compare its score with the floor.

Reads the JSON that ``mutmut export-cicd-stats`` writes
(``mutants/mutmut-cicd-stats.json``). Run it through
``scripts/mutmut_shard.py`` so the counts cover that shard's mutants only.

The score is the share of mutants that actually ran which a test caught
(killed, or timed out, which mutmut also counts as caught). Mutants with no
result yet are listed as "Not run yet" instead of dragging the score down.

Floors live in ``scripts/mutation_scores.json``. A score is compared only
when every mutant in the shard has a result: a partial run tests the fastest
mutants first, and its score moved by up to 4 points between nights with no
change in test quality. ``--check`` fails (exit 1) when a complete run's
score is more than ``allowed_drop`` points under a floor that was itself
measured on a complete run. A floor that is missing, or came from a partial
run, never fails: the check prints the complete score to record instead.

Usage:
    python scripts/mutation_summary.py STATS LABEL [--floors FILE]
    python scripts/mutation_summary.py STATS LABEL --floors FILE --check
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# (stats key, row title), in the order the table shows them.
ROWS: tuple[tuple[str, str], ...] = (
    ("killed", "Killed"),
    ("timeout", "Timed out (counts as caught)"),
    ("survived", "Survived"),
    ("no_tests", "No covering test"),
    ("suspicious", "Suspicious"),
    ("segfault", "Segfault"),
    ("check_was_interrupted_by_user", "Interrupted"),
    ("skipped", "Skipped"),
)


def _count(stats: Mapping[str, object], key: str) -> int:
    value = stats.get(key, 0)
    if isinstance(value, bool) or not isinstance(value, int | str):
        return 0
    try:
        return max(int(value), 0)
    except ValueError:
        return 0


@dataclass(frozen=True)
class Score:
    total: int
    not_run: int
    ran: int
    caught: int

    @property
    def percent(self) -> float | None:
        return round(self.caught / self.ran * 100, 1) if self.ran > 0 else None

    @property
    def complete(self) -> bool:
        return self.ran > 0 and self.not_run == 0


def score_of(stats: Mapping[str, object]) -> Score:
    total = _count(stats, "total")
    recorded = sum(_count(stats, key) for key, _ in ROWS)
    not_run = max(total - recorded, 0)
    ran = max(total - not_run - _count(stats, "skipped"), 0)
    caught = _count(stats, "killed") + _count(stats, "timeout")
    return Score(total=total, not_run=not_run, ran=ran, caught=caught)


@dataclass(frozen=True)
class Floor:
    score: float | None
    complete: bool
    measured: str | None


@dataclass(frozen=True)
class Verdict:
    failed: bool
    message: str


def load_floors(path: Path) -> tuple[float, dict[str, Floor]]:
    """Return ``(allowed_drop, floors by shard label)`` from the floors file."""
    data: Any = json.loads(path.read_text(encoding="utf-8"))
    allowed_drop = float(data["allowed_drop"])
    floors: dict[str, Floor] = {}
    for label, entry in data["shards"].items():
        score = entry["score"]
        floors[label] = Floor(
            score=None if score is None else float(score),
            complete=bool(entry["complete"]),
            measured=entry.get("measured"),
        )
    return allowed_drop, floors


def compare(
    score: Score, label: str, floor: Floor | None, allowed_drop: float
) -> Verdict:
    """Decide whether ``score`` is a regression against ``floor``."""
    if floor is None:
        return Verdict(
            True,
            f"Shard `{label}` has no entry in scripts/mutation_scores.json. "
            "Add one (score null) so its score is tracked.",
        )
    current = score.percent
    if current is None:
        return Verdict(False, f"No mutants ran for `{label}`, so there is no score.")
    if not score.complete:
        return Verdict(
            False,
            f"{score.not_run} of {score.total} mutants have no result yet, so "
            f"{current}% is not compared with the floor. The nightly resumes "
            "from this run's results and compares once every mutant has one.",
        )
    if floor.score is None:
        return Verdict(
            False,
            f"No floor recorded for `{label}` yet. Record this complete score: "
            f'"score": {current}, "complete": true.',
        )
    if not floor.complete:
        return Verdict(
            False,
            f"The {floor.score}% floor for `{label}` came from a partial run "
            f"({floor.measured}), so it is not enforced. Record this complete "
            f'score: "score": {current}, "complete": true.',
        )
    drop = round(floor.score - current, 1)
    if drop > allowed_drop:
        return Verdict(
            True,
            f"Mutation score for `{label}` fell to {current}%, {drop} points "
            f"under its {floor.score}% floor (allowed drop {allowed_drop}). "
            "Add tests that kill the new survivors (see mutation-report/"
            "results.txt in the artifact), or lower the floor in "
            "scripts/mutation_scores.json with the reason in the commit.",
        )
    if current > floor.score:
        return Verdict(
            False,
            f"{current}% is above the {floor.score}% floor. Raise the floor in "
            "scripts/mutation_scores.json to keep the gain.",
        )
    return Verdict(False, f"{current}% is within {allowed_drop} points of the floor.")


def summarise(
    stats: Mapping[str, object], label: str, verdict: Verdict | None = None
) -> str:
    """Return the Markdown summary for one shard's stats."""
    score = score_of(stats)
    percent = "n/a" if score.percent is None else f"{score.percent}%"
    lines = [
        f"### Mutation score ({label}): {percent}",
        "",
        f"{score.caught} of {score.ran} mutants that ran were caught by a test.",
        "",
    ]
    if verdict is not None:
        lines += [verdict.message, ""]
    lines += ["| Result | Mutants |", "|---|---|"]
    lines += [f"| {title} | {_count(stats, key)} |" for key, title in ROWS]
    if score.not_run:
        lines.append(f"| Not run yet | {score.not_run} |")
    lines.append(f"| **Total** | {score.total} |")
    return "\n".join(lines) + "\n"


def _no_results(label: str, reason: str) -> str:
    return f"### Mutation score ({label}): no results\n\n{reason}\n"


def _read_stats(path: Path) -> tuple[dict[str, object] | None, str]:
    if not path.is_file():
        return None, "mutmut recorded no mutation data for this shard."
    try:
        stats = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"Could not read `{path}`: {exc}"
    if not isinstance(stats, dict):
        return None, f"`{path}` is not a JSON object."
    return stats, ""


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("stats", type=Path)
    parser.add_argument("label")
    parser.add_argument("--floors", type=Path)
    parser.add_argument(
        "--check",
        action="store_true",
        help="print only the verdict, and exit 1 when the score fell",
    )
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2
    if args.check and args.floors is None:
        parser.print_usage()
        print("--check needs --floors")
        return 2

    stats, reason = _read_stats(args.stats)
    if stats is None:
        # No stats means mutmut failed or never ran, and its own step already
        # decides the job. The summary is a report, so it never fails here.
        print(_no_results(args.label, reason), end="")
        return 0

    verdict: Verdict | None = None
    if args.floors is not None:
        allowed_drop, floors = load_floors(args.floors)
        verdict = compare(
            score_of(stats), args.label, floors.get(args.label), allowed_drop
        )

    if not args.check:
        print(summarise(stats, args.label, verdict), end="")
        return 0
    assert verdict is not None
    level = "error" if verdict.failed else "notice"
    print(f"::{level} title=Mutation score ({args.label})::{verdict.message}")
    return 1 if verdict.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
