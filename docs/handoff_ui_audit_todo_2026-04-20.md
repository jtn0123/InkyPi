# Handoff UI Audit To-Do

Date: 2026-04-20

Context:
Compare the real worktree at `${REPO_ROOT}` (checked out to the
`claude/infallible-montalcini-c71168` branch) against the prototype bundle
from `<handoff-artifact-path>/Update to InkyPi-handoff.zip`.

What already landed well:
- Persistent sidebar shell and shared pageheader language
- Dashboard hero, plugin tile grid, and playlist card visual direction
- Condensed settings console with section nav
- Plugin workflow split into configure/style/schedule tabs

Priority backlog:

## P0: Fix Real Regressions

- [x] Fix the `/settings` sticky-save collision.
  Floating UI (`Show Logs` and the global status badge) can block clicks on `#saveSettingsBtn` on short viewports.
  Target files: `src/templates/settings.html`, `src/static/styles/partials/_settings.css`, `src/static/styles/partials/_status_badge.css`

- [x] Keep fixed controls page-aware.
  The logs toggle is described as mobile-only, but its fixed positioning behaves like a global desktop overlay.
  Target files: `src/static/styles/partials/_settings.css`, `src/static/styles/partials/_responsive.css`

## P1: Finish Handoff Workflow Parity

- [x] Move scheduling into the plugin page's Schedule tab.
  Right now the tab is mostly explanatory text while the real controls still live in the `Add to Playlist` modal.
  Target files: `src/templates/plugin.html`, `src/static/scripts/plugin_page.js`

- [x] Make Dashboard "Quick switch" actually switch playlists.
  The current implementation mostly opens the Playlists page; the handoff implies direct activation or switching.
  Target files: `src/templates/inky.html`, `src/static/scripts/dashboard_page.js`, playlist routes or API as needed

- [x] Show a forward-looking refresh ETA or countdown on the dashboard.
  The current third hero cell shows time since last refresh, not when the next refresh will happen.
  Target files: `src/templates/inky.html`, `src/static/scripts/dashboard_page.js`

- [x] Add a dedicated Plugins navigation target.
  The handoff shell treats Plugins as a first-class destination; the current app still buries discovery inside the dashboard.
  Target files: `src/templates/macros/sidebar.html`, `src/blueprints/main.py`, plugin listing route or template if split out

## P2: Tighten Information Architecture

- [x] Decide whether the dashboard is a "current display" surface or also the plugin browser.
  If a dedicated Plugins page lands, keep the dashboard focused on live state, KPIs, and quick actions.

- [x] Reconcile the sidebar "Now showing" card with the hero-strip.
  The branch removed some duplication, but the sidebar card still has room to become more useful or more minimal.
  Target files: `src/templates/macros/sidebar.html`, `src/inkypi.py`

- [x] Simplify settings diagnostics vs logs.
  The settings page now has section tabs, diagnostics panels, a hidden logs frame, a logs toggle, and the global status badge. The pieces work, but the hierarchy still feels heavier than the handoff.
  Target files: `src/templates/settings.html`, `src/static/scripts/settings_page.js`

## P2: Polish and Consistency

- [x] Normalize action semantics and copy across pages.
  Examples: `Save Settings`, `Update preview`, `Update instance`, `Display Next`, `Open`, `Activate`.

- [x] Make KPI and overview cards degrade more gracefully when telemetry is missing.
  The handoff feels intentional even in empty states; some live cards still fall back to sparse placeholders.
  Target files: `src/templates/inky.html`, `src/static/scripts/dashboard_page.js`

- [x] Revisit preview-mode affordances for desktop and mobile.
  The handoff explicitly distinguishes fit and native behavior; the current implementation is close, but the interaction model could still be clearer.

## Validation Backlog

- [x] Keep the failing Playwright settings round-trip test green after each layout tweak.
  Current canary: `tests/integration/test_settings_round_trip_e2e.py`

- [x] Add a browser test for dashboard quick-switch behavior once direct switching exists.

