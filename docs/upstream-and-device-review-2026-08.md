# Upstream + device-firmware review — August 2026

Two investigations in one doc:

- **Part A** — what `fatihak/InkyPi` (parent) has that we don't, since the
  [April 2026 review](./upstream-review-2026-04.md).
- **Part B** — operational patterns from the ESP projects
  (`jtn0123/ESP32-Garage-Fan`, `jtn0123/halloween_esp`) worth having on the Pi.

The review turned up both work that has since been done and work that has not.
Items implemented in PR #632 are ticked below and listed in that PR's
description; everything still unticked — B8–B15 and the Part A watch list — is
live follow-up work. Tick boxes as further items land; strike through anything
we decide against, with the reason.

## Scope and method

| | |
|---|---|
| Our head | `c80da30` on `claude/app-fork-feature-review-09e2f7` (VERSION `1.3.0`) |
| Upstream head | `73c21a1b` — "Bump required versions (#592)", **2026-02-13** |
| Merge base | `8d08acdd` — "Fix wind directions (#462)", 2025-12-12 |
| Upstream commits since merge-base not in our main | 25 (all triaged in the April review) |
| Upstream open PRs | **51** (was 35 in April) |
| ESP repos read | `garage_fan` (firmware + scripts + Makefile), `halloween_esp` (Makefile, tools, ROADMAP) |

Each claim below was checked against our tree, not inferred from PR titles.
Where I could not confirm something without hardware, it says so.

---

## Headline findings

1. **Upstream is effectively dormant.** Three commits in the last six months,
   none since 2026-02-13. Meanwhile open PRs grew 35 → 51. The parent repo is
   now a source of *community patches*, not of releases. Your instinct was
   right; there is no sync to do, only harvesting.

2. **The April review's Port list never started.** All nine issues
   (JTN-767 … JTN-775) are still `Backlog`. That backlog is still the highest
   value/effort ratio available — see A0.

3. **One April verdict was wrong, and it's hiding a live bug.** The review
   recorded the Open-Meteo Kelvin fix as "already in our `weather_api.py`". It
   is not. Details in A1 — this is the single most concrete user-facing defect
   found in this pass.

4. **17 upstream PRs postdate the April review**, including two Waveshare
   panel-driver fixes that apply to our code as-written (A2).

5. **The ESP repos are ahead of InkyPi on exactly the axes you asked about** —
   update confidence, unattended recovery, and crash forensics. The most
   valuable single finding is B1: our systemd watchdog is wired so that it can
   never fire for the failure it exists to catch.

---

# Part A — Upstream delta

## A0. Carried forward from April (still open)

No code written on any of these. Listed newest-verdict-first, not re-triaged —
the April write-ups still stand.

