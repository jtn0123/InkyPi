### Future Improvements

## CSP-Compliant Refactoring Plan (High Priority)

### Overview
Transform InkyPi to be Content Security Policy (CSP) compliant by removing inline JavaScript, organizing external dependencies, and preserving functionality. Once complete, we can safely enforce CSP (not report-only) without breaking UI interactions.

### Current State (scoped findings)
- **Inline event handlers**: 83 across 16 HTML files (e.g., `onclick=`, `onchange=`).
- **Script tags**: 22 files contain `<script>` tags (mix of inline and external references).
- **Inline styles**: 28 `style="..."` attributes and 1 `<style>` block.
- **External CDNs in use**:
  - Leaflet (weather map) in `src/plugins/weather/settings.html`
  - Chart.js (weather render) in `src/plugins/weather/render/weather.html`
  - FullCalendar (calendar render) in `src/plugins/calendar/render/calendar.html`
- **CSP header**: Set in `src/inkypi.py` via `INKYPI_CSP` (report-only by default via `INKYPI_CSP_REPORT_ONLY`). Default value disallows inline scripts.

### Phase 1: Infrastructure Setup

- Create core JS and vendor structure to replace inline handlers and CDN dependencies.

1) Core JavaScript files (shared utilities)
   - `src/static/scripts/base.js`:
     - Modal helpers: `openModal`, `closeModal`, `closeResponseModal`
     - Collapsibles: `toggleCollapsible`
     - Form utilities: `clearField`, slider value sync helpers
     - Navigation wrappers (e.g., back)
     - Checkbox value pattern: `input.value = input.checked ? 'true' : 'false'`

2) Page-specific scripts
   - `src/static/scripts/plugin.js` (plugin configuration page)
   - `src/static/scripts/playlist.js`
   - `src/static/scripts/settings.js`
   - `src/static/scripts/history.js`
   - `src/static/scripts/api_keys.js`

3) Vendor dependencies (local copies)
   - `src/static/vendor/leaflet/`
   - `src/static/vendor/chartjs/`
   - `src/static/vendor/fullcalendar/`
   - Pin and vendor the exact versions currently used via CDN.

### Phase 2: Refactor Core Templates (remove inline handlers)

Order of implementation (highest impact first):
- `src/templates/response_modal.html` (already has external JS; remove remaining inline close handler)
- `src/templates/plugin.html` (many handlers: collapsibles, modals, file upload, actions)
- `src/templates/playlist.html` (playlist CRUD + modals)
- `src/templates/settings.html` (device settings, shutdown/reboot, sliders)
- `src/templates/history.html` (display, delete, clear, refresh)
- `src/templates/api_keys.html` (clear field, save/delete keys)

Approach:
- Replace attributes like `onclick="..."` with `addEventListener` in the corresponding `*.js` file.
- Keep function names stable where referenced from other scripts, but move definitions into external JS.

### Phase 3: Plugin-Specific Templates

1) Weather plugin (priority; uses CDNs)
- Files: `src/plugins/weather/settings.html`, `src/plugins/weather/render/weather.html`
- Actions:
  - Vendor Leaflet and Chart.js locally and update template references to `static/vendor/...`.
  - Move inline `<script>` logic and all `onclick`/`onchange` handlers to `src/static/scripts/weather.js` and `src/static/scripts/weather-render.js`.
  - Keep behavior: provider-based title options, checkbox value handling, map modal logic, charts rendering.

2) Calendar plugin (priority; uses CDN)
- Files: `src/plugins/calendar/settings.html`, `src/plugins/calendar/render/calendar.html`
- Actions:
  - Vendor FullCalendar locally and update template references.
  - Extract inline handlers: view selection, add/remove calendar inputs, checkbox value handling.
  - New file: `src/static/scripts/calendar.js`.

3) Remaining plugin settings (batch)
- Files: Clock, Image Upload, AI Image, Newspaper, Image URL, Image Folder, APOD, WPOTD, AI Text, etc.
- Actions:
  - Extract simple checkbox/value patterns and any buttons to `src/static/scripts/plugin-<name>.js` files.
  - Standardize on shared helpers from `base.js`.

### Phase 4: Styles and CSP Finalization

1) Inline styles cleanup
- Move the single `<style>` block to an external CSS file under `src/static/styles/`.
- Convert the most prominent `style="..."` attributes to CSS classes where beneficial (prioritize dynamic or frequently reused styles).

2) CSP policy updates
- After vendoring and refactor, remove external CDNs from CSP, keeping scripts and styles as `'self'`.
- Enforce CSP by setting `INKYPI_CSP_REPORT_ONLY=0`.
- Recommended baseline CSP (post-refactor):

```text
default-src 'self';
img-src 'self' data: https:;
style-src 'self' 'unsafe-inline';
script-src 'self';
font-src 'self' data:
```

Note: We can later remove `'unsafe-inline'` from `style-src` once all inline styles are gone.

### Phase 5: Testing and Validation

- Page-by-page functional testing: buttons, modals, forms, AJAX flows.
- Weather/Calendar: verify map picker and calendar display work with vendored assets.
- Browser console: verify zero CSP violations under enforced CSP.
- Automated tests: run existing suite; add UI tests where feasible for critical flows.