- [x] Add browser coverage for the inline Schedule tab once modal-only scheduling is retired.

## Phase 2: Side-by-Side Parity Sweep

Status:
- The first wave of workflow parity is complete.
- The next wave is visual and state-density parity against the zip plus the latest side-by-side report.

### Dashboard

- [x] Rework the sidebar `NOW PLAYING` footer so the idle state still reads like the handoff card instead of a fallback placeholder.
  User callout: bottom-left dashboard footer still does not visually match the zip.
  Target files: `src/templates/macros/sidebar.html`, `src/static/styles/partials/_sidebar.css`

- [x] Normalize the dashboard header action cluster.
  User callout: top-right dashboard buttons feel inconsistent in sizing, spacing, and hierarchy versus the zip.
  Target files: `src/templates/inky.html`, `src/static/styles/partials/_dashboard.css`

- [x] Tighten dashboard vertical rhythm between the plugin area and the now/idle/next area.
  User callout: there is still too much dead white space compared to the handoff.
  Target files: `src/templates/inky.html`, `src/static/styles/partials/_dashboard.css`

- [ ] Re-audit the dashboard with real now-playing data and an active playlist.
  Current side-by-side is still dominated by idle-state emptiness.
  Target files: runtime data setup plus screenshot/report refresh

### Playlists

- [x] Rebuild the populated playlist rows to match the handoff's row density, preview balance, and action rhythm.
  User callout: playlist page UI/UX still does not match the zip closely enough.
  Target files: `src/templates/playlist.html`, `src/static/styles/partials/_playlists.css`, `src/static/scripts/playlist.js`

- [ ] Re-audit playlists with at least one populated rotation and one expanded card.
  The current comparison still uses an empty local playlist, so the row treatment is not yet proven.
  Target files: runtime data setup plus screenshot/report refresh

### Plugin Detail

- [x] Refactor the plugin detail page to match the handoff's calmer composition.
  Biggest current miss: the left column still reads like a dense production form instead of the handoff's editorial content stack.
  Target files: `src/templates/plugin.html`, `src/static/styles/partials/_plugins.css`

- [x] Move API-key management into a compact in-content card while keeping header state lighter.
  The zip uses a dedicated API card in the content column; the current page still pushes API state into the header too aggressively.
  Target files: `src/templates/plugin.html`, `src/static/styles/partials/_plugins.css`

- [x] Tighten the preview/progress aside into a clearer compare-first layout.
  The handoff preview area feels tighter and more obviously paired than the current `Preview & Apply` section.
  Target files: `src/templates/plugin.html`, `src/static/styles/partials/_plugins.css`, `src/static/styles/partials/_feedback.css`

- [ ] Re-capture the plugin detail page side-by-side after this pass.
  This page changed materially enough that the comparison board should be refreshed before calling parity finished.
  Target files: screenshot/report refresh

### API Keys

- [x] Flatten the API keys screen further so it reads like the zip instead of the production settings shell.
  User callout: API keys page still does not visually match the handoff closely enough.
  Target files: `src/templates/api_keys.html`, `src/templates/macros/api_key_card.html`, `src/static/styles/partials/_api-keys.css`

### Settings / History

- [ ] Decide which production extras on Settings stay and which should be visually reduced for parity.
  Current open drift: sticky save affordance, breadcrumb/device chrome, and live diagnostics surfaces still make the page feel busier than the handoff.
  Progress: status-badge chrome is now disabled on Settings, the save bar is compact again, and the page copy/navigation language is closer to the handoff.
  Target files: `src/templates/settings.html`, `src/static/styles/partials/_settings.css`

- [ ] Decide whether History should regain the handoff-style top metrics emphasis or stay intentionally more operational.
  Current drift is more about product direction than a broken implementation.
  Progress: status-badge chrome is now disabled on History, header chips are reduced, and the storage card title is closer to the handoff.
  Target files: `src/templates/history.html`, `src/static/styles/partials/_history.css`
