# Profiling and Benchmarking Guide

> **See also:** [`docs/benchmarking.md`](benchmarking.md) covers the *runtime* (production) benchmark system that records per-refresh timings in SQLite on the device. This document covers *developer* tools: pytest-benchmark, cProfile, and py-spy.

---

## When to Profile

Reach for profiling tools when you notice:

- A plugin render takes noticeably longer than similar plugins.
- The refresh loop falls behind its scheduled interval.
- A Flask request path (e.g. `/preview`, `/api/refresh`) feels sluggish under load.
- A `--durations` report from pytest flags a test taking more than a few hundred milliseconds.
- A CI benchmark run shows a large regression vs. the previous baseline.

---

## Running Benchmarks Locally

The benchmark suite lives in `tests/benchmarks/` and uses [pytest-benchmark](https://pytest-benchmark.readthedocs.io/).

```bash
# Run all benchmarks (requires --benchmark-only to avoid skipping)
.venv/bin/python -m pytest tests/benchmarks/ --benchmark-only

# Run a single benchmark by name
.venv/bin/python -m pytest tests/benchmarks/ --benchmark-only -k test_http_cache_hit_lookup
```

### Output Columns

| Column    | Meaning                                              |
|-----------|------------------------------------------------------|
| `min`     | Fastest single iteration — best-case latency         |
| `mean`    | Average over all rounds — general performance level  |
| `median`  | Middle value — less skewed by outliers than mean     |
| `stddev`  | Spread; high stddev means noisy results              |
| `ops`     | Iterations per second (`1 / mean`)                   |
| `rounds`  | Number of timing rounds collected                    |

All times are in seconds unless the column header says otherwise.

---

## Comparing Two Runs

Save a named baseline before your change, then compare after:

```bash
# Save baseline (e.g. before your change)
.venv/bin/python -m pytest tests/benchmarks/ --benchmark-only \
    --benchmark-save=before

# Make your change, then save a second run
.venv/bin/python -m pytest tests/benchmarks/ --benchmark-only \
    --benchmark-save=after

# Compare the two saved runs
.venv/bin/python -m pytest tests/benchmarks/ --benchmark-only \
    --benchmark-compare=before

# Fail if any benchmark regresses by more than 10 %
.venv/bin/python -m pytest tests/benchmarks/ --benchmark-only \
    --benchmark-compare=before \
    --benchmark-compare-fail=mean:10%
```

Saved runs land in `.benchmarks/` (gitignored). Use descriptive names so you can find them later.

---

## Using `scripts/test_profile.sh`

`scripts/test_profile.sh` is a lightweight wrapper around `pytest` tuned for profiling plugin render paths.

**What it does:**

1. Activates `.venv` (or sources `scripts/venv.sh` if no venv is active).
2. Sets `PYTHONPATH=src` so plugins are importable without install.
3. Sets `SKIP_UI=1` and `SKIP_A11Y=1` to skip browser-dependent tests.
4. Runs `pytest -q --durations=25` — the `--durations` flag prints the 25 slowest test items at the end of the run.
5. If you pass arguments they are forwarded directly to pytest; with no arguments it defaults to `tests/plugins`.

**When to use it:**

- Quick scan for slow plugin tests without configuring pytest manually.
- When you want the `--durations` report but don't want to type out the full pytest invocation.
- As a sanity check after optimising a plugin: run before and after, compare the durations table.

```bash
# Default: profile all plugin tests
scripts/test_profile.sh

# Profile a single plugin directory
scripts/test_profile.sh tests/plugins/test_clock_plugin.py

# Override the number of slowest tests shown
PYTEST_DURATIONS=50 scripts/test_profile.sh
```

---

## Profiling a Single Function with `cProfile`

When `--durations` points to a hot function, use `cProfile` for a call-graph breakdown:

```bash
# Profile a specific test (writes profile data to /tmp/out.prof)
.venv/bin/python -m cProfile -o /tmp/out.prof \
    -m pytest tests/plugins/test_clock_plugin.py -x -q

# View the profile interactively with snakeviz
.venv/bin/pip install snakeviz
.venv/bin/python -m snakeviz /tmp/out.prof
```

`snakeviz` opens a browser with a sunburst chart. Click any frame to zoom in. The `cumtime` column (cumulative time) is usually most useful for finding the root cause of slowness.

You can also profile a script or function directly:

```bash
.venv/bin/python -c "
import cProfile, pstats, io
from utils.http_cache import HTTPCache
pr = cProfile.Profile()
pr.enable()
# ... code under test ...
pr.disable()
s = io.StringIO()
pstats.Stats(pr, stream=s).sort_stats('cumulative').print_stats(20)
print(s.getvalue())
"
```

---

## Alternative: `py-spy`

[py-spy](https://github.com/benfred/py-spy) is a sampling profiler that attaches to a running process without modifying the code. It has very low overhead, making it suitable for production-like investigation.

```bash
pip install py-spy   # system Python, not venv — py-spy needs root or ptrace

# Start the dev server
.venv/bin/python src/inkypi.py --dev --web-only &
SERVER_PID=$!

# Record a 30-second flame graph while you trigger requests
sudo py-spy record -o /tmp/profile.svg --pid $SERVER_PID --duration 30

# Open in any browser
open /tmp/profile.svg
```

`py-spy top` gives a live `top`-style view of the running process — useful for quickly spotting which function is consuming CPU without waiting for a full recording.

---

## Which Tool When

| Situation | Recommended tool |
|-----------|-----------------|
| Detect regressions across PRs | `pytest-benchmark` + `--benchmark-compare` |
| Find which test is slow | `scripts/test_profile.sh` (`--durations`) |
| Drill into a slow function call graph | `cProfile` + `snakeviz` |
| Profile a live server or production-like workload | `py-spy` |
| Record per-refresh timings on the device | Runtime benchmark system (see `docs/benchmarking.md`) |

---

## See Also

- [`docs/benchmarking.md`](benchmarking.md) — runtime benchmarking system (SQLite, `refresh_events`, `stage_events`)
- `tests/benchmarks/test_perf_baseline.py` — benchmark suite source; add new benchmarks here
- `scripts/test_profile.sh` — plugin test runner with `--durations` output
