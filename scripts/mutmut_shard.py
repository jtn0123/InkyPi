#!/usr/bin/env python3
"""Run a mutmut command on one shard of the mutation scope.

The mutation nightly splits ``[tool.mutmut] only_mutate`` (pyproject.toml)
into shards, one CI job each, so each package gets its own time budget. This
wrapper narrows mutmut's loaded ``only_mutate`` to one shard's patterns and
then runs the mutmut command line unchanged.

Why not ``mutmut run "blueprints.*"``? mutmut re-tests every mutant you name,
even one that already has a result, so a named run starts from scratch every
night and stops at the same place. ``mutmut run`` with no names keeps every
recorded result and tests only the mutants that have none. With the scope
narrowed here, a ``mutants/`` tree restored from the previous night resumes
where that night stopped. Every other command (``results``,
``export-cicd-stats``) then also counts this shard's mutants only.

Before ``run``, unreadable result files are deleted (mutmut regenerates
them) and mutants whose check was interrupted are queued again, so a night
that was stopped mid-write cannot wedge the rest of the week.

Usage:
    python scripts/mutmut_shard.py <shard> run --max-children 2
    python scripts/mutmut_shard.py <shard> results
    python scripts/mutmut_shard.py <shard> export-cicd-stats
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mutmut.configuration import Config

REPO_ROOT = Path(__file__).resolve().parents[1]

# Shard label -> only_mutate patterns. The labels are the CI matrix labels in
# .github/workflows/ci.yml and the keys of scripts/mutation_scores.json;
# tests/unit/test_mutmut_shard.py keeps all three, and pyproject.toml, in step.
SHARDS: dict[str, tuple[str, ...]] = {
    "app-setup": ("src/app_setup/*",),
    "blueprints": ("src/blueprints/*",),
    "utils": ("src/utils/*",),
    "refresh-task": ("src/refresh_task/*",),
    "core": ("src/config.py", "src/model.py", "src/services/*"),
}

# mutmut's exit code for a check stopped by Ctrl-C / SIGINT
# (mutmut.stats.status_by_exit_code). It is a non-result: test it again.
INTERRUPTED = 2


@dataclass(frozen=True)
class RestoredResults:
    results: int
    requeued: int
    dropped_files: int


def narrow_scope(shard: str, cfg: Config | None = None) -> None:
    """Point mutmut's config (by default the one it loaded) at one shard."""
    if cfg is None:
        from mutmut.configuration import config

        cfg = config()
    configured = set(cfg.only_mutate)
    missing = [pattern for pattern in SHARDS[shard] if pattern not in configured]
    if missing:
        raise SystemExit(
            f"Shard {shard!r} mutates {missing}, which [tool.mutmut] only_mutate "
            "in pyproject.toml does not list. Add them there first."
        )
    cfg.only_mutate = list(SHARDS[shard])


def prepare_restored_results(mutants_dir: Path) -> RestoredResults:
    """Make a restored ``mutants/`` tree safe to resume from.

    Deletes ``.meta`` files that are not a readable mutmut result file, and
    resets interrupted checks to "not checked" so this run tests them again.
    """
    results = requeued = dropped = 0
    for meta in sorted(mutants_dir.rglob("*.meta")):
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            data = None
        exit_codes = data.get("exit_code_by_key") if isinstance(data, dict) else None
        if not isinstance(data, dict) or not isinstance(exit_codes, dict):
            meta.unlink()
            dropped += 1
            continue
        changed = False
        for key, code in exit_codes.items():
            if code == INTERRUPTED:
                exit_codes[key] = None
                requeued += 1
                changed = True
            elif code is not None:
                results += 1
        if changed:
            meta.write_text(json.dumps(data, indent=4), encoding="utf-8")
    return RestoredResults(results=results, requeued=requeued, dropped_files=dropped)


def _usage() -> int:
    print(__doc__, file=sys.stderr)
    print(f"Shards: {', '.join(SHARDS)}", file=sys.stderr)
    return 2


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) < 2 or args[0] not in SHARDS:
        return _usage()
    shard, mutmut_args = args[0], args[1:]

    # mutmut reads pyproject.toml and writes mutants/ relative to the cwd.
    os.chdir(REPO_ROOT)
    narrow_scope(shard)
    if mutmut_args[0] == "run":
        restored = prepare_restored_results(REPO_ROOT / "mutants")
        print(
            f"Shard {shard}: resuming with {restored.results} mutant results from "
            f"earlier runs ({restored.requeued} interrupted checks queued again, "
            f"{restored.dropped_files} unreadable result files dropped).",
            flush=True,
        )

    # Imported here: importing mutmut.__main__ sets the multiprocessing start
    # method to fork, so mutmut's worker processes inherit the narrowed config.
    from mutmut.__main__ import cli

    # Click's standalone mode always ends by raising SystemExit.
    try:
        cli.main(args=mutmut_args, prog_name="mutmut")
    except SystemExit as exc:
        if exc.code is None:
            return 0
        return exc.code if isinstance(exc.code, int) else 1


if __name__ == "__main__":
    raise SystemExit(main())
