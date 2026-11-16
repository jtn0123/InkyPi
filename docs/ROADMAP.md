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
(`.claude/grade-report.md`, which is not committed); the IDs refer to the
2026-11-15 regrade.

- [ ] **C12** — 14 different responsive breakpoints. Settling on 3–4 width
      tokens changes layouts, so each page needs a visual check.
- [x] **D1** — "CI gate (all checks pass)" is a required status check for
      `main`, set by the repository ruleset "main: require the CI gate". Its
      only bypass is the release deploy key, which pushes the version-bump
      commit. See `docs/development.md`.
- **E4** (won't do) — The service runs as root and keeps CAP_SYS_ADMIN.
      The suggested `SystemCallFilter=~@mount` and `RestrictNamespaces=yes`
      would break the Screenshot plugin: Chromium's sandbox runs as `nobody`
      and needs user namespaces and chroot. `systemd-run` stays open on
      purpose, because updates run through it. The only full fix is a
      non-root service user, which isn't worth it for a device on a private
      network that only its owner reaches.
- [x] **E5** — An update trusted a wheel whose hash is in the release's own
      manifest, and both came from the same editable release. Now the
      release workflow keeps each release a draft until the SBOM, wheelhouse
      and Pi image are attached, publishes it last, and pushes the release
      commit and tag with a deploy key. GitHub's immutable releases are on,
      so a published release's files and tag can't change. An update with no
      tag installs the latest published release, not the newest tag, which a
      draft already has. Signing tags and checking them in `do_update.sh` is
      not planned.
- [ ] **A4 / B5** (previous grade) — Direct-render statuses now match the
      refresh loop's (#877) and there is one `WorkflowError`. Left: check that
      the async `/update_now` job path maps errors the same way.
- [ ] **G6** — A playlist turn that isn't due still starts a render worker.
      Left for now: the Pi logged none in 24 hours.
- [ ] A render worker spends about 1.8 s on the Pi importing
      `refresh_task.worker`, because the package `__init__` also loads the
      task, SSE and event-bus modules. A lean worker entry module would cut
      that (found in #874).
- [ ] `/update_device_cycle` keeps its own 1440-minute limit, and the
      3600-second default cycle is still copied in a few places instead of
      read from the config schema (found in #877).
- [ ] The plugin page's API-key badges (`.api-key-indicator` in
      `plugin.html`) are rendered hidden and nothing shows them. Show them or
      delete them and their CSS.
- [ ] The Debian image digest in `build-wheelhouse.yml` is pinned by hand and
      Dependabot does not update it. Refresh it on each Trixie point release.

## Closed since the last reconcile

- [x] The 2026-11-15 regrade: 49 of its 54 items landed (#834–#878 and this
      reconcile), from the "Fit to container" crash (#835) and the PIN-off
      API-key leak (#839) to one schema for every config rule (#877), one
      `fetchJson` for every page script (#878), a suite-wide network block
      (#875) and random-order test runs (#872). Its open items are listed
      above.
- [x] The previous grade's open items: A1, A5, A6, C6 and I4 landed in #789,
      #796, #802, #804 and #805, and G3 was closed. For C5 / D4, a ceiling
      stops new source-text tests (#872). Of C8–C12, `plugin_form.js` and the
      badge colours were done before the regrade, the page closures and
      leaked globals in #878, and the breakpoints carry over as C12. E3 and
      E5 carry over as E4 and E5. A4 / B5 is listed above.
- [x] Split the largest modules: `refresh_task/task.py` (#705),
      `blueprints/plugin.py` (#706), `utils/http_utils.py` (#707) and
      `blueprints/playlist.py` (#708).
- [x] Re-audit the dashboard and playlists with real data — done while
      dogfooding with populated playlists and history (#695).
- [x] `scripts/render_weather_mock.py` (imported `pytz`) was replaced by
      record/replay in `scripts/dry_run_plugin.py` (#766).
