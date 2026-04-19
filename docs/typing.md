# Type-Checking Strategy

InkyPi uses [mypy](https://mypy.readthedocs.io/) for static type analysis.
Rather than enabling strict mode everywhere at once, we follow an **incremental
strict** path: a small "strict subset" is enforced as a CI blocker today, with
more modules added over time as they stabilize. The broader `src/` check is now
ratcheted against a checked-in baseline so new typing debt cannot slip in while
we keep paying down the backlog.

## Why incremental strict?

Enabling `--strict` across the whole codebase in one shot would produce
hundreds of errors and risk churn on actively-changing files.  An incremental
approach lets us raise the quality bar module by module without blocking
ongoing feature work.

## Current strict subset (CI-blocking)

| Module | Added |
|---|---|
| `src/utils/http_utils.py` | JTN-525 |
| `src/utils/security_utils.py` | JTN-525 |
| `src/utils/client_endpoint.py` | Quality guards PR |
| `src/utils/display_names.py` | Quality guards PR |
| `src/utils/messages.py` | Quality guards PR |
| `src/utils/output_validator.py` | Quality guards PR |
| `src/utils/paths.py` | Quality guards PR |
| `src/utils/refresh_info.py` | Quality guards follow-up PR |
| `src/utils/refresh_stats.py` | Quality guards follow-up PR |
| `src/refresh_task/actions.py` | Refresh guards PR |
| `src/refresh_task/context.py` | Refresh guards PR |
| `src/refresh_task/worker.py` | Refresh guards PR |
| `src/utils/sri.py` | Quality guards follow-up PR |
| `src/utils/time_utils.py` | Quality guards PR |
| `src/utils/http_cache.py` | JTN-676 |
| `src/model.py` | JTN-663 |

This list is intentionally low-churn: the broad `src/` ratchet protects the
rest of production code from backsliding, while the modules above are held to
full `--strict`.

## How to add a module to the strict subset

1. **Run mypy strict on the module locally** and fix all errors:

   ```bash
   .venv/bin/python -m mypy --strict src/utils/your_module.py
   ```

2. **Add a per-module block to `mypy.ini`:**

   ```ini
   [mypy-utils.your_module]
   strict = True
   ```

3. **Add the file to the blocking check in `scripts/lint.sh`:**

   ```bash
   mypy --strict \
     src/utils/http_utils.py \
     src/utils/security_utils.py \
     src/utils/your_module.py
   ```
4. **Update the table above** with the module path and Linear issue reference.
5. Open a PR — CI will enforce strictness from that point forward.

## Current CI behavior: ratcheted `src/`, advisory `tests/`

`scripts/lint.sh` runs the non-strict mypy pass as **two separate invocations**
plus the blocking strict subset:

1. `mypy src/` — production code, compared against the checked-in baseline in
   `scripts/mypy_src_baseline.txt`
2. `mypy tests/` — test suite, advisory only
3. `mypy --strict ...` — curated strict subset, fully blocking

`src/` is no longer purely informational. CI fails only when the `src/` count
rises above the committed baseline, or when mypy cannot produce a summary to
compare against. `tests/` remains non-blocking because its typing noise is
still much higher. The strict subset above is unchanged and remains fully
blocking.

### Why the split?

The test suite carries far more advisory typing noise than `src/` (fixtures,
monkeypatching, duck-typed stubs). When both were combined into a single
`mypy src tests` run, a small regression in production code was invisible —
drowned out by thousands of test-only errors. Splitting the counts makes
**`src/` type drift legible so we can ratchet it downward** and eventually
promote more modules into the strict subset.

### What to do if the `src/` count changes

If `src/` goes up:

1. Run `mypy src/` locally and look at the diff in errors vs `main`.
2. If your PR introduced the new errors, fix them before merging.
3. If the increase is unrelated to your change (for example a dependency or
   typeshed shift), call it out in the PR and land a coordinated baseline
   update only if the new debt is intentional.

If `src/` goes down:

1. Confirm the lower count is real by rerunning `mypy src/` or
   `bash scripts/lint.sh`.
2. Update `scripts/mypy_src_baseline.txt` to the new lower integer.
3. Rerun `bash scripts/lint.sh` so the ratchet records the improvement.

If `mypy src/` exits without a `Found N errors` or `Success:` summary, treat it
as a broken type-check invocation. The ratchet will fail until the underlying
config/import problem is fixed.

Increases in the `tests/` count are lower priority but still worth a glance —
prefer fixing them opportunistically in the same area you're already editing.

## Coding guidelines for typed modules

- Avoid `Any` unless truly unavoidable; prefer `object` or a narrow union.
- Prefer `collections.abc.Callable`, `Sequence`, `Mapping` over their
  `typing` counterparts for argument types.
- Use `cast()` sparingly — only when mypy cannot infer a type that you know is
  correct (e.g. narrowing an untyped third-party return value).
- Add `# type: ignore[<code>]` only as a last resort, always with a narrow
  error code and an inline comment explaining why.
