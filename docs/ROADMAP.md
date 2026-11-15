# Roadmap

The single list of what is still open. InkyPi is a personal project with one
user, so anything aimed at onboarding or multi-user setups is out of scope.

Detailed write-ups stay where they were made; this page links to them rather
than repeating them. Older planning docs that are fully done or superseded live
in [`archive/`](./archive/).

Last reconciled: 2026-11-15.

## Display output

- [ ] **Compact layouts for very small panels.** Weather and the calendar's
      week/month grids are too dense to read at 250×122. Needs a dedicated
      small-panel layout, not a CSS tweak.
- [ ] **Warn when `calendar.min.js` is missing.** It is an install-time vendor
      file outside git; without it the calendar renders blank and nothing says
      why. `scripts/dry_run_plugin.py` warns since #766, but the running app
      does not: fold it into the boot asset check (review B10).
- [ ] **Overflow coverage for calendar and weather.** The cross-platform text
      fit test (`tests/snapshots/test_render_text_fit.py`) does not cover them
      yet: calendar needs the vendor file, weather needs a larger mock payload.
- [ ] Gradient fills in the weather chart and GitHub heatmap look noisy on
      2-colour panels — a design call rather than a bug.

## Device and reliability

Open items from the [August 2026 device review](./upstream-and-device-review-2026-08.md):

- [ ] **B8 — Panel-wear odometer**: lifetime refresh count and per-plugin
      display hours.
- [ ] **B13 — Minimal fallback UI** that still works when the asset bundle is
      broken.
- [ ] **B14 — Physical button** (next plugin / refresh / blackout). Hardware-gated.
- B11 (startup QR code) and B15 (multi-device registry) are dropped: one
  device, one user.

## Upstream harvest

Still-open ports from the [April review](./archive/upstream-review-2026-04.md),
tracked in Linear:

- [ ] JTN-767 — plugin fallback logic and deprecation cleanup
- [ ] JTN-773 — mutable-default and security hardening batch
- [ ] JTN-770 — Google Keep plugin
- [ ] JTN-771 — "Save as new instance" button
- [ ] JTN-774 — configurable `image_url` download timeout
- [ ] JTN-775 — servo control / rotating frame

## Code health

- [ ] `FONTS["ds-digi"]` points at `static/fonts/DS-DIGI.TTF`; the file lives
      under `DS-DIGI/`. Unused today.

## Grade follow-ups

The remaining code-quality items come from a local grade report
(`.claude/grade-report.md`, which is not committed); the IDs refer to it.

- [ ] **A1** — Give scheduling policy one owner; next-due and next-up maths is
      still repeated across the scheduler and the routes.
- [ ] **A4 / B5** — Domain errors carry HTTP status codes, so the same failure
      gets different statuses on different routes.
- [ ] **A5** — `blueprints/settings/__init__.py` is a service locator for
      updates, logs, the version check and benchmarks.
- [ ] **A6** — The main process loads plugin code (and its imports) on each
      refresh to pick a progress label and ask `skip_display_condition`.
- [ ] **C6** — Modal dialogs handle keyboard focus inconsistently.
- [ ] **C8–C12** — Other front-end cleanups: `plugin_form.js`, large page
      closures and copied helpers, badge colours, leaked bundle globals,
      one-off breakpoints.
- [ ] **C5 / D4** — JS tests assert on source text instead of behaviour.
- [ ] **E3** — The service runs as root with no systemd hardening.
- [ ] **E5** — Updates trust release files; tags are not signed or verified.
- [ ] **G3** — The forkserver preloads the whole web app, not what workers need.
- [ ] **I4** — CI duplicates installs and checks.

## Closed since the last reconcile

- [x] Split the largest modules: `refresh_task/task.py` (#705),
      `blueprints/plugin.py` (#706), `utils/http_utils.py` (#707) and
      `blueprints/playlist.py` (#708).
- [x] Re-audit the dashboard and playlists with real data — done while
      dogfooding with populated playlists and history (#695).
- [x] `scripts/render_weather_mock.py` (imported `pytz`) was replaced by
      record/replay in `scripts/dry_run_plugin.py` (#766).
