## InkyPi Polishing Plan

This plan sequences improvements across testing, resilience, UX polish, performance, and CI, optimized for cloud-only validation before hardware-in-the-loop.

### Goals
- Increase test depth for security, error handling, and concurrency
- Strengthen RefreshTask lifecycle correctness and isolation
- Harden API edge cases and settings flows
- Polish UX interactions and accessibility
- Improve performance and observability
- Prioritize non-Raspberry Pi CI checks first (pytest, lint, container smoke) before HIL

### Working Agreements
- Implement in small, reversible increments with a checkpoint (commit) per increment
- After each change, run targeted tests then a representative suite; proceed only on green
- Add or update tests when a new bug is found to prevent regressions

---

## Phase 1: Critical Test Coverage (High Impact, Medium Effort)

### 1. Security & Error Handling Tests
Tasks
- Add CSP/HSTS/security headers coverage
- Validate XSS prevention in templates and JSON responses
- Expand input validation errors for settings and plugin operations
- Cover error recovery paths and error responses consistency

Existing/Planned Tests
- tests/unit/test_security_headers_csp_hsts.py
- tests/integration/test_api_json_errors.py
- tests/integration/test_settings_save_errors.py (expanded)
- tests/unit/test_config_validation_errors.py
- tests/unit/test_http_utils_more.py

Acceptance Criteria
- All security header tests pass with strict policies and correct fallbacks
- Malformed payloads yield 4xx with structured errors, never 500
- No reflected HTML/JS is rendered from untrusted inputs

### 2. Concurrency & Threading: RefreshTask Lifecycle
Tasks
- Verify start/stop, idempotency, and cleanup on app teardown
- Ensure thread-safety for shared state; no deadlocks/hangs
- Validate retries/backoff and resilience to plugin exceptions

Existing/Planned Tests
- tests/integration/test_refresh_task.py
- tests/integration/test_refresh_task_interval.py
- tests/unit/test_refresh_task_resilience.py
- tests/unit/test_display_save_failure_isolation.py
- tests/unit/test_plugininstance_refresh_logic.py

Acceptance Criteria
- Start/stop is safe to call repeatedly; no lingering threads
- Crashing plugins do not crash the scheduler; errors logged and isolated
- Retry/backoff adheres to configured policy

### 3. API Edge Cases: Settings and Plugins
Tasks
- Exercise boundary conditions for settings CRUD, backups, and rollbacks
- Validate playlist operations, isolation between plugin instances, lifecycle flows
- Verify logs endpoint truncation behavior and pagination

Existing/Planned Tests
- tests/integration/test_settings_routes.py, test_settings_update_flows.py, test_settings_backup.py, test_settings_more.py, test_settings_extra.py
- tests/integration/test_plugin_routes.py, test_plugin_pages.py, test_plugin_lifecycle_flow.py, test_plugin_isolation.py
- tests/integration/test_logs_api_truncation.py
- tests/unit/test_model_invariants.py, test_playlist_priority_active.py

Acceptance Criteria
- Settings APIs handle invalid/missing fields with precise error messages
- Playlist operations preserve invariants and priority rules
- Logs API reliably truncates/limits without corrupting content

Validation Strategy
- Run full test suite in web-only mode (INKYPI_NO_REFRESH=1)
- Add targeted property-based tests where invariants exist (model, playlist)

---

## Phase 2: UX & Accessibility Polish (Medium Impact, Low/Medium Effort)

Tasks
- Unify lightbox overlays for preview images across plugin and playlist pages with ESC/outside-click close and native-size toggle on double-click
- Improve progressive disclosure and response modals
- Strengthen keyboard navigation and ARIA attributes

Existing/Planned Tests
- tests/static/test_response_modal_js.py, test_response_modal_more.py
- tests/static/test_progressive_disclosure.py, test_ui_enhancements.py
- tests/integration/test_playlist_a11y.py, test_more_a11y.py

Acceptance Criteria
- Consistent lightbox behavior site-wide; all specified interactions validated
- Axe/lighthouse checks show no critical a11y violations

---

## Phase 3: Performance, Observability, and CI (Medium Impact, Medium Effort)

Tasks
- Benchmark critical endpoints and refresh flows; track in sqlite benchmarks.db and reporting
- Add structured logging for refresh lifecycle and plugin execution timing
- Strengthen lint/type checks; ensure fast, deterministic CI

Existing/Planned Assets
- scripts/show_benchmarks.py, scripts/export_benchmarks_report.py
- docs/benchmarking.md (extend)
- scripts/lint.sh, mypy.ini, pyproject.toml

Acceptance Criteria
- Baseline benchmarks captured and compared; regressions fail CI
- CI pipeline runs: lint, unit, integration (web-only), packaging smoke

---

## Execution Order & Dependencies
1. Establish baseline: run full test suite in web-only mode (no hardware) and record failures
2. Phase 1.1 Security/Error Handling fixes → re-run impacted tests + unit suite
3. Phase 1.2 Concurrency/Threading fixes → run refresh/integration suite
4. Phase 1.3 API Edge Cases fixes → run integration suite
5. Phase 2 UX polish and a11y → run static and integration UI tests
6. Phase 3 perf/observability/CI → run full suite and publish benchmarks

---

## Checkpoints & Validation
- After each task: commit with scope-labeled message and run relevant tests
- Always prefer cloud-only checks first; add hardware-in-the-loop runs as a final gate