### Rollout Strategy
- Incremental edits with small commits per file/page.
- Keep CSP in report-only during the sweep; switch to enforce after validations pass.
- Rollback-ready: each step self-contained to facilitate reverts if needed.

### Rough Effort Estimate
- Phase 1: 2–3 hours
- Phase 2: 6–8 hours
- Phase 3: 4–6 hours
- Phase 4: 2–3 hours
- Phase 5: 2–4 hours
- Total: ~16–24 hours

### Success Criteria
- Zero CSP violations with CSP enforced (not report-only)
- All interactive features function as before
- External dependencies are served from `src/static/vendor/`
- No inline JavaScript in templates
- All tests pass


## UI Progress Bars and Stability-Focused UI Enhancements

### Overview
Add non-breaking, additive UI progress indicators for long-running operations and a set of stability-first UI enhancements (dark mode, skeletons, subtle animations, search, breadcrumbs, quick actions). Preserve current behavior as a fallback, avoid schema changes, and maintain test stability.

### Goals
- Implement reliable, determinate progress bars for long-running operations (manual update, background refresh, uploads).
- Keep all changes backward compatible; gracefully fall back to existing spinner behavior.
- Add discoverability and UX polish: dark mode with system detection, skeleton loading, subtle transitions, plugin filtering, breadcrumbs, and a quick actions toolbar.

### Assumptions & Current State
- Manual updates: `POST /plugin/update_now` (in `src/blueprints/plugin.py`) returns JSON success; no progress reporting.
- Background refresh runs in `src/refresh_task.py` via `RefreshTask`, `ManualRefresh`, `PlaylistRefresh`.
- UI uses spinner styles in `src/static/styles/main.css`; there is no progress bar component yet. A progress-like pattern exists in `src/templates/history.html` for storage usage.

### Design (Additive, Non-breaking)
1) Backend job tracking (in-memory, thread-safe)
   - Introduce a small job model (id, type, stage, percent, status, error, timestamps) guarded by a lock.
   - Track jobs in `RefreshTask` or new `utils/job_progress.py` with TTL cleanup; no device config/schema changes.
   - Instrument `ManualRefresh`/`PlaylistRefresh` with coarse milestones: 0% init → 20% prepare → 60% generate image → 80% save/display → 100% done.
   - `update_now` returns the existing success payload plus an optional `job_id` when progress is available.

2) Minimal API surface (read-only progress)
   - `GET /progress/<job_id>` → `{ percent, stage, status, error? }`.
   - Optional: `GET /progress/current` → latest background refresh job (for global banner).
   - No auth/role changes; simple 404 for unknown/expired jobs; TTL cleanup to bound memory.

3) Frontend progress UI (progressive enhancement)
   - New CSS classes for a reusable progress bar (normal and small variants) with CSS variables and `prefers-reduced-motion` support.
   - `plugin.html`: on submit, show upload progress (XHR) and, if a `job_id` is returned, poll `/progress/<job_id>` until completion. Fallback to existing spinner if no `job_id`.
   - `playlist.html`: optionally render a tiny inline progress bar for the instance currently refreshing.
   - `inky.html`: optional global, subtle progress banner when a background refresh is active.

4) Progressive fallback
   - If progress endpoints are unavailable or errors occur, retain current spinner-only behavior without breaking flows.

### Additional UI Enhancements (Stability-First Scope)
- Dark mode toggle with system preference detection (no breaking CSS changes; use variables).
- Skeleton loading states for preview image and plugin thumbnails; remove on `onload`.
- Subtle animations/transitions for state changes, gated by `prefers-reduced-motion`.
- Plugin grid search/filter by name on `inky.html` (client-side only).
- Breadcrumb navigation: “Home › Plugin › Instance” in `plugin.html` header.
- Quick actions toolbar: refresh now, save settings, add to playlist, open history (wire to existing endpoints).
- Hover previews for plugin grid thumbnails (non-blocking enhancement).

### Testing & Validation (Cloud-only first)
- Unit tests
  - Job lifecycle: create/update/complete/error/TTL cleanup.
  - Thread-safety under concurrent updates.
- Integration tests
  - `POST /plugin/update_now` preserves existing contract; includes `job_id` when available.
  - `GET /progress/<job_id>` advances from 0→100% and returns 404 after TTL.
  - Background refresh exposes `current` progress when enabled.
- UI smoke (headless/browser-lite)
  - Progress bar renders and completes; spinner fallback works when no `job_id`.
  - Upload progress displayed via XHR events.
- Regression
  - Existing test suite remains green; no schema/config mutations; incremental lint only where touched.

### Rollout & Safeguards
- Feature flag to disable UI polling (default enabled).
- Graceful degradation to spinner on any failure.
- Small, incremental edits with clear commits; easy rollback per page/module.

### Acceptance Criteria
- Manual updates show determinate progress when `job_id` is returned; otherwise show spinner.
- Background refresh progress can be surfaced without blocking the UI.
- No breaking changes to endpoints, templates, or device config; existing flows keep working.
- New progress endpoints covered by unit/integration tests; overall CI stays green.

### Risks & Mitigations
- Concurrency/races → guard with `threading.Lock`/`Condition`; test concurrent updates.
- Memory growth → TTL cleanup and capped job map size.
- Partial progress accuracy → use coarse, stable milestones to avoid fragile reporting.
- Network variance → polling at ~300–500 ms with backoff; timeout per job (~60 s) to avoid hangs.

