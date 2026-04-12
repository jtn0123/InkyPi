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

### Where instrumentation lives

- `src/refresh_task.py`:
  - Creates a `benchmark_id` per refresh.
  - Persists `refresh_events` row with timing and system snapshot.
  - Emits `stage_events` for `generate_image` and overall `display_pipeline`.
- `src/display/display_manager.py`:
  - Records `preprocess_ms` and `display_ms` and, if available, emits stage `display_driver` with driver type.

### Exporting reports

Use the export script (to be added) or query the DB directly. A generated summary is tracked at `docs/benchmarks_report.md`.

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

Every PR runs benchmarks and compares against a cached CI baseline. If any
benchmark's median time exceeds the baseline by more than the configured
threshold, CI fails.

- **CI baseline**: cached per-OS via GitHub Actions cache. On pushes to `main`,
  the current run becomes the new baseline for future PRs. On the very first
  run (no cache), the comparison is informational only (non-blocking).
- **Repo baseline** (`tests/benchmarks/baseline.json`): committed for local
  development use and as a fallback when no CI cache exists.
- **Threshold**: defaults to +15%. Override via the `BENCHMARK_THRESHOLD_PCT`
  GitHub Actions variable or environment variable.
- **Comparison script**: `scripts/benchmark_compare.py`

The gate runs as part of the `lint` job in `.github/workflows/ci.yml`.

#### Updating the baseline

When a legitimate performance change lands (new feature, algorithm change), update
the baseline:

```bash
SKIP_BROWSER=1 PYTHONPATH=src pytest tests/benchmarks/ --benchmark-only \
  --benchmark-json=tests/benchmarks/baseline.json -q
git add tests/benchmarks/baseline.json
git commit -m "chore: update benchmark baseline"
```

#### Adding a new benchmark

Add benchmarks only if they:
- Have no network dependency
- Have no wall-clock dependency
- Run in well under one second
- Are representative of a real hot path

After adding a new benchmark, regenerate the baseline as described above.

### Roadmap (next)

- Add `/api/benchmarks/*` endpoints and simple dashboard.
- SSE progress stream and lightweight UI indicator.
