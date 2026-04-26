# Codebase Grade Report

**Project:** InkyPi
**Audited:** 2026-04-25
**Baseline:** `origin/main` at `d67a3dc` (`1.0.6`)
**Stack:** Python 3.11-3.13, Flask/Waitress, Jinja2, vanilla JS/CSS, Raspberry Pi install/update shell, pytest/Playwright/GitHub Actions, uv runtime lockfile

## PR Evaluation Process

This report is intentionally checked into `docs/` so it can be reviewed, commented on, and validated through the normal PR process. The grading artifact should be evaluated with the same release discipline as code changes:

1. Review the grades and improvement IDs for accuracy against current `origin/main`.
2. Confirm the top-five recommendations are still the right next PR slices before implementation.
3. Let GitHub Actions run the repository gates on the report PR, even though the change is documentation-only.
4. After merge, use the item IDs below as stable backlog handles, for example "do A1 and C1".

Local validation used for this audit:

```bash
git fetch origin main --prune
PYTHONPATH=src python3 -m mypy src
gh pr list --state open --limit 20
gh api 'repos/jtn0123/InkyPi/dependabot/alerts?state=open&per_page=20'
```

Current signals from the audit pass:

- `mypy src` passes with `Success: no issues found in 135 source files`.
- `scripts/mypy_src_baseline.txt` is `0`; `scripts/mypy_tests_baseline.txt` is `7450`.
- There are no open PRs in `jtn0123/InkyPi` at the time of the audit.
- GitHub Dependabot reports 6 open alerts: 4 high `GitPython` alerts across `uv.lock` and `install/requirements-dev.txt` with patched version `3.1.47`, plus 2 medium `pip` alerts (`GHSA-58qw-9mgm-455v` / `CVE-2026-3219`) with no patched version. The current branch should verify whether the `uv.lock` `GitPython` alerts are stale, because `GitPython` is not present in this checkout's `uv.lock`.
- The most recent merged PR on `main` is PR #593, and its recorded checks passed across lint/type-check, pytest 3.11/3.12/3.13, install matrix, runtime smoke, browser smoke, coverage gate, SonarCloud, CodeQL, Semgrep, Trivy, gitleaks, dependency review, and CodeRabbit.

## Summary

| ID | Category | Grade | Items |
|----|----------|-------|-------|
| A | Architecture & Design | B | 3 |
| B | Backend Quality | B+ | 3 |
| C | Frontend Quality | B- | 3 |
| D | Testing & Reliability | B+ | 3 |
| E | Security | A- | 3 |
| F | Dependencies & Tech Currency | B- | 3 |
| G | Performance & Scalability | B+ | 2 |
| H | Documentation & Onboarding | B | 2 |
| I | Developer Experience & Tooling | B+ | 3 |
| **Overall** | | **B+** | **25** |

**Top 5 highest-leverage PR slices:** A1+G2, C1+C3, D1, F1, B1

## Three-Snapshot Comparison

This comparison uses the older audit/readiness context as a directional yardstick, then rechecks the current repo state before assigning today's grades.

| ID | Category | Original 2026-04-19 | Middle 2026-04-24 | Current 2026-04-25 | Movement |
|----|----------|---------------------|-------------------|--------------------|----------|
| A | Architecture & Design | B- | B | B | Held: service/collaborator extraction helped, but the largest coordinators are still large. |
| B | Backend Quality | B- | B | B+ | Up: typed production code and route/contract fixes made API behavior more enforceable. |
| C | Frontend Quality | C+ | B- | B- | Held: accessibility and UI coverage are good, but JS/CSS maintainability remains the main ceiling. |
| D | Testing & Reliability | B | B+ | B+ | Held high: pytest matrix, browser smoke, coverage, install, and runtime gates passed; mutation signal is still the next frontier. |
| E | Security | B+ | A- | A- | Held high: CodeQL, Semgrep, Trivy, gitleaks, SonarCloud, dependency review, and hardening coverage are all present in the current gate set. |
| F | Dependencies & Tech Currency | B- | B | B- | Down: uv runtime locking is strong, but the live Dependabot view now has 6 alerts: 4 high `GitPython` alerts with a `3.1.47` patch and 2 medium `pip` alerts with no patched version. |
| G | Performance & Scalability | B | B+ | B+ | Held: resource budgets and smoke/perf gates are strong, but budget policy is scattered. |
| H | Documentation & Onboarding | B- | B | B | Held: docs are broad; architecture/testing docs need a small sync pass after recent refactors. |
| I | Developer Experience & Tooling | C+ | B | B+ | Up: `PYTHONPATH=src mypy src` now passes and `scripts/mypy_src_baseline.txt` is 0. |
| **Overall** | | **B-** | **B** | **B+** | Up: the repo crossed from "good with noisy debt" into "strong, enforceable quality gates." |