- [x] **JTN-768** — grayscale (`L`-mode) background-color crash · [#568](https://github.com/fatihak/InkyPi/pull/568) · *High*
      — partially mitigated: `image_album.py:314` already coerces to `str` and
      uses `img.mode`. Re-check `clock.py:87`, `image_folder`, `image_upload`.
- [x] **JTN-769** — Open-Meteo day-label / moon-phase off-by-one · [#613](https://github.com/fatihak/InkyPi/pull/613) · *High*
      — **confirmed present**: `weather_data.py` computes
      `target_date = dt.date() + timedelta(days=1)`, so every row's moon phase
      is tomorrow's.
- [ ] **JTN-767** — plugin fallback logic & deprecation cleanup · [#561](https://github.com/fatihak/InkyPi/pull/561) · *Medium*
- [x] **JTN-772** — run-once mode + on-frame error rendering · [#451](https://github.com/fatihak/InkyPi/pull/451) · *Medium*
      — on-frame errors we now have (`utils/fallback_image.render_error_image`);
      run-once mode we don't. Scope the issue down to run-once.
- [ ] **JTN-773** — mutable-default + security hardening batch · [#623](https://github.com/fatihak/InkyPi/pull/623) · *Medium*
- [ ] **JTN-770** — Google Keep plugin · [#663](https://github.com/fatihak/InkyPi/pull/663) · *Medium*
- [ ] **JTN-771** — "Save as new instance" button · [#489](https://github.com/fatihak/InkyPi/pull/489) · *Low*
- [ ] **JTN-774** — configurable `image_url` download timeout · [#600](https://github.com/fatihak/InkyPi/pull/600) · *Low*
- [ ] **JTN-775** — servo control / rotating frame · [#598](https://github.com/fatihak/InkyPi/pull/598) · *Low*

## A1. Correction: the Open-Meteo weather path is broken in three ways

The April review closed [#487](https://github.com/fatihak/InkyPi/pull/487) as
"already in our `weather_api.py`". Re-checking the file, we still carry the
original bug plus two more that upstream fixed in the same neighbourhood.

- [x] **A1a — `temperature_unit=kelvin` is not a valid Open-Meteo parameter.**
      [`weather_api.py:26`](../src/plugins/weather/weather_api.py) sends
      `temperature_unit=kelvin`; Open-Meteo accepts only `celsius` and
      `fahrenheit`. Upstream's fix requests `celsius` and adds `+273.15` at
      parse time. **Effect: choosing "Standard (K)" with the Open-Meteo
      provider does not work.** *High — small fix.*

- [x] **A1b — "Feels like" silently equals the plain temperature.**
      [`weather_data.py:770`](../src/plugins/weather/weather_data.py) reads the
      legacy `current_weather` block, then line 784 asks it for
      `apparent_temperature` — a key that block never contains, so the
      `.get(..., temperature)` fallback always wins. Upstream's URL was
      migrated to `current=temperature,windspeed,winddirection,is_day,`
      `precipitation,weather_code,apparent_temperature`; ours still uses
      `current_weather=true`. *Medium — no error, just quietly wrong.*

- [x] **A1c — hourly forecast has no weather codes, so no per-hour icons.**
      Our `hourly=` list omits `weather_code`, and `parse_open_meteo_hourly`
      reads only time/temp/precip. Upstream [#471](https://github.com/fatihak/InkyPi/pull/471)
      requests hourly `weather_code` and passes sunrise/sunset for day-vs-night
      icon selection. *Low — feature gap, not a bug.*

> A1a–A1c are one coherent piece of work: migrate the Open-Meteo request to the
> modern `current=` form and update the three parsers together. Doing them
> separately means touching the same function three times. **Fold JTN-769 (A0)
> into the same change** — it's the same file and the same parse loop.

- [ ] **A1d — Open-Meteo timestamps are parsed in the wrong timezone.**
      With `timezone=auto` the API returns offset-free *local* timestamps for
      the forecast location, but `weather_data.py` attaches the device timezone
      before converting. Anywhere the device and the forecast location differ,
      current/hourly/sunrise/sunset/humidity/pressure all shift. Predates this
      review — raised by CodeRabbit on
      [#632](https://github.com/jtn0123/InkyPi/pull/632) and deliberately left
      out of it: the fix spans the API and data-point helpers, and it changes
      behaviour for everyone whose device timezone already matches their
      location, so it wants its own change and its own testing. *Medium.*

## A2. New upstream PRs since the April review

Seventeen PRs opened after 2026-04-19. Triaged against our tree.

### Worth acting on

- [x] **[#724](https://github.com/fatihak/InkyPi/pull/724) — `epd3in7`-class panels cannot work in our driver.**
      Those drivers take a required `mode` argument on `init()` and expose
      `display_1Gray`/`display_4Gray` instead of a generic `display()`. Our
      [`waveshare_display.py`](../src/display/waveshare_display.py)
      `initialize_display` calls `self.epd_display_init()` with no arguments
      and then `inspect.getfullargspec(self.epd_display.display)`. **We pin
      `epd3in7.py` in [`install/waveshare-manifest.txt:47`](../install/waveshare-manifest.txt)**,
      so we advertise a panel we cannot drive. *Medium — affects one panel
      family; fix is ~20 lines.*

- [ ] **[#728](https://github.com/fatihak/InkyPi/pull/728) — re-instantiate the EPD object after sleep.**
      `display_image` ends with `self.epd_display.sleep()`, and the next
      refresh calls `self.epd_display_init()` on that same object — whose SPI
      handle `module_exit()` closed. Reporter hits
      `OSError: [Errno 9] Bad file descriptor`.
      **Caveat:** most Waveshare `init()` implementations begin with
      `epdconfig.module_init()`, which re-opens SPI
      ([`epdconfig.py:146`](../src/display/waveshare_epd/epdconfig.py)), so this
      is driver-dependent and I could not reproduce it without hardware. Treat
      as defensive hardening, not a confirmed break. *Low-Medium.*

- [ ] **[#740](https://github.com/fatihak/InkyPi/pull/740) — Inky 2.4.0 for newer hardware.**
      Our range `inky>=2.3,<3` already permits it; the lock pins `inky==2.3.0`.
      A lockfile bump plus a smoke test on real hardware. *Low — trivial.*

### Watch, don't port yet

| PR | What | Why not now |
|---|---|---|
| [#733](https://github.com/fatihak/InkyPi/pull/733) | Widget overlay system | Genuinely novel — overlay clock/weather badges on any plugin's output. Big surface; design it against our render pipeline rather than porting. |
| [#736](https://github.com/fatihak/InkyPi/pull/736) | Automatic photo fitting + settings migration | Overlaps our `image_loader` resize strategies. Compare before porting. |
| [#683](https://github.com/fatihak/InkyPi/pull/683) | Screenshot plugin + `skip_display_condition` | The conditional-skip idea is the valuable half — "don't burn a refresh if nothing changed" is real e-ink savings. |
| [#686](https://github.com/fatihak/InkyPi/pull/686) | Hardware button → next playlist item | Pairs with B14 below and upstream #532. |
| [#735](https://github.com/fatihak/InkyPi/pull/735) | iCloud Shared Albums plugin | New source, no equivalent. Depends on an unofficial endpoint. |
| [#684](https://github.com/fatihak/InkyPi/pull/684) | Weather sunshine + wind-over-time | Fold into the A1 weather work if it's cheap by then. |
| [#670](https://github.com/fatihak/InkyPi/pull/670) | Weather localization | Same reason April deferred #567 — do i18n project-wide (M1), not per-plugin. |
| [#738](https://github.com/fatihak/InkyPi/pull/738) | Playlist plugin refresh intervals | Our scheduler diverged. Reproduce against our tree before porting. |

### Already ahead / not applicable

- [#723](https://github.com/fatihak/InkyPi/pull/723) GPT-Image-2 — we already
  ship `gpt-image-1.5` **and** `gpt-image-2` (`ai_image.py:29-30`).
- [#737](https://github.com/fatihak/InkyPi/pull/737) Unsplash timeout — we have
  it (`unsplash.py:113`, `_request_timeout()`).
- [#677](https://github.com/fatihak/InkyPi/pull/677) Immich assets — same churn
  cluster April already declined.
- [#739](https://github.com/fatihak/InkyPi/pull/739) `-W` driver path,
  [#685](https://github.com/fatihak/InkyPi/pull/685) service typo,
  [#692](https://github.com/fatihak/InkyPi/pull/692) Unsplash illustrations,
  [#693](https://github.com/fatihak/InkyPi/pull/693) Office Hotkeys plugin —
  installer layout mismatch or niche.

---

# Part B — Device-operations patterns from the ESP projects

The Pi isn't an ESP32, but the *operational* problems are identical: an
unattended device on a shelf, updated remotely, that must not need a cable.
Both ESP repos have solved this more completely than InkyPi has.

## B0. What InkyPi already does well

Worth stating, because it changes what's actually missing. We already have,
and in several cases better than the ESP repos:

- systemd `Type=notify` + `WatchdogSec=120` with a dedicated heartbeat thread
  (`refresh_task/task.py:214`) ≈ `esp_task_wdt`
- `StartLimitIntervalSec`/`StartLimitBurst` + `OnFailure=inkypi-failure.service`
  writing `.start-limit-hit` ≈ the ESP reboot budget
- `prev_version` breadcrumb written *before* checkout + `rollback.sh` + a UI
  trigger ≈ A/B slots
- Per-device memory drop-ins and `OOMScoreAdjust=500` — no ESP equivalent
- Per-plugin circuit breaker with pause + `disabled_reason`
  (`refresh_task/health.py`)
- On-frame error rendering (`utils/fallback_image.py:152`)
- `/healthz`, `/readyz`, `/api/diagnostics`, `/metrics` ≈ `/api/state` + `/api/stats`
- GitHub-release update check in the settings UI
- **SHA-256-pinned Waveshare drivers** (`waveshare-manifest.txt`) — stronger
  supply-chain hygiene than either ESP repo

So the gaps below are specific, not "InkyPi has no ops story".

## B1. The watchdog proves the wrong thing ← highest-value item here

`_watchdog_heartbeat_loop` ([`refresh_task/task.py:214`](../src/refresh_task/task.py))
feeds systemd on a timer whose only liveness condition is `is_running=lambda:
self.running` — a plain bool. JTN-596 decoupled it from the refresh cycle so a
long `plugin_cycle_interval_seconds` couldn't stall the heartbeat.

The side effect: if the refresh loop **deadlocks** — blocked on SPI, on a wedged
chromium subprocess, on a plugin's socket — `self.running` stays `True`, the
heartbeat keeps pinging, and `WatchdogSec=120` never fires. The watchdog cannot
catch a hung refresh loop, which is the failure it exists for.

`garage_fan` does the opposite: `esp_task_wdt_reset()` is called from the main
loop (`fan_controller_main.cpp:141`), and the HTTP path explicitly slices work
so it "never blocks more than 50 ms at a time, feeds the watchdog between
slices" (`net/http_tx.h`) — liveness is proven *by the work loop*, not by a
timer that runs beside it.

- [x] **B1 — Gate the heartbeat on refresh-loop progress.** Have the refresh
      loop stamp a monotonic `last_progress_at` at each phase boundary; the
      heartbeat pings only while `now - last_progress_at < grace`, where grace
      generously exceeds the slowest legitimate refresh (AI image generation,
      chromium screenshot). A wedged loop then stops the pings and systemd
      restarts us. *High value, ~40 lines, fully unit-testable.*

## B2–B5. Update confidence

`garage_fan/scripts/deploy.sh` is the reference. Its comments are worth reading
in full — every guard in it exists because of a specific incident.

- [x] **B2 — Verify the new version is actually serving, not just "active".**
      `update.sh:100` waits for `systemctl is-active`. That proves the unit
      started, not that the new code works. `deploy.sh` polls
      `/api/state` until `fw == EXPECTED_FW` **and** `confirmed == true`, and
      distinguishes three outcomes: confirmed / rolled back / genuinely dark.
      Ours should poll `/readyz` plus the version from `/api/diagnostics` until
      it matches the target tag, with the same three-way reporting. *High.*

- [x] **B3 — Automatic rollback after N failed starts.** `rollback.sh` exists
      but is manual (`sudo bash rollback.sh`) or UI-triggered. `boot_health.h`
      auto-reverts unattended in ~10–15 min: an RTC counter tracks consecutive
      boots that never reached the broker, NVS records the last image that ever
      *did*, and a never-confirmed image flips slots at 3 strikes — while a
      once-confirmed image never rolls back, because then the broker is the
      problem, not the firmware. We already have both halves (the
      `.start-limit-hit` sentinel and `prev_version`); nothing joins them.
      *High — this is the difference between "recovers on its own" and "needs a
      keyboard".*

- [ ] **B4 — Pre-flight abort gates in the updater.** `deploy.sh` hard-aborts
      when the built image has an empty WiFi SSID, with the comment: *"A
      warning scrolled past in build output is not a gate; this is."* They
      bricked a device that way on 2026-08-01. Our equivalents: free disk
      before checkout, device config passes schema validation, the display
      driver for the configured panel is present, `VERSION` is readable.
      *Medium.*

- [x] **B5 — Report unconfirmed vs rolled-back vs dark.** Follows from B2/B3;
      surface the three-way outcome in the settings UI and in
      `.last-update-failure` so the UI can say which happened. *Medium.*

## B6–B7. Crash forensics

- [x] **B6 — Breadcrumb the operation in flight.** `system/crashlog.h` keeps a
      16-byte RTC breadcrumb naming the op in flight plus the reset reason, so
      a boot that dies mid-operation can name it on the next boot: *"panic
      during sd_mount"* rather than *"panic"*. The header notes it was "the
      difference between diagnosing the 2026-08-05 crash loop and guessing at
      it." We record update failures, but nothing says *"we died while
      rendering plugin X, phase generate_image"*. Pi equivalent: a small file
      under `/run/inkypi` written before each risky phase, read and rolled into
      the diagnostics payload at startup. *Medium-High — cheap, and it pays for
      itself the first time.*

- [x] **B7 — Quarantine whatever killed the last boot.** Our circuit breaker
      counts *handled* exceptions; a plugin that gets the process OOM-killed
      never trips it and just crash-loops. `crashlog`'s SD sentinel is the
      pattern: a sentinel is held only while the risky operation is in flight,
      and a boot that finds it still set quarantines the card so it "can never
      boot-loop the controller". With B6's breadcrumb in place this is a small
      addition: if the last boot died inside plugin X, start with X paused and
      say so in the UI. *Medium-High.*

## B8–B12. Display and device UX

- [ ] **B8 — Panel-wear odometer.** `system/odometer.h` persists run-seconds
      (today + lifetime) and an energy estimate to NVS every 15 minutes, so a
      reboot loses at most that much accounting and never the lifetime total.
      E-ink panels have a finite refresh budget and we currently count nothing:
      no lifetime refresh count, no per-plugin display hours, no full-vs-partial
      split. This is the most InkyPi-specific idea in the whole ESP set.
      *Medium.*

- [ ] **B9 — Boot self-test.** halloween ROADMAP #26 sweeps R/G/B/W per zone at
      plug-in, so a dead channel is visible before showtime. Ours: after an
      install or update, push a known test pattern and record pass/fail in
      diagnostics — proving the panel and the driver work before a plugin gets
      blamed. *Medium.*

- [ ] **B10 — Asset manifest check at boot.** halloween ROADMAP #29 `stat()`s
      every scene file at boot and lists missing names in `/api/status`. We load
      `static/dist/manifest.json` with graceful degradation
      (`app_setup/asset_helpers.py`) but never *report* what's missing — fonts,
      plugin icons, render templates. Surface it in `/api/diagnostics`. *Medium.*

- [ ] **B11 — QR code on the startup screen.** We render IP text
      (`generate_startup_image`). halloween #24 puts scene, uptime, SD free
      **and a QR to the web remote** on its eInk. A QR turns "read the IP, type
      it on your phone" into one scan. *Low — high polish-per-hour.*

- [ ] **B12 — Blackout / kill switch endpoint.** halloween #25 has
      `/api/blackout`, GET **and** POST so it's bookmarkable, that kills
      everything. Ours: a bookmarkable URL that pauses refreshes and blanks the
      display — useful for guests, photos, or a plugin misbehaving while you're
      out. *Low.*

## B13–B15. Longer shots

- [ ] **B13 — Minimal fallback UI.** halloween's `/remote` (#21) is "embedded in
      flash so it survives a missing SD". Ours: a dependency-free page that
      still works when the asset bundle or manifest is broken — exactly the
      state where you most need the UI. *Low-Medium.*
- [ ] **B14 — Physical button.** Converges with upstream
      [#532](https://github.com/fatihak/InkyPi/pull/532) /
      [#686](https://github.com/fatihak/InkyPi/pull/686) and halloween's
      arcade-button panel (RGB-lit so the button's meaning is software). Next
      plugin / force refresh / blackout. *Low — hardware-gated.*
- [ ] **B15 — Multi-device registry.** `devices.toml` + `tools/device.py` +
      `tools/hosts.py` resolve a target as: explicit arg → env var → first
      entry. Only worth it if you run more than one InkyPi. *Low.*

---

## Suggested order

Grouped so each block is one coherent change rather than scattered edits.

**First — correctness users can see**
1. A1a+A1b+A1c + JTN-769 — one Open-Meteo pass (**A1a is a live "Standard units
   don't work" bug**)
2. A2/#724 — `epd3in7` panels, since we already ship the pinned driver
3. JTN-768 — grayscale background crash

**Second — the unattended-device story** (the ESP core, in dependency order)
4. B1 — watchdog gating *(do first; it's independent and self-contained)*
5. B2 — post-update version+health verify
6. B3 — automatic rollback on repeated failed starts
7. B6 → B7 — crash breadcrumb, then quarantine-on-crash
8. B4, B5 — pre-flight gates and three-way update reporting

**Third — polish**
9. B8 panel odometer, B10 asset manifest check, B9 boot self-test
10. B11 QR, B12 blackout, A2/#740 Inky bump
11. Re-triage the A0 backlog and the A2 "watch" list

**Deliberately not scheduled:** B13–B15, the A2 watch list, and everything the
April review put under "Maybe later".

---

# Part C — Upstream PRs worth taking inspiration from

Separate from "should we port this". These are open PRs whose *ideas* are good
enough to build our own version of, even where the code doesn't fit our tree.
Ranked by how much the idea is worth, not by diff size.

### C1. `skip_display_condition` — [#683](https://github.com/fatihak/InkyPi/pull/683) · steal the idea

The best single idea in the queue, and it's about 15 lines of core surface. A
new optional `BasePlugin` hook:

```python
def skip_display_condition(self, settings, device_config, current_dt):
    return None            # proceed with normal display
    # or: return "No games to display"   → skip this cycle, reason shown in preview
```

It gives a plugin a way to say *"I have nothing worth showing right now"*
instead of rendering an empty frame. The author's example is a sports
scoreboard in the offseason; ours would be a calendar with no events, an RSS
feed with nothing new, a countdown that already fired.

Two things make it better than it first looks. The reason string is rendered
into the playlist preview, so a skipped plugin is *visible* rather than
mysterious. And the docstring tells plugin authors to cache anything the hook
fetched into a private `settings` key so `generate_image` doesn't repeat the
request — the obvious performance trap, closed in the docs at the point of use.

This also pairs directly with **B8** (panel-wear odometer): the cheapest e-ink
refresh is the one you don't do.

### C2. Widget overlay system — [#733](https://github.com/fatihak/InkyPi/pull/733) · steal the concept

+1788/-4 across 28 files, and the most architecturally ambitious thing anyone
has proposed upstream. A second render layer: transparent RGBA overlays
composited on top of whatever plugin is active, positioned and reordered
independently through the UI. Ships date / IP / static-message samples, and an
`inkypi-widget` CLI mirroring the `inkypi-plugin` one we already have.

The detail worth stealing outright: **automatic contrast color selection** —
a widget can opt into having its text picked black-or-white based on what's
behind it. That's the hard part of overlays on arbitrary plugin output.

Too big to port; the right move is our own design against our render pipeline
if we want it. Worth reading before designing anything overlay-shaped.

### C3. Auto photo fitting — [#736](https://github.com/fatihak/InkyPi/pull/736) · steal the migration discipline

Adds an `Auto` fit mode that picks Cover when image and display orientations
match and Contain when they differ. Nice feature — but the reason it's on this
list is *how it's built*: it centralizes Cover/Contain/Auto inside
`AdaptiveImageLoader` (the class upstream took from us in #427, so the shape
transfers directly), preserves the existing `resize=True/False` interfaces so
no plugin changes, and migrates legacy `padImage` → `fitMode` centrally with
documented old→new mappings.

That's the settings-migration pattern we'll want the next time we rename a
plugin setting. 57 tests, and the compatibility section spells out exactly what
stays the default.

### C4. Control-only plugins may return `None` — buried in [#598](https://github.com/fatihak/InkyPi/pull/598)

The servo PR itself is niche (and April already flagged it as unsafe in its
current form — pulse on boot, no mock mode). But it contains one small core
change with much wider reach: **a plugin may return `None` from
`generate_image` to skip rendering entirely**, which turns "plugin" into a
mechanism for actuators and side effects, not just images.

Combined with C1, that's a clean split: `skip_display_condition` for *"nothing
to show this cycle"*, `None` for *"I was never about showing anything"*.

### C5. Live preview endpoint — [#660](https://github.com/fatihak/InkyPi/pull/660)

April deferred this (M6) in favour of building on our own
`live-preview-lightbox` scaffolding — still the right call. But the endpoint
design is worth copying: `/preview` renders in-memory and returns base64, so
there are no temp files and no display write; the client debounces on form
change; required-field validation happens client-side with friendly hints
(*"(select a date first)"*) rather than a server round-trip; and on machines
without Chromium the HTML plugins say *"(needs Chromium — works on Pi)"*
instead of showing a broken image.

That last one is the kind of graceful degradation that's easy to skip and
annoying to live without in dev.

### C6. Hardware button, done the small way — [#686](https://github.com/fatihak/InkyPi/pull/686)

Two competing button PRs upstream. [#532](https://github.com/fatihak/InkyPi/pull/532)
is +2074 across 17 files with a full button-action config UI; #686 is +322 and
does one thing — press A, advance the playlist.

#686 is the better reference, and specifically for its design note: it *routes
manual cycling through the existing refresh thread* rather than acting on the
button handler's thread, "to avoid display/config write races". Anything we
build that can trigger a refresh from outside the loop — button, webhook,
blackout endpoint (**B12**) — needs exactly that discipline.

### C7. Screenshot plugin practicalities — also [#683](https://github.com/fatihak/InkyPi/pull/683)

Two small, real fixes bundled with C1: a configurable **render wait** so
JavaScript-heavy pages finish painting before capture, and **skip if blank**,
which detects a single-colour screenshot and declines to display it. Both are
the sort of thing you only discover by running the plugin against real sites.

### C8. Run-once mode — [#451](https://github.com/fatihak/InkyPi/pull/451)

+88/-22 total, and half of it (on-frame error rendering) we already have. The
remaining half is a `--run-once` flag: render the next plugin, push it, exit.
That makes cron- or timer-driven deployments possible without running the
scheduler at all — a genuinely different operating mode for very low duty-cycle
setups. Already tracked as JTN-772; scope that issue down to just run-once.

---

## Maintenance note

The April review suggested re-scanning upstream on a 6-month cadence (next:
2026-10). Given three commits in six months, that's still right — but the *open
PR* queue is now where the value is, and it moves faster than main. Worth
scanning PRs quarterly even while main stays frozen.
