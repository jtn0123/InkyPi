# Codebase Direction Checklist

Created: 2026-04-26

Use this as the working checklist after the 2026-04-25 codebase grade report. The goal is to move InkyPi from a strong **B+** toward a realistic **A-** by reducing the remaining risky concentration points, not by adding more broad process.

## How To Use This Plan

- Treat each numbered section as one PR-sized workstream unless noted otherwise.
- Keep PRs narrow. If a task starts changing unrelated UI, install, release, and refresh code at once, split it.
- Re-check the relevant grade-report item before starting: `A1`, `G2`, `C1`, `C3`, `D1`, `F1`, `B1`.
- Mark checkboxes as done only after code, tests, docs, and PR validation are all handled.

## 1. A1 + G2 - Split The Refresh Control Room

Plain-English goal: `RefreshTask` is the machine room for the display loop. It currently decides what to run, runs it, records timings, handles fallbacks, pushes display output, and reports status. This work splits that into smaller helpers so future fixes do not require touching one giant file.

### Target Outcome

- [ ] `RefreshTask` is mostly an orchestrator: it wires collaborators together and owns the loop.
- [ ] Plugin execution and retry policy live outside `src/refresh_task/task.py`.
- [ ] Display persistence, fallback-image handling, and display update result handling live outside `task.py`.
- [ ] Timing, benchmark persistence, and progress/event recording live in a recorder-style collaborator.
- [ ] Existing refresh behavior stays the same for manual refreshes, scheduled refreshes, plugin failure, fallback display, and subprocess cleanup.

### Suggested PR Split

#### PR 1.1 - Extract Recorder/Telemetry First

- [ ] Create `src/refresh_task/recorder.py` or similarly named module.
- [ ] Move stage timing, progress event publishing, and benchmark persistence out of `task.py`.
- [ ] Keep the public behavior identical.
- [ ] Add focused unit tests for recorder behavior.
- [ ] Add or update one integration test showing refresh still records progress/benchmark output.

Validation:

```bash
PYTHONPATH=src pytest -q tests/unit tests/integration/test_refresh_task.py tests/integration/test_refresh_cycle.py
PYTHONPATH=src python3 -m mypy src/refresh_task
```

#### PR 1.2 - Extract Display Pipeline

- [ ] Create `src/refresh_task/display_pipeline.py`.
- [ ] Move display persistence, fallback image choice, and display update result handling into it.
- [ ] Keep hardware/mock display paths unchanged.
- [ ] Add tests for success, plugin failure fallback, and display failure behavior.

Validation:

```bash
PYTHONPATH=src pytest -q tests/unit/test_display_interfaces.py tests/integration/test_display_flows.py tests/integration/test_refresh_task.py
PYTHONPATH=src python3 -m mypy src/display src/refresh_task
```

#### PR 1.3 - Extract Execution Policy

- [ ] Create `src/refresh_task/executor.py`.
- [ ] Move subprocess/in-process execution policy and retry/failure mapping out of `task.py`.
- [ ] Keep circuit-breaker and health state behavior compatible with current tests.
- [ ] Add tests for plugin success, timeout, exception, and subprocess cleanup.

Validation:

```bash
PYTHONPATH=src pytest -q tests/integration/test_refresh_task.py tests/integration/test_error_injection.py tests/integration/test_update_now_timeout.py
PYTHONPATH=src python3 -m mypy src/refresh_task
```

### Done Means

- [ ] `src/refresh_task/task.py` is materially smaller and easier to scan.
- [ ] The new collaborators have clear names and narrow responsibilities.
- [ ] Refresh-related tests pass locally and in CI.
- [ ] No user-visible refresh/display behavior changes unless intentionally documented.

## 2. C1 + C3 - Organize The Frontend Wiring

Plain-English goal: the UI is feature-rich, but some JavaScript files are doing too many jobs. This work turns giant scripts into smaller modules so adding a button, modal, validation rule, or preview state is less likely to break another feature.

### Target Outcome

- [ ] `src/static/scripts/progressive_disclosure.js` is split into focused modules.
- [ ] `src/static/scripts/plugin_page.js` exposes less global state.
- [ ] Shared DOM, escaping, focus, modal, and status helpers live in reusable utilities where appropriate.
- [ ] Browser smoke and accessibility tests still cover the changed flows.

### Suggested PR Split

#### PR 2.1 - Split Progressive Disclosure

- [ ] Identify natural groups: settings mode, wizard navigation, live preview, change summary, lightbox/canvas preview.
- [ ] Extract each group into a small module.
- [ ] Keep the page bootstrap thin.
- [ ] Preserve existing selectors and data attributes unless a test-backed rename is necessary.

