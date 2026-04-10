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

As of JTN-508 the scope was expanded from three individual files to four full
directories. See `pyproject.toml` → `[tool.mutmut]` → `paths_to_mutate`:

| Path | Reason chosen |
|------|--------------|
| `src/app_setup/` | Application bootstrap and middleware helpers |
| `src/blueprints/` | All Flask blueprint route handlers |
| `src/utils/` | All shared utilities (HTTP, image, security, i18n, etc.) |
| `src/refresh_task/` | Refresh coordinator; scheduling logic is regression-prone |

Any surviving mutations found by the nightly run against these expanded paths
should be triaged as described in the follow-up issue linked to JTN-508.

## How to run locally

Install dev dependencies (mutmut is already in `install/requirements-dev.txt`):

```bash
pip install -r install/requirements-dev.txt
```

Run the mutation pass against the configured files:

```bash
INKYPI_ENV=dev INKYPI_NO_REFRESH=1 PYTHONPATH=src mutmut run
```

Check the summary after the run completes:

```bash
mutmut results
```

Inspect a specific surviving mutant (replace `<id>` with the number from `results`):

```bash
mutmut show <id>
```

Apply a surviving mutant to the working tree for manual investigation:

```bash
mutmut apply <id>
# ... investigate / add a test ...
mutmut unapply
```

## How to expand scope

1. Add the file path to `paths_to_mutate` in `pyproject.toml`:

   ```toml
   [tool.mutmut]
   paths_to_mutate = "src/utils/http_utils.py,src/utils/image_serving.py,src/refresh_task/task.py,src/utils/new_module.py"
   ```

2. Add the new path to `EXPECTED_FILES` in `tests/test_mutmut_config.py` so the
   config test keeps it honest.

3. Open a PR with the change. The nightly job will pick up the new file on its
   next Sunday run.

## CI schedule

The `mutation-nightly` job in `.github/workflows/ci.yml` runs every **Sunday at
03:00 UTC** (`cron: '0 3 * * 0'`). It is gated by
`if: github.event_name == 'schedule'` and will never trigger on a push or pull
request.

Results are uploaded as the `mutmut-cache` artifact and can be downloaded from
the GitHub Actions run summary.

## Interpreting results

| Status | Meaning |
|--------|---------|
| Killed | Test suite caught the mutant — good |
| Survived | No test detected the change — consider adding a targeted test |
| Skipped | mutmut could not parse or apply the mutation |
| Suspicious | Test timed out; worth investigating |

A survived mutant does not automatically block CI. The nightly job is advisory:
review the results, add targeted tests, and shrink the surviving count over time.