## A - Architecture & Design - B

The codebase now has real architectural boundaries: refresh-task collaborators exist, service workflow modules exist, settings is package-split, and CI protects several behavioral contracts. The grade stays at B because the main coordinator and route files remain large: `src/refresh_task/task.py` is 1563 lines, `src/blueprints/plugin.py` is 1407 lines, and `src/blueprints/playlist.py` is 1086 lines. The architecture is professional, but not yet reference-grade because important flows still require reading across broad modules.

### A1 - Finish decomposing the refresh coordinator
- **Where:** `src/refresh_task/task.py:220`, `src/refresh_task/task.py:630`, `src/refresh_task/task.py:1040`
- **What's wrong:** `RefreshTask` still mixes execution policy, display persistence, fallback images, metrics, subprocess cleanup, and event emission. This keeps reliability work concentrated in a high-blast-radius module.
- **Fix:** Extract plugin execution/retry policy into `src/refresh_task/executor.py`, display persistence/fallback into `src/refresh_task/display_pipeline.py`, and benchmark/progress recording into a recorder collaborator. Keep `RefreshTask` as loop coordinator.
- **Effort:** L
- **Grade lift:** B -> B+ (turns the largest coordinator into smaller testable units)

### A2 - Complete route-to-service migration for plugin and playlist workflows
- **Where:** `src/blueprints/plugin.py:608`, `src/blueprints/plugin.py:880`, `src/blueprints/playlist.py:640`, `src/services/plugin_workflows.py:114`, `src/services/playlist_workflows.py:229`
- **What's wrong:** Service modules exist, but route files still own preview rendering, update-now policy, playlist create/update, ETA caching, and response branching.
- **Fix:** Move update-now/preview policy into `src/services/plugin_workflows.py` and playlist create/update/delete plus ETA calculation into `src/services/playlist_workflows.py`. Keep blueprints to request parsing and response mapping.
- **Effort:** L
- **Grade lift:** B -> B+ (makes the service layer consistent instead of partial)

### A3 - Replace settings `_mod` coupling with explicit collaborators
- **Where:** `src/blueprints/settings/_updates.py:9`, `src/blueprints/settings/_config.py:8`, `src/blueprints/settings/_logs.py:8`
- **What's wrong:** Settings submodules still import shared mutable state and helpers through `blueprints.settings as _mod`, hiding dependencies behind the package boundary.
- **Fix:** Introduce update, log, config, and benchmark service helpers with explicit inputs. Leave route registration in `__init__.py`, but move shared state behind typed coordinator objects.
- **Effort:** M
- **Grade lift:** B -> B+ (makes the package split an actual dependency boundary)

## B - Backend Quality - B+

Backend quality improved after the mypy/security push because production code now type-checks cleanly: `PYTHONPATH=src python3 -m mypy src` reports success across 135 source files, and `scripts/mypy_src_baseline.txt` is 0. The route split work also exposed and fixed real contract gaps in `src/schemas/endpoint_map.py`, which is exactly the kind of bug strong backend contracts should catch. The grade is B+ rather than A- because validation/request modeling is still uneven and several fallback paths still rely on broad exception handling.

### B1 - Promote request validation helpers into reusable typed request models
- **Where:** `src/blueprints/playlist.py:66`, `src/blueprints/playlist.py:694`, `src/blueprints/plugin.py:896`, `src/blueprints/settings/_config.py:200`, `src/utils/request_models.py`
- **What's wrong:** Response contracts are strong, but request parsing still varies by route. Playlist names, plugin IDs, refresh settings, import payloads, and form/file handling do not yet share one model style.
- **Fix:** Expand `src/utils/request_models.py` for playlist create/update, add-plugin, update-now, settings import, and isolation settings. Each model should return typed parsed values plus field-level errors.
- **Effort:** M
- **Grade lift:** B+ -> A- (makes mutating API behavior easier to reason about and test)

