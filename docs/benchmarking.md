## InkyPi Benchmarking and Progress

This document describes production-grade benchmarking for InkyPi. It persists per-refresh metrics and stage events in SQLite with minimal overhead and is safe to run on devices.

### Configuration

- `enable_benchmarks` (bool): Enable/disable recording. Default: true.
- `benchmarks_db_path` (str): Path to the SQLite DB file. Default: `<BASE_DIR>/benchmarks.db`.
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

### Roadmap (next)

- Add `/api/benchmarks/*` endpoints and simple dashboard.
- SSE progress stream and lightweight UI indicator.


