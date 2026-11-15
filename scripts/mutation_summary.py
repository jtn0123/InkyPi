#!/usr/bin/env python3
"""Render one mutmut shard's results as Markdown for the CI job summary.

Reads the JSON that ``mutmut export-cicd-stats`` writes
(``mutants/mutmut-cicd-stats.json``) and prints a short table plus a score,
so the nightly's result is readable from the run page without downloading
an artifact.

The score is the share of mutants that actually ran which a test caught
(killed, or timed out, which mutmut also counts as caught). Each shard stops
at a time budget, so mutants it never reached are listed as "Not run"
instead of dragging the score down.

Usage:
    python scripts/mutation_summary.py mutants/mutmut-cicd-stats.json <label>
"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

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


def summarise(stats: Mapping[str, object], label: str) -> str:
    """Return the Markdown summary for one shard's stats."""
    total = _count(stats, "total")
    recorded = sum(_count(stats, key) for key, _ in ROWS)
    not_run = max(total - recorded, 0)
    ran = total - not_run - _count(stats, "skipped")
    caught = _count(stats, "killed") + _count(stats, "timeout")
    score = f"{caught / ran * 100:.1f}%" if ran > 0 else "n/a"

    lines = [
        f"### Mutation score ({label}): {score}",
        "",
        f"{caught} of {ran} mutants that ran were caught by a test.",
        "",
        "| Result | Mutants |",
        "|---|---|",
    ]
    lines += [f"| {title} | {_count(stats, key)} |" for key, title in ROWS]
    if not_run:
        lines.append(f"| Not run (time budget) | {not_run} |")
    lines.append(f"| **Total** | {total} |")
    return "\n".join(lines) + "\n"


def _no_results(label: str, reason: str) -> str:
    return f"### Mutation score ({label}): no results\n\n{reason}\n"


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print(__doc__, file=sys.stderr)
        return 2
    path = Path(args[0])
    label = args[1] if len(args) > 1 else "mutation"

    # Never fail the job: the summary is a report, and mutmut's own exit
    # status already decides whether the shard passed.
    if not path.is_file():
        print(_no_results(label, "mutmut recorded no mutation data for this shard."))
        return 0
    try:
        stats = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(_no_results(label, f"Could not read `{path}`: {exc}"))
        return 0
    if not isinstance(stats, dict):
        print(_no_results(label, f"`{path}` is not a JSON object."))
        return 0
    print(summarise(stats, label), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