### B2 - Normalize expected operational fallbacks away from broad exceptions
- **Where:** `src/services/plugin_workflows.py:119`, `src/services/playlist_workflows.py:190`, `src/refresh_task/task.py:253`, `src/display/display_manager.py:293`
- **What's wrong:** Some expected recoverable cases still use broad `except Exception` paths. That blurs config lookup failures, validation failures, plugin failures, and true internal bugs.
- **Fix:** Add typed result objects or domain exceptions for known recoverable cases. Reserve broad catches for process-boundary cleanup, hardware best-effort behavior, or startup survival paths.
- **Effort:** M
- **Grade lift:** B+ -> A- (keeps operational resilience while improving debug signal)

### B3 - Finish canonical JSON envelope adoption on async render jobs
- **Where:** `src/blueprints/plugin.py:808`, `src/blueprints/plugin.py:913`, `src/refresh_task/job_queue.py:87`, `src/schemas/endpoint_map.py`
- **What's wrong:** A few async job endpoints still sit outside the strongest response-envelope pattern. That creates avoidable special cases for contract tests and frontend callers.
- **Fix:** Convert remaining raw job payloads to `json_success` / `json_error`, add schemas, and update tests and callers for the canonical shape.
- **Effort:** S
- **Grade lift:** B+ -> A- (removes a visible API consistency exception)

## C - Frontend Quality - B-

The frontend has improved accessibility, browser smoke coverage, data-action hooks, and safer UI patterns, but its maintainability ceiling is still real. `src/static/styles/main.css` is 11000 lines, `src/static/scripts/plugin_page.js` is 1145 lines, and `src/static/scripts/progressive_disclosure.js` is 908 lines. The UI is stronger than the original C+ grade suggested, but the implementation still has several large files that make iterative frontend work more expensive than it should be.

### C1 - Split `progressive_disclosure.js` into focused UI modules
- **Where:** `src/static/scripts/progressive_disclosure.js:18`, `src/static/scripts/progressive_disclosure.js:250`, `src/static/scripts/progressive_disclosure.js:364`, `src/static/scripts/progressive_disclosure.js:800`
- **What's wrong:** One class owns settings modes, validation, tooltips, wizard navigation, live preview, change summaries, canvas preview effects, and lightbox behavior.
- **Fix:** Split into `settings_mode.js`, `settings_wizard.js`, `live_preview.js`, and `preview_lightbox.js`; move shared escaping/DOM helpers to `ui_helpers.js`.
- **Effort:** M
- **Grade lift:** B- -> B (shrinks the highest-complexity frontend script)

### C2 - Treat generated CSS as generated and keep source partials authoritative
- **Where:** `src/static/styles/main.css:1`, `src/static/styles/partials/`, `src/static/styles/_imports.css:1`, `scripts/build_css.py`
- **What's wrong:** CSS partials exist, but the shipped 11000-line `main.css` remains present and easy to inspect or edit directly, which can confuse the source of truth.
- **Fix:** Add a generated-file header and CI check that fails if partials and generated CSS drift. Document that edits go through `src/static/styles/partials/`.
- **Effort:** S
- **Grade lift:** B- -> B (reduces style maintenance mistakes)

### C3 - Reduce global surface in plugin-page JavaScript
- **Where:** `src/static/scripts/plugin_page.js:84`, `src/static/scripts/plugin_page.js:367`, `src/static/scripts/plugin_page.js:914`
- **What's wrong:** The plugin page keeps many behaviors in one closure and exposes page functions globally, increasing accidental coupling across preview, schedule, modal, and API-key flows.
- **Fix:** Export a smaller page controller, move modal/focus helpers to shared UI utilities, and split preview/status/progress/schedule actions into modules.
- **Effort:** M
- **Grade lift:** B- -> B (reduces the blast radius of plugin-page changes)

## D - Testing & Reliability - B+

Reliability is genuinely strong now. The current gate shape includes pytest across Python 3.11, 3.12, and 3.13; browser smoke; coverage gate; install matrix; runtime smoke; install smoke; security/SBOM; CodeQL; Semgrep; Trivy; gitleaks; SonarCloud; and dependency review. The grade stops at B+ because mutation testing is still scheduled/nightly rather than a consistently actionable merge signal.

