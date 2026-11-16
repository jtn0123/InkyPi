## InkyPi Benchmarking and Progress

This document describes production-grade benchmarking for InkyPi. It persists per-refresh metrics and stage events in SQLite with minimal overhead and is safe to run on devices.

### Configuration

- `enable_benchmarks` (bool): Enable/disable recording. Default: true.
- `benchmarks_db_path` (str): Path to the SQLite DB file. Default: `<PROJECT_ROOT>/runtime/benchmarks.db`.
- `benchmark_sample_rate` (float 0..1): Probability to record a refresh. Default: 1.0.

Add these to `src/config/device.json` as needed. Defaults are safe in production.

### What is recorded

- Table `refresh_events` per refresh:
  - `refresh_id`, `ts`, `plugin_id`, `instance`, `playlist`, `used_cached`
  - `request_ms`, `generate_ms`, `preprocess_ms`, `display_ms`
  - `cpu_percent`, `memory_percent`, `notes`
- Table `stage_events` per stage within a refresh:
  - `refresh_id`, `ts`, `stage`, `duration_ms`, `extra_json`

Rows older than 30 days (`BENCHMARK_RETENTION_DAYS` in `src/benchmarks/benchmark_storage.py`) are deleted every 10 refreshes, with the history cleanup, so the database stays at roughly a month of rows. The diagnostics page shows at most the last 7 days.

### Where instrumentation lives

- `src/refresh_task/refresh_cycle.py`:
  - Creates a `benchmark_id` per refresh and emits the `generate_image` stage.
  - Saves the `refresh_events` row at the end of the refresh.
- `src/refresh_task/display_pipeline.py`:
  - Emits the overall `display_pipeline` stage and, when the driver is known, `display_driver`.
- `src/refresh_task/recorder.py`:
  - `RefreshRecorder` adds the system snapshot and writes rows through `src/benchmarks/benchmark_storage.py`.
- `src/display/display_manager.py`:
  - Measures `preprocess_ms` and `display_ms` and reports the driver name.

### Exporting reports

There is no export script. Read the numbers from the same JSON endpoints the Diagnostics panel uses (all `GET`, all read-only; they answer 404 while `enable_benchmarks` is off):

- `/api/benchmarks/summary?window=24h`: the refresh count and p50/p95 of `request_ms`, `generate_ms`, `preprocess_ms` and `display_ms`. `window` takes minutes, hours or days (`30m`, `6h`, `7d`) and defaults to `24h`.
- `/api/benchmarks/refreshes?window=24h&limit=50`: recent `refresh_events` rows, newest first. `limit` is 1–200; pass the response's `next_cursor` as `cursor=` for the next page.
- `/api/benchmarks/plugins?window=24h`: average timings per plugin.
- `/api/benchmarks/stages?refresh_id=<id>`: the `stage_events` rows for one refresh.

```bash
curl -s "http://<pi-hostname>.local/api/benchmarks/summary?window=7d" | jq .
```

Or copy the database file (`benchmarks_db_path`) off the device and query it with `sqlite3`.

### Overhead and safety

- Best-effort writes with exceptions swallowed to avoid impacting refresh cycles.
- Sampling control via `benchmark_sample_rate` for production.

### pytest-benchmark CI tests

`tests/benchmarks/` contains micro-benchmarks for hot paths (cache lookups, image
processing, config reads, plugin render pipelines). All are deterministic, hermetic,
and complete in under 1 second each.

#### Running benchmarks locally

```bash
# Run and display results
SKIP_BROWSER=1 PYTHONPATH=src pytest tests/benchmarks/ --benchmark-only -q

# Run and save JSON for comparison
SKIP_BROWSER=1 PYTHONPATH=src pytest tests/benchmarks/ --benchmark-only \
  --benchmark-json=/tmp/bench-current.json -q
```

#### CI regression gate

The `lint` job in `.github/workflows/ci.yml` times the change and its base
commit (`HEAD^1`: the PR's base branch, or the previous commit on `main`) on
the same runner. Each side runs twice, in turn, and each benchmark's lowest
median counts. If a benchmark is more than the threshold slower than on the
base commit, CI fails.

The gate used to compare against a baseline cached from an earlier `main` run.
Two hosted runners with the same CPU model can differ by 25–33%, and more
across models, so unrelated PRs failed.

- **Threshold**: defaults to +15%. Override via the `BENCHMARK_THRESHOLD_PCT`
  GitHub Actions variable or environment variable.
- **Comparison script**: `scripts/benchmark_compare.py`. `--baseline` and
  `--current` each take one or more pytest-benchmark JSON files.
- **Absolute budgets**: `scripts/perf_budget_gate.py` also fails CI when a
  plugin render or cold start is over its budget.
- **Artifacts**: every run uploads `benchmark-results` with all four JSON
  files and the comparison log.

#### The committed baseline

`tests/benchmarks/baseline.json` lists the benchmarks that should exist, and
gives local runs something to compare against:

```bash
SKIP_BROWSER=1 PYTHONPATH=src pytest tests/benchmarks/ --benchmark-only \
  --benchmark-json=/tmp/bench-current.json -q
python scripts/benchmark_compare.py --current /tmp/bench-current.json
```

Its timings come from one machine, so compare against it only on similar
hardware. To refresh it:

```bash
SKIP_BROWSER=1 PYTHONPATH=src pytest tests/benchmarks/ --benchmark-only \
  --benchmark-json=tests/benchmarks/baseline.json -q
```

#### Adding a new benchmark

Add benchmarks only if they:
- Have no network dependency
- Have no wall-clock dependency
- Run in well under one second
- Are representative of a real hot path

After adding a new benchmark, regenerate the baseline as described above.

#### Removing a benchmark

Delete the test and its entry in `tests/benchmarks/baseline.json`. The gate
fails when a benchmark the base commit ran is missing from the change's run,
unless the committed baseline no longer lists it either; then it is reported
as `RETIRED`.

### Dashboard

The Settings → Updates → Diagnostics panel reads from the runtime benchmark
database through `/api/benchmarks/*` endpoints. It shows:

- p50/p95 timing by stage for the selected window
- per-plugin timing averages
- recent refresh rows
- stage drill-down for a selected refresh

### Roadmap (next)

- SSE progress stream and lightweight UI indicator.
