# Type-Checking Strategy

InkyPi uses [mypy](https://mypy.readthedocs.io/) in **strict mode for every
module**: `strict = True` sits once in the `[mypy]` section of `mypy.ini`, plus
`warn_unreachable` and five error codes strict leaves out: `redundant-expr`,
`truthy-bool`, `possibly-undefined`, `deprecated` and `ignore-without-code`.
When one fires on a guard, first ask whether the annotation is honest: a value
read from JSON or the network should be typed `object` and keep its
`isinstance` check, not be `cast` to the shape it is hoped to have and then
re-checked. `src/` must stay at zero errors;
`tests/` is ratcheted against a checked-in baseline so new test typing debt
cannot slip in while the backlog is paid down.

## Why there is no per-module strict list

mypy applies `strict = True` from *any* section to the whole run. A
`[mypy-utils.foo]` section with `strict = True` does not make only `utils.foo`
strict; it makes everything strict. Until November 2026 `mypy.ini` held 22 such
sections, documented as a "strict subset", and `scripts/lint.sh` ran a third
`mypy --strict` pass over them. In fact the whole tree was strict, and deleting
the last section would have dropped every module to non-strict with nothing
failing. `tests/unit/test_mypy_config.py` now checks that strict is set once,
globally, that no section switches a strict flag back off, and that mypy really
reports `no-untyped-def` with the repo config.

## Third-party libraries without types

`ignore_missing_imports` is not set globally, so an import that mypy has no
types for fails the check instead of quietly becoming `Any`. Each library
falls into one of three cases:

- It ships its own types. Nothing to do.
- A stub package exists (mypy says "Library stubs not installed for ...").
  Pin it in the `dev` dependency group in `pyproject.toml` next to `types-requests`,
  `types-PyYAML`, `types-psutil`, `types-jsonschema` and `types-waitress`,
  matched to the library's version, and regenerate the lock.
- Neither exists (mypy says "missing library stubs or py.typed marker", or
  "Cannot find implementation" for a device-only library). Add the module to
  one of the two `[mypy-...]` sections at the end of `mypy.ini`.

`tests/unit/test_mypy_config.py` fails if the global switch comes back.

## Current CI behavior: clean `src/`, ratcheted `tests/`

`scripts/lint.sh` runs mypy as **two separate invocations**:

1. `mypy src/` — production code, compared against the checked-in baseline in
   `scripts/mypy_src_baseline.txt`; this baseline should remain `0`
2. `mypy tests/` — test suite, compared against the checked-in baseline in
   `scripts/mypy_tests_baseline.txt`

CI fails if `mypy src/` reports any issue or cannot produce a summary, and if
the test error count rises above the committed baseline or mypy cannot produce
a summary to compare against.

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
2. Update `scripts/mypy_tests_baseline.txt` to the new lower integer, taken
   from a CI lint job rather than a macOS run (the file's header explains
   why). Edit the single value on its last line and add a history comment
   above it; `scripts/lint.sh` rejects a file with more than one value.
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