### D1 - Make mutation testing actionable instead of mostly aspirational
- **Where:** `.github/workflows/ci.yml:567`, `pyproject.toml:111`, `docs/mutation_testing.md:93`
- **What's wrong:** Mutation testing exists, but it is not yet a practical merge signal. Broad mutation scope can still be expensive before producing useful artifacts.
- **Fix:** Shard mutation scope by package or create a curated deterministic mutation harness for top-risk modules. Upload per-shard reports and fail on surviving mutants in completed shards.
- **Effort:** M
- **Grade lift:** B+ -> A- (turns an advanced reliability idea into actual signal)

### D2 - Add a fast local UI smoke lane
- **Where:** `scripts/test.sh:22`, `scripts/test.sh:140`, `docs/testing.md:31`, `.github/workflows/ci.yml:630`
- **What's wrong:** Browser and a11y gates are strong in CI but heavier than the default local loop, so some frontend regressions are found after push.
- **Fix:** Add `scripts/test.sh ui-fast` covering one browser smoke, one a11y page, one layout overlap case, and one plugin workflow.
- **Effort:** S
- **Grade lift:** B+ -> A- (moves key UI feedback earlier)

### D3 - Store flake and soak results as durable trend artifacts
- **Where:** `.github/workflows/ci.yml:498`, `.github/workflows/ci.yml:539`, `scripts/preflash_validate.sh:153`
- **What's wrong:** Flake and soak lanes exist, but trend visibility depends on manually reading CI logs.
- **Fix:** Emit JSON summaries from flake/soak validation, upload them as artifacts, and summarize trends on scheduled runs.
- **Effort:** M
- **Grade lift:** B+ -> A- (makes reliability drift visible before failures)

## E - Security - A-

Security remains one of the strongest areas. The repo has explicit auth docs, CSRF validation, CSP middleware/reporting, SSRF/DNS-rebinding protections, rate limiting, secret redaction, hash-pinned dependency flows, SBOM/security scans, and dedicated privileged-flow tests. The grade is A- rather than A because a few deployment-safety and auditability improvements would still make the appliance safer for non-expert users.

### E1 - Retire or narrow stale Sonar architecture suppressions
- **Where:** `sonar-project.properties:21`
- **What's wrong:** Some suppressions are explained, but long-lived policy exceptions can make future architecture/security feedback less trustworthy.
- **Fix:** Update the Sonar architecture model to match accepted current boundaries, then remove suppressions that become unnecessary. Add owner/date/removal condition for any remaining exception.
- **Effort:** M
- **Grade lift:** A- -> A (keeps quality gates strict without stale policy exceptions)

### E2 - Add a first-run auth posture warning for exposed network installs
- **Where:** `src/app_setup/auth.py:1`, `src/app_setup/security_middleware.py:210`, `docs/auth.md:1`, `docs/installation.md`
- **What's wrong:** PIN auth is optional, which is reasonable for a LAN appliance, but a broader network bind with no auth should be visibly called out.
- **Fix:** Add a first-run diagnostics warning when auth is disabled and the app is bound beyond localhost. Link directly to `INKYPI_AUTH_PIN` and `INKYPI_READONLY_TOKEN`.
- **Effort:** S
- **Grade lift:** A- -> A (improves safe-by-default deployment posture)

### E3 - Add consolidated privileged-action audit logging
- **Where:** `src/blueprints/settings/_updates.py`, `src/blueprints/settings/_config.py`, `src/blueprints/settings/_system.py`
- **What's wrong:** Privileged routes are guarded, but there is not one obvious audit trail for update, rollback, shutdown, import/export, and API-key changes.
- **Fix:** Add an audit logger that records request id, remote address, action, sanitized metadata, and result for privileged state-changing routes.
- **Effort:** S
- **Grade lift:** A- -> A (improves incident reconstruction without changing controls)

## F - Dependencies & Tech Currency - B-