Validation:

```bash
PYTHONPATH=src pytest -q tests/integration/test_e2e_form_workflows.py tests/integration/test_collapsible_sections_e2e.py tests/integration/test_settings_round_trip_e2e.py
PYTHONPATH=src REQUIRE_BROWSER_SMOKE=1 pytest -q tests/integration/test_browser_smoke.py
```

#### PR 2.2 - Reduce Plugin Page Global State

- [ ] Split plugin preview/status/progress/schedule behavior into focused modules.
- [ ] Keep a small page controller as the only bootstrap entrypoint.
- [ ] Move modal/focus helpers into shared UI utilities if they are duplicated.
- [ ] Avoid changing visual design during this PR unless required by the refactor.

Validation:

```bash
PYTHONPATH=src pytest -q tests/integration/test_plugin_workflow_e2e.py tests/integration/test_plugin_preview_smoke.py tests/integration/test_plugin_update_now.py tests/integration/test_plugin_add_to_playlist_ui.py
PYTHONPATH=src REQUIRE_BROWSER_SMOKE=1 pytest -q tests/integration/test_browser_smoke.py
```

### Done Means

- [ ] The largest frontend scripts are smaller and easier to reason about.
- [ ] Browser tests cover the main changed flows.
- [ ] UI behavior is unchanged except where explicitly documented.
- [ ] Future UI work has obvious module homes.

## 3. D1 - Make Mutation Testing Useful

Plain-English goal: mutation testing asks, "If a bug were inserted here, would our tests catch it?" Right now it exists, but it is not yet a reliable everyday signal. This work makes it smaller, faster, and actionable.

### Target Outcome

- [ ] Mutation testing runs on a curated set of high-risk modules first.
- [ ] Results are uploaded as artifacts.
- [ ] Surviving mutants are easy to read and route to follow-up work.
- [ ] The job is either reliable enough to gate selected paths or clearly labeled as scheduled/advisory.

### Suggested PR Split

#### PR 3.1 - Narrow The First Useful Mutation Scope

- [ ] Pick a small initial scope: request models, HTTP utilities, config schema, or refresh helpers.
- [ ] Update `pyproject.toml` or mutation workflow config for that scope.
- [ ] Document why this scope was chosen.
- [ ] Make the job finish predictably.

Validation:

```bash
PYTHONPATH=src pytest -q tests/unit tests/contract
python -m mutmut run --paths-to-mutate <chosen-scope>
```

#### PR 3.2 - Publish Mutation Artifacts

- [ ] Ensure CI uploads mutation result artifacts.
- [ ] Add a short Markdown or JSON summary.
- [ ] Document how to inspect surviving mutants locally.
- [ ] Decide whether the first scope blocks PRs or stays scheduled-only.

Validation:

```bash
python -m pytest -q tests/test_mutmut_config.py
```

### Done Means

- [ ] Mutation testing is no longer just "we have a tool installed."
- [ ] A developer can see which mutants survived and what to do next.
- [ ] The signal is narrow enough to trust.

## 4. F1 - Close Dependency Alerts Cleanly

Plain-English goal: GitHub is warning about vulnerable packages. Some can be fixed now, some cannot. Fix what has a patch, and track what does not.

### Target Outcome

- [ ] GitPython is pinned or resolved to `3.1.47` or later wherever it exists.
- [ ] Dependabot closes GitPython alerts, or any stale alert is documented with evidence.
- [ ] The unpatched `pip` advisory stays visible until upstream publishes a fixed version.
- [ ] Dependency workflow remains reproducible and hash-checked.

### Checklist

- [x] Add `GitPython>=3.1.47,<4` to `install/requirements-dev.in`.
- [x] Regenerate `install/requirements-dev.txt` with `gitpython==3.1.47` and hashes.
- [x] Add local tracking note for `pip` advisory because GitHub issues are disabled.
- [ ] After PR merge, re-check Dependabot alerts #9 through #12.
- [ ] If `uv.lock` GitPython alerts remain but local `uv.lock` has no GitPython entry, capture that as a stale-alert finding.
- [ ] Watch for a patched `pip` release for `GHSA-58qw-9mgm-455v`.
- [ ] Once patched, update all affected manifests and verify alerts #7 and #8 close.

Validation:

```bash
bash scripts/check_requirements_drift.sh
pip install --dry-run --require-hashes -r install/requirements-dev.txt
gh api 'repos/jtn0123/InkyPi/dependabot/alerts?state=open&per_page=20'
```

### Done Means

- [ ] No actionable patched dependency alert remains open.
- [ ] Unpatched upstream advisories have a clear owner and closure condition.
- [ ] Dependency docs/reporting match live GitHub evidence.

