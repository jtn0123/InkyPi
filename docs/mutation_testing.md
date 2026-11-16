# Mutation Testing

## What is mutation testing?

Mutation testing automatically introduces small code changes ("mutants") into
the source and then runs the test suite. If at least one test fails for a given
mutant, the mutant is **killed** — meaning our tests caught the bug. If no test
fails, the mutant **survives** — which signals a gap in test coverage.

Coverage reports tell you *which lines* were executed. Mutation testing tells
you *whether those lines are actually verified* by assertions.

## Why do we have it?

InkyPi ships to devices that cannot be easily reflashed in the field. A
high-quality test suite that catches real regressions is therefore more
important than raw line-coverage percentages. Mutation testing gives us a
second opinion on test quality independent of coverage metrics.

## Which files are currently in scope?

See `pyproject.toml` → `[tool.mutmut]` → `only_mutate`:

| Path | Reason chosen |
|------|--------------|
| `src/app_setup/` | Application bootstrap and middleware helpers |
| `src/blueprints/` | All Flask blueprint route handlers |
| `src/utils/` | All shared utilities (HTTP, image, security, i18n, etc.) |
| `src/refresh_task/` | Refresh coordinator; scheduling logic is regression-prone |
| `src/config.py`, `src/model.py` | Device config and the playlist model every route reads |
| `src/services/` | History, playlist, plugin and update logic moved out of the blueprints (#877) |

mutmut skips decorated functions, so a Flask route handler itself is never
mutated; the helpers and services it calls are.

## How to run locally

Install dev dependencies (mutmut is already in `install/requirements-dev.txt`):

```bash
pip install -r install/requirements-dev.txt
```

Run the mutation pass against the configured files:

```bash
INKYPI_ENV=dev INKYPI_NO_REFRESH=1 SKIP_BROWSER=1 mutmut run --max-children 2
```

Run one shard when you are triaging one package locally. The wrapper
narrows mutmut's scope to the shard's files, so the score and the "not run"
count cover that package alone, and a second run resumes where the first
stopped instead of testing every mutant again:

```bash
INKYPI_ENV=dev INKYPI_NO_REFRESH=1 SKIP_BROWSER=1 \
  python scripts/mutmut_shard.py utils run --max-children 2
```

The shards are `app-setup`, `blueprints`, `utils`, `refresh-task` and `core`
(`config.py`, `model.py` and `services/`); see `SHARDS` in
`scripts/mutmut_shard.py`. Any other mutmut command works the same way, for
example `python scripts/mutmut_shard.py utils results`.

Check the summary after the run completes:

```bash
mutmut results
```

Inspect a specific surviving mutant (replace `<id>` with the named mutant from `results`):

```bash
mutmut show <id>
```

Apply a surviving mutant to a clean working tree for manual investigation
(mutmut 3 has no `unapply`; restore the affected file through Git):

```bash
mutmut apply <id>
# ... investigate / add a test ...
git restore -- <changed-file>
```

## How to expand scope

1. Add the directory (or file, if intentionally narrow) path to `only_mutate` in `pyproject.toml`:

   ```toml
   [tool.mutmut]
   source_paths = ["src/"]
   only_mutate = ["src/app_setup/*", ..., "src/new_area/*"]
   ```

2. Add the new path to `EXPECTED_PATTERNS` in `tests/test_mutmut_config.py` so
   the config test keeps it honest.

3. Put the path in a shard: an existing one in `SHARDS` in
   `scripts/mutmut_shard.py`, or a new shard there plus a matching entry in
   the `mutation-nightly` matrix in `.github/workflows/ci.yml` and in
   `scripts/mutation_scores.json` (score `null`). `tests/unit/test_mutmut_shard.py`
   fails until all three agree and every `only_mutate` path is in exactly one
   shard.

4. Open a PR with the change. The nightly job will pick up the new path on its
   next run (daily, 09:00 UTC).

## CI schedule

The `mutation-nightly` job in `.github/workflows/ci.yml` runs on CI's one
scheduled event (daily, 09:00 UTC) and can be started manually with
`workflow_dispatch`. It will never trigger on a push or pull request.

The job is sharded by package so each package has its own runtime budget:

| Shard | Path |
|-------|------|
| `app-setup` | `src/app_setup/` |
| `blueprints` | `src/blueprints/` |
| `utils` | `src/utils/` |
| `refresh-task` | `src/refresh_task/` |
| `core` | `src/config.py`, `src/model.py`, `src/services/` |

Each shard runs `scripts/mutmut_shard.py <shard> run --max-children 2`. The
wrapper narrows mutmut's `only_mutate` to the shard's files in-process (the
worker processes are forked, so they inherit it) rather than passing mutant
names: with names, mutmut tests every matching mutant again, and the shard's
totals would include the other packages' mutants as "not run". mutmut copies
the source, tests, and repository inputs into an isolated `mutants/` tree and
stores results there; the production source stays unchanged.

### Resuming across nights

No shard finishes its package in one 100-minute night, so each shard keeps
its results for the week. Before running, the job restores the shard's
`mutants/**/*.meta` files (one per source file, holding each mutant's
result) from the Actions cache. The key is the shard, the mutmut version and
the ISO week, so the cache starts fresh every Monday (UTC) and whenever
mutmut is upgraded. mutmut tests only the mutants with no result yet, and
drops a result when the function it belongs to changes. Before running, the
wrapper queues again any mutant whose check was interrupted at the time
limit, and deletes `.meta` files it cannot read. After the run (also after a
timeout), the job saves the results under a new key for the next night.
Only `.meta` files are cached: mutmut does not overwrite a stale copy of a
source file in `mutants/`, so caching the copies would test old code.

### Score floors

`scripts/mutation_scores.json` holds each shard's committed score. After the
summary, the job compares the night's score with it
(`scripts/mutation_summary.py --check`) and fails when a shard's score is more
than `allowed_drop` (2) points under its floor. It compares only a complete
run, one where every mutant in the shard has a result: a partial run tests
the fastest mutants first, so its score moves several points from night to
night without any change in the tests. It also does not enforce a floor that
came from a partial run (`"complete": false`), or a shard with no score yet
(`null`); for those it prints the score to record. When a complete run
finishes, record its score with `"complete": true` (the summary prints the
exact entry), and raise the floor when the score goes up.

CI sets `SKIP_BROWSER=1` and excludes container tests for this backend mutation
pass. Browser and container tests have their own CI jobs. Run without
`PYTHONPATH=src`: mutmut sets up the isolated imports itself.

Each shard writes its mutation score and a table of results (killed,
survived, not run and so on) to the run's summary page, using
`scripts/mutation_summary.py`. The `mutmut-results-<shard>` artifact holds
`mutation-report/results.txt` (the `mutmut results` listing of surviving and
unchecked mutants), the `mutmut-cicd-stats.json` counts, and the parts of
the `mutants/` tree that mutmut needs to show a mutant: the per-file `.meta`
results and the mutated copies of the four packages. Extract it at the root
of a checkout of the same commit, then run `mutmut results` and
`mutmut show <id>` without running anything. The upload is best-effort and
never fails the job.

Each shard stops mutmut after 100 minutes (inside the job's 120-minute cap) and
keeps the partial results, with a notice in the run summary; the next night
resumes from them. Surviving mutants do not fail the job on their own; it
fails when mutmut itself fails (most often because its clean-test run broke)
or when a complete run's score falls under its floor. Scheduled runs include
the shards in the `ci-gate` result, so either turns the nightly red.

mutmut runs several pytest sessions in one interpreter and runs the clean
tests as a sorted subset. As a result, a test that changes a module global
without restoring it (assigning directly instead of using `monkeypatch`) can
break unrelated tests here even when the normal suite passes.

## Narrow PR Mutation Gate

The full `mutmut` pass is slow, so it runs nightly. For PRs, the repo also
has a narrow deterministic harness:

```bash
INKYPI_ENV=dev INKYPI_NO_REFRESH=1 PYTHONPATH=src python scripts/mutation_check.py
```

For each of a few hand-picked high-value mutants, it copies the repository to
a temporary directory, runs the mutant's test commands on the unmutated copy
(each must pass, or the mutant is reported as broken: an import error would
otherwise look like a caught bug), then applies the mutation and runs them
again. It fails when a mutant survives or is broken. A mutant marked
`linux_only` (the install-idempotency smoke drives GNU sed) is skipped on
other systems rather than counted as killed.

CI's `preflash-validate` job sets `INKYPI_VALIDATE_MUTATION=1`, so
`scripts/preflash_validate.sh` runs it on every PR; it adds about 20-30
seconds.

## Interpreting results

| Status | Meaning |
|--------|---------|
| Killed | Test suite caught the mutant — good |
| Survived | No test detected the change — consider adding a targeted test |
| Skipped | mutmut could not parse or apply the mutation |
| Suspicious | Test timed out; worth investigating |

A survived mutant does not block CI on its own. Review the nightly results, add
targeted tests, and shrink the surviving count over time; a falling score
fails the nightly once its shard has a floor from a complete run.