Runtime dependency handling is mostly solid: `pyproject.toml` declares Python `>=3.11,<3.14`, `uv.lock` is present, docs explain dependency locking, and CI runs lockfile drift plus security/SBOM checks. The grade drops to B- because live Dependabot currently reports 6 open alerts: 4 high `GitPython` alerts with patched version `3.1.47`, plus 2 medium `pip` alerts with no patched version. Dev dependencies are still handled through a separate pip-compile-style workflow, so dependency closure spans two maintenance paths.

### F1 - Patch GitPython and track the open `pip` advisory
- **Where:** `install/requirements-dev.in`, `install/requirements-dev.txt`, `uv.lock`, GitHub Dependabot alerts #7 through #12
- **What's wrong:** GitHub reports 4 high `GitPython` alerts (`GHSA-rpm5-65cw-6hj4` and `GHSA-x2qx-6953-8485`) with patched version `3.1.47`, plus 2 medium `pip` alerts (`GHSA-58qw-9mgm-455v` / `CVE-2026-3219`) with no patched version. The current checkout does not contain `GitPython` in `uv.lock`, so those two `uv.lock` alerts need verification after the dev requirements bump lands.
- **Fix:** Bump `GitPython` to `3.1.47` in the regenerated dev requirements path, then verify Dependabot closes the `install/requirements-dev.txt` alerts and either closes or confirms the stale `uv.lock` alerts. For `pip`, keep a short tracking issue or PR note that records the advisory, affected manifests, current lack of patched version, and planned closure condition.
- **Effort:** S
- **Grade lift:** B- -> B (turns live dependency findings into an owned closure path)

### F2 - Finish migrating dev dependencies to uv
- **Where:** `docs/dependency_locking.md:61`, `install/requirements-dev.in`, `install/requirements-dev.txt`, `pyproject.toml`
- **What's wrong:** Runtime deps use uv, but dev deps still use pip-compile-style files. That creates split-brain dependency maintenance.
- **Fix:** Move dev dependencies into pyproject optional/dependency groups, regenerate `uv.lock`, export dev requirements from uv, and update docs/scripts.
- **Effort:** M
- **Grade lift:** B- -> B+ (completes the dependency-tooling migration after the live advisory is handled)

### F3 - Add a non-blocking dependency freshness report
- **Where:** `.github/dependabot.yml`, `.github/workflows/ci.yml`, `docs/dependencies.md`
- **What's wrong:** CVE/security checks are strong, but there is no separate signal for secure-but-aging packages.
- **Fix:** Add a weekly freshness report using uv tooling or equivalent, upload a Markdown artifact, and use it for planning rather than blocking PRs.
- **Effort:** S
- **Grade lift:** B- -> B (improves proactive maintenance)

## G - Performance & Scalability - B+

For a Pi-targeted Flask appliance, performance discipline is above average. CI has benchmark/perf, memory-cap, install, runtime smoke, and preflash validation lanes; runtime code has bounded job retention, ETA caching, and benchmark persistence. The grade remains B+ because budgets are scattered rather than presented as one coherent resource policy, and performance instrumentation is still mixed into large hot-path modules.

### G1 - Centralize resource budgets
- **Where:** `src/refresh_task/job_queue.py:25`, `src/blueprints/playlist.py:97`, `src/refresh_task/housekeeping.py:1`, `docs/benchmarking.md`
- **What's wrong:** Job retention, ETA cache size, plugin timeout, history retention, memory budgets, and benchmark thresholds live in different places.
- **Fix:** Add `docs/resource_budgets.md` and a small constants/config reference for defaults that are not environment-driven.
- **Effort:** S
- **Grade lift:** B+ -> A- (makes device resource constraints explicit)

### G2 - Move display-pipeline metrics out of the refresh coordinator
- **Where:** `src/refresh_task/task.py:330`, `src/refresh_task/task.py:630`
- **What's wrong:** Stage timing and benchmark persistence are valuable but interwoven with display correctness paths.
- **Fix:** Extract timing and event persistence into a recorder object consumed by the refresh flow.
- **Effort:** M
- **Grade lift:** B+ -> A- (keeps observability while lowering hot-path complexity)

## H - Documentation & Onboarding - B

Documentation is broad: README, architecture, ADRs, development, testing, security, dependency locking, profiling, benchmarking, plugin building, and troubleshooting are all present. The grade stays B because the recent code movement means architecture and testing docs need another synchronization pass.