## 5. B1 - Make Request Parsing Match Response Contracts

Plain-English goal: outgoing API responses are already disciplined. Incoming requests should be just as disciplined. Instead of each route hand-parsing forms and JSON in its own style, use typed request models that validate inputs consistently.

### Target Outcome

- [ ] Mutating playlist routes use typed request parsing.
- [ ] Plugin add/update/preview/update-now routes use typed request parsing.
- [ ] Settings import/update/isolation routes use typed request parsing.
- [ ] Validation errors are field-level and consistent across JSON and form submissions.
- [ ] Existing response envelope contracts stay intact.

### Suggested PR Split

#### PR 5.1 - Playlist Request Models

- [ ] Add playlist create/update/reorder request models in `src/utils/request_models.py` or a dedicated request-model module.
- [ ] Replace inline parsing in `src/blueprints/playlist.py`.
- [ ] Add tests for invalid names, invalid IDs, invalid times, and malformed JSON/form payloads.

Validation:

```bash
PYTHONPATH=src pytest -q tests/integration/test_playlist_routes.py tests/integration/test_playlist_crud_e2e.py tests/contracts/test_json_envelope.py
PYTHONPATH=src python3 -m mypy src/utils src/blueprints/playlist.py
```

#### PR 5.2 - Plugin Request Models

- [ ] Add plugin add/update/preview/update-now request models.
- [ ] Replace inline parsing in `src/blueprints/plugin.py`.
- [ ] Preserve HTMX and JSON caller behavior.
- [ ] Add tests for missing plugin IDs, invalid instance IDs, invalid refresh/update-now payloads, and field errors.

Validation:

```bash
PYTHONPATH=src pytest -q tests/integration/test_plugin_routes.py tests/integration/test_plugin_validation.py tests/integration/test_plugin_update_now.py tests/contract
PYTHONPATH=src python3 -m mypy src/utils src/blueprints/plugin.py
```

#### PR 5.3 - Settings Request Models

- [ ] Add request models for settings import/export/update/isolation controls.
- [ ] Replace repeated parsing in settings submodules.
- [ ] Keep privileged-action protections unchanged.
- [ ] Add tests for malformed imports, invalid isolation values, and missing fields.

Validation:

```bash
PYTHONPATH=src pytest -q tests/integration/test_settings_routes.py tests/integration/test_settings_save_errors.py tests/integration/test_settings_update_flows.py tests/integration/test_privileged_flow_security.py
PYTHONPATH=src python3 -m mypy src/blueprints/settings src/utils
```

### Done Means

- [ ] Request parsing has one obvious pattern.
- [ ] Field validation behavior is easier to test.
- [ ] Route files become smaller and less defensive.
- [ ] Contract tests still pass.

## Suggested Order

1. [ ] Finish and merge PR #594: grade report, GitPython patch, pip tracking.
2. [ ] Re-check Dependabot after merge.
3. [ ] Do PR 1.1: refresh recorder extraction.
4. [ ] Do PR 1.2: display pipeline extraction.
5. [ ] Do PR 1.3: execution policy extraction.
6. [ ] Do PR 2.1: progressive disclosure split.
7. [ ] Do PR 2.2: plugin page global-state reduction.
8. [ ] Do PR 5.1: playlist request models.
9. [ ] Do PR 5.2: plugin request models.
10. [ ] Do PR 5.3: settings request models.
11. [ ] Do PR 3.1: narrow mutation scope.
12. [ ] Do PR 3.2: mutation artifacts and policy.

## Milestones

### Milestone 1 - Dependency And Audit Cleanup

- [ ] PR #594 merged.
- [ ] GitPython alerts verified closed or stale.
- [ ] `pip` advisory tracking remains current.

### Milestone 2 - Refresh Loop Maintainability

- [ ] Recorder extracted.
- [ ] Display pipeline extracted.
- [ ] Execution policy extracted.
- [ ] Refresh tests pass cleanly.

### Milestone 3 - Frontend Maintainability

- [ ] Progressive disclosure split.
- [ ] Plugin page script split.
- [ ] Browser smoke and key UI journeys pass.

### Milestone 4 - Request Contract Maturity

- [ ] Playlist request models landed.
- [ ] Plugin request models landed.
- [ ] Settings request models landed.
- [ ] Response contract tests remain green.

### Milestone 5 - A- Readiness Check

- [ ] Re-run codebase grade.
- [ ] Re-run handoff UI screenshots with populated data.
- [ ] Confirm no patched high/critical dependency alerts remain.
- [ ] Confirm CI gates are still green.
- [ ] Decide whether remaining work is polish or true release risk.
