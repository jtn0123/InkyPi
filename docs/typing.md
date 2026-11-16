# Type-Checking Strategy

InkyPi uses [mypy](https://mypy.readthedocs.io/) in **strict mode for every
module**: `strict = True` sits once in the `[mypy]` section of `mypy.ini`, plus
`warn_unreachable` and five error codes strict leaves out: `redundant-expr`,
`truthy-bool`, `possibly-undefined`, `deprecated` and `ignore-without-code`.
When one fires on a guard, first ask whether the annotation is honest: a value
read from JSON or the network should be typed `object` and keep its
`isinstance` check, not be `cast` to the shape it is hoped to have and then
re-checked. `src/` and `scripts/` must stay at zero errors; `tests/` is
ratcheted against a checked-in list of error fingerprints so new test typing
debt cannot slip in while the backlog is paid down.

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

## Packages that may not write `Any`

`app_setup`, `display` and `services` also run with `disallow_any_explicit`
(the last section of `mypy.ini`), so writing `Any` there is an error. Use the
real type instead: `Config` or `PlaylistManager` imported under
`TYPE_CHECKING`, a small `Protocol` naming what a function needs from an object
tests replace with fakes (`services.plugin_workflows.SettingsValidator`),
`npt.NDArray[np.uint8]` rather than a bare `np.ndarray`, or `object` plus an
`isinstance` check. A decoded JSON dict whose values are not
checked yet is `utils.json_types.JsonObject`. Objects from a library with no
type information are still `Any`, by inference; don't annotate them.

Removing a `cast(Any, ...)` this way can expose a real mismatch. In
`display_manager.py` it showed `apply_image_enhancement` declaring
`dict[str, float]` for settings that also hold the screen-rendering mode, and
in the Waveshare `epdconfig.py` it showed a `RuntimeError` that was built but
never raised. When a package gets to zero, add it to that section;
`tests/unit/test_mypy_config.py` checks the list never shrinks.

## Current CI behavior: clean `src/` and `scripts/`, ratcheted `tests/`

`scripts/lint.sh` runs mypy as **three separate invocations**, `src/`,
`tests/` and `scripts/`, each through `scripts/mypy_ratchet.py`, which
compares the run with a checked-in baseline:

- `scripts/mypy_src_baseline.txt` — empty: `src/` must stay clean
- `scripts/mypy_tests_baseline.txt` — the test suite's known errors
- `scripts/mypy_scripts_baseline.txt` — empty: the developer, CI and device
  tools must stay clean too

A baseline lists **fingerprints**, `path:error-code`, each with the number of
errors mypy reports for it, for example `tests/unit/test_x.py:arg-type 2`. The
check fails when a fingerprint is new, has more or fewer errors than listed,
or has gone, and prints only those differences (with the errors behind a new
or grown one). A crashed or misconfigured mypy run fails too, since it has
nothing to compare.

The baselines used to hold one total each. That let a fixed error in one test
file pay for a new error in another, so new debt could arrive unseen; per-file,
per-code counts close that gap.

`scripts/` is checked with the same strict settings as `src/` and `tests/`.
Its modules are not a package, so `mypy.ini` puts `scripts/` on `mypy_path`:
that lets `restore_config.py` resolve its sibling `backup_config.py`. Runtime
imports are unchanged; the scripts still add their own directory to `sys.path`.

### Why the split?

The test suite carries far more typing noise than `src/` (fixtures,
monkeypatching, duck-typed stubs). When both were combined into a single
`mypy src tests` run, a small regression in production code was invisible,
drowned out by thousands of test-only errors. Splitting the runs keeps
**`src/` clean and makes `tests/` type drift legible** so we can ratchet it
down over time.

### When `src/` or `scripts/` fails

The baseline is empty, so every error printed is new:

1. Fix errors your change introduced before merging.
2. If one is unrelated to your change, call it out in the PR and fix the
   underlying dependency or config issue rather than adding it to the
   baseline.
3. For an untyped library, add a stub package to the dev group.

### When `tests/` fails

If it prints **errors beyond the baseline**, fix them: they are new in that
file. Adding a fingerprint to the baseline is exceptional and coordinated,
not routine.

If it prints **fixed errors still listed**, you removed some: lock in the
improvement by rewriting the list, and commit it with your change:

```bash
python scripts/mypy_ratchet.py tests scripts/mypy_tests_baseline.txt --update
```

`--update` keeps the comment header and rewrites the fingerprints under it;
add a line to the header's history when the drop is worth recording. CI runs
on Linux, which installs a few Linux-only dependencies a macOS checkout
skips, so the two runs could disagree (they have matched so far). When they
do, commit the list the CI lint job wants.

Prefer paying down errors in clusters: shared fixtures, contract and security
tests, then browser and integration tests.

## Coding guidelines for typed modules

- Avoid `Any` unless truly unavoidable; prefer `object` or a narrow union.
  For a decoded JSON dict, write `utils.json_types.JsonObject`.
- Route handlers return `flask.typing.ResponseReturnValue`, or something
  narrower such as `Response` or `str`. Helpers that build a `json_error` or
  `json_success` reply return `utils.api_responses.JsonResponse`, and
  `JsonResponse | None` when `None` means "no error".
- Prefer `collections.abc.Callable`, `Sequence`, `Mapping` over their
  `typing` counterparts for argument types.
- Use `cast()` sparingly — only when mypy cannot infer a type that you know is
  correct (e.g. narrowing an untyped third-party return value).
- Add `# type: ignore[<code>]` only as a last resort, always with a narrow
  error code and an inline comment explaining why.
