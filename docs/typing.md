# Type-Checking Strategy

InkyPi uses [mypy](https://mypy.readthedocs.io/) for static type analysis.
Rather than enabling strict mode everywhere at once, we follow an **incremental
strict** path: a small "strict subset" is enforced as a CI blocker today, with
more modules added over time as they stabilize. The broader `src/` check is now
expected to stay clean, while `tests/` is ratcheted against a checked-in
baseline so new test typing debt cannot slip in while we keep paying down the
backlog.

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
| `src/utils/request_models.py` | Request-model ratchet PR |
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

## Current CI behavior: clean `src/`, ratcheted `tests/`

`scripts/lint.sh` runs the non-strict mypy pass as **two separate invocations**
plus the blocking strict subset:

1. `mypy src/` — production code, compared against the checked-in baseline in
   `scripts/mypy_src_baseline.txt`; this baseline should remain `0`
2. `mypy tests/` — test suite, compared against the checked-in baseline in
   `scripts/mypy_tests_baseline.txt`
3. `mypy --strict ...` — curated strict subset, fully blocking

`src/` is no longer purely informational. Now that the production baseline is
zero, CI fails if `mypy src/` reports any issue or cannot produce a summary.
`tests/` still has much higher typing noise, but it is no longer unbounded:
CI fails if the test error count rises above the committed baseline, or if
mypy cannot produce a summary to compare against. The strict subset above is
unchanged and remains fully blocking.

### Why the split?

The test suite carries far more typing noise than `src/` (fixtures,
monkeypatching, duck-typed stubs). When both were combined into a single
`mypy src tests` run, a small regression in production code was invisible,
drowned out by thousands of test-only errors. Splitting the counts keeps
**`src/` clean and makes `tests/` type drift legible** so we can ratchet it
down over time.

### What to do if the `src/` count changes

If `src/` goes above zero:

1. Run `mypy src/` locally and look at the diff in errors vs `main`.
2. If your PR introduced the new errors, fix them before merging.
3. If the increase is unrelated to your change, call it out in the PR and fix
   the underlying dependency/config issue rather than raising the baseline.

If `src/` stays at zero:

1. Leave `scripts/mypy_src_baseline.txt` at `0`.
2. Prefer adding newly stable modules to the strict subset instead of changing
   the production baseline.

If `mypy src/` exits without a `Found N errors` or `Success:` summary, treat it
as a broken type-check invocation. The ratchet will fail until the underlying
config/import problem is fixed.

### What to do if the `tests/` count changes

If `tests/` goes up:

1. Run `mypy tests/` locally and inspect the new errors.
2. Fix errors introduced by the PR before merging.
3. Treat baseline increases as exceptional and coordinated, not as routine.

If `tests/` goes down:

1. Confirm the lower count is real by rerunning `mypy tests/` or
   `bash scripts/lint.sh`.
2. Update `scripts/mypy_tests_baseline.txt` to the new lower integer.
3. Prefer paying down errors in clusters: shared fixtures, contract/security
   tests, then browser/integration tests.

## Coding guidelines for typed modules

- Avoid `Any` unless truly unavoidable; prefer `object` or a narrow union.
- Prefer `collections.abc.Callable`, `Sequence`, `Mapping` over their
  `typing` counterparts for argument types.
- Use `cast()` sparingly — only when mypy cannot infer a type that you know is
  correct (e.g. narrowing an untyped third-party return value).
- Add `# type: ignore[<code>]` only as a last resort, always with a narrow
  error code and an inline comment explaining why.
