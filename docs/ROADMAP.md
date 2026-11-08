# Roadmap

The single list of what is still open. InkyPi is a personal project with one
user, so anything aimed at onboarding or multi-user setups is out of scope.

Detailed write-ups stay where they were made; this page links to them rather
than repeating them. Older planning docs that are fully done or superseded live
in [`archive/`](./archive/).

Last reconciled: 2026-10-30.

## Display output

- [ ] **Compact layouts for very small panels.** Weather and the calendar's
      week/month grids are too dense to read at 250×122. Needs a dedicated
      small-panel layout, not a CSS tweak.
- [ ] **Warn when `calendar.min.js` is missing.** It is an install-time vendor
      file outside git; without it the calendar renders blank and nothing says
      why. Fold into the boot asset check (review B10).
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

## Web UI

- [ ] Re-audit the dashboard and playlists with real data (an active playlist,
      a populated rotation) — earlier audits only saw empty states.

## Code health

- [ ] **Split the largest modules.** `blueprints/plugin.py`,
      `utils/http_utils.py` and `blueprints/playlist.py` each exceed ~1,000
      lines and carry most recent bug fixes. (`refresh_task/task.py` is done:
      split into mixin modules, none over ~600 lines.)
- [ ] `scripts/render_weather_mock.py` is stale (imports `pytz`).
- [ ] `FONTS["ds-digi"]` points at `static/fonts/DS-DIGI.TTF`; the file lives
      under `DS-DIGI/`. Unused today.