### H1 - Refresh architecture docs to match current package boundaries
- **Where:** `docs/architecture.md:21`, `docs/architecture.md:56`, `src/refresh_task/scheduler.py`, `src/services/plugin_workflows.py`, `src/services/playlist_workflows.py`
- **What's wrong:** The architecture document still lags behind current service and refresh collaborator boundaries in places.
- **Fix:** Update the component diagram and request/refresh flow to include `src/services/`, refresh collaborators, and settings package modules.
- **Effort:** S
- **Grade lift:** B -> B+ (keeps onboarding docs credible)

### H2 - Add a "which validation gate should I run?" table
- **Where:** `docs/testing.md:1`, `docs/development.md:188`, `scripts/test.sh:22`, `scripts/preflash_validate.sh:195`
- **What's wrong:** The testing docs are thorough, but the number of gates is high enough that choosing the right command takes effort.
- **Fix:** Add a table mapping change type to command: backend route, plugin render, frontend template/script, install/update, security-sensitive, performance-sensitive, release workflow.
- **Effort:** S
- **Grade lift:** B -> B+ (reduces contributor friction)

## I - Developer Experience & Tooling - B+

This is the biggest post-merge grade lift. The current merged state has `scripts/mypy_src_baseline.txt` set to 0 and `PYTHONPATH=src python3 -m mypy src` succeeds. Combined with Ruff, Black, shellcheck, pre-commit, sharded tests, CI gate, CodeQL, Semgrep, Trivy, gitleaks, Sonar, browser smoke, coverage, and install gates, the repo's quality feedback is now high-signal. It is B+ rather than A because test typing debt and local dependency bootstrap still lag behind the production-code gate.

### I1 - Continue the test typing ratchet after clearing `src`
- **Where:** `mypy.ini`, `scripts/lint.sh`, `scripts/mypy_tests_baseline.txt`, `tests/`, `docs/typing.md`
- **What's wrong:** Production code is clean, but test typing remains advisory debt at a baseline of `7450`. That matters because the test suite is now large enough for fixture/type drift to hide real mistakes.
- **Fix:** Keep the tests mypy baseline ratcheted, then clean one test cluster at a time starting with contract/security tests and shared fixtures.
- **Effort:** M
- **Grade lift:** B+ -> A- (extends type trust into the test harness)

### I2 - Keep `src` mypy at zero with a strict no-regression gate
- **Where:** `scripts/mypy_src_baseline.txt:1`, `scripts/lint.sh`, `.github/workflows/ci.yml`
- **What's wrong:** The baseline is now zero, so any future production mypy issue should be treated as a regression, not a new baseline.
- **Fix:** Simplify the ratchet path so `mypy src` success is the expected state. Keep the baseline file only as a guard if useful, but make new `src` mypy errors fail locally and in CI.
- **Effort:** S
- **Grade lift:** B+ -> A- (locks in the value of the big cleanup)

### I3 - Consolidate local bootstrap around uv
- **Where:** `scripts/venv.sh`, `scripts/dev.sh`, `scripts/lint.sh:9`, `scripts/test.sh:8`, `docs/dependency_locking.md:61`
- **What's wrong:** The runtime lockfile story is uv-based, but local scripts still support a mixed venv/pip/dev-requirements path.
- **Fix:** After dev dependency migration, make uv the default bootstrap path while preserving documented Pi fallbacks. Print one clear remediation command when dependencies are missing.
- **Effort:** M
- **Grade lift:** B+ -> A- (aligns local setup with dependency policy)

## Direction From Here

The next best direction is not more broad hardening for its own sake. The repo is now strong enough that the highest-value work is targeted consolidation:

1. **A1 + G2:** shrink the refresh coordinator and move display-pipeline metrics into a recorder.
2. **C1 + C3:** split the two largest frontend scripts before adding more UI behavior.
3. **D1:** turn mutation testing into practical signal on the riskiest modules.
4. **F1:** patch `GitPython` now, then keep the `pip` advisory visible until a patched release exists.
5. **B1:** make request parsing match the response-contract strength that already exists.

If those land cleanly, the realistic next-grade target is **A- overall**. The main constraint is no longer "does the repo have gates?" It does. The constraint is reducing the remaining large coordinators and making the strongest gates cheaper to use every day.
