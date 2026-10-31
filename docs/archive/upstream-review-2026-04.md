# Upstream review: `fatihak/InkyPi` — April 2026

Tracking issue: [JTN-718](https://linear.app/jtn0123/issue/JTN-718).

## Scope and method

- **Our head**: `c199e6a` on `origin/main` (tag `0.61.7`).
- **Upstream head**: `73c21a1` on `fatihak/main` (fetched 2026-04-19).
- **Merge base**: `8d08acd` — "Fix wind directions (#462)", 2025-12-12.
- **Upstream commits since merge-base not in our main**: **25**.
- **Upstream open PRs scanned**: **35** (everything currently `open` on `fatihak/InkyPi` at review time).
- **Upstream merged PRs scanned (since 2025-04-19)**: **50+** (`gh pr list --state merged --search "merged:>=2025-04-19"`).

Deep-dives (actually opened the diff against our tree, not just title-skim):
PRs #561, #568, #427, #613, #623, #615, #600, #598, #584, #581, #567, #548, #544, #545, #537, #536, #530, #494, #487, #482, #476, #469, #460, #451, #459, #489, #434, #414, #402, #365, #388, #385, #356, #663, #662, #660, #659, #651, #640, #641, #631, #629, #625, #614, #613, #608, #593, #588, #572, #532, #531, #454.

Title-skim only (no diff fetched): the pure-docs PRs, translation-only PRs for languages we don't yet support, the dev-branding PRs, and the "bump dependency version" commits we already maintain separately via our own lockfile process.

**Cutoff criteria for skipping an item:**

1. We already have a strictly better equivalent (e.g. our full API keys UI vs. upstream's template block; our `diagnostics` + `metrics` blueprints vs. upstream's System Info dashboard).
2. The change is pure internal refactor, branding, or docs cleanup that doesn't land user-visible value in our fork.
3. The change touches a subsystem where we have diverged so fundamentally (plugin blueprints, install/update flow, CSS build, testing infra) that the upstream patch would cost more than rebuilding the same idea from scratch against our architecture.
4. The PR is stale / conflicting / hasn't been responded to by the author for more than 3 months.

The verdict on each candidate is **Port / Maybe later / Rejected** below. Linear issues are filed only for "Port" items — that's where the "follow-up" work lives.

---

## Summary

| Bucket        | Count | Notes                                                                |
| ------------- | ----- | -------------------------------------------------------------------- |
| Port          | 9     | Filed as follow-up Linear issues — see links below.                  |
| Maybe later   | 8     | Real value but blocked by architectural cost or niche demand.        |
| Rejected      | ~20   | Already ported, already have a better version, or pure churn.        |

---

## Port (follow-up Linear issues filed)

### 1. Plugin fallback logic & deprecation cleanup — **[JTN-767](https://linear.app/jtn0123/issue/JTN-767)**

Upstream: [commit `ce6379c`](https://github.com/fatihak/InkyPi/commit/ce6379c) / [PR #561](https://github.com/fatihak/InkyPi/pull/561). Priority: Medium.
A batch of small correctness fixes: `logger.warn` → `logger.warning`, tighter try/except scopes, crash-on-empty-list in `image_folder`, null-deref defaults in `weather.py`. Medium effort because our files have drifted.

### 2. Grayscale background-color crash fix — **[JTN-768](https://linear.app/jtn0123/issue/JTN-768)**

Upstream: [commit `fb71cc3`](https://github.com/fatihak/InkyPi/commit/fb71cc3) / [PR #568](https://github.com/fatihak/InkyPi/pull/568). Priority: High.
Fixes a real crash when a plugin (clock, image album/folder/upload) produces an `L`-mode (grayscale) image and then pastes an RGB tuple as background. Hits users on bi-color / grayscale Waveshare panels — which our fork *does* support. Small effort, high user impact.

### 3. Open-Meteo forecast day-label off-by-one — **[JTN-769](https://linear.app/jtn0123/issue/JTN-769)**

Upstream: [PR #613](https://github.com/fatihak/InkyPi/pull/613). Priority: High.
Silent correctness bug: the "today" column can be labelled with tomorrow's weekday name depending on user's timezone. Tiny fix, real visible bug for half the world.

### 4. Google Keep plugin — **[JTN-770](https://linear.app/jtn0123/issue/JTN-770)**

Upstream: [PR #663](https://github.com/fatihak/InkyPi/pull/663). Priority: Medium.
New plugin that pulls a single Google Keep note (list or text) with dynamic font sizing. Fills a real gap in our plugin catalog — personal tasks/notes from a source users actually sync to. Medium effort because we need to integrate with our own API key UI idioms.

### 5. "Save as new instance" button — **[JTN-771](https://linear.app/jtn0123/issue/JTN-771)**

Upstream: [commit `49e444c`](https://github.com/fatihak/InkyPi/commit/49e444c) / [PR #489](https://github.com/fatihak/InkyPi/pull/489). Priority: Low.
Tiny UX win: lets users duplicate-and-tweak a saved plugin instance instead of re-entering all settings. Upstream adds a single template line; our blueprint already supports the save path.

### 6. Run-once mode + on-frame error rendering — **[JTN-772](https://linear.app/jtn0123/issue/JTN-772)**

Upstream: [PR #451](https://github.com/fatihak/InkyPi/pull/451). Priority: Medium.
Two distinct features bundled. Run-once suits cron-driven deployments. On-frame errors replace "stale pixels on silent failure" with a visible error card — a real operator UX win. Medium effort; our `refresh_task` is now a package so direct cherry-pick won't apply.

### 7. Mutable-default + security hardening batch (triage first) — **[JTN-773](https://linear.app/jtn0123/issue/JTN-773)**

Upstream: [PR #623](https://github.com/fatihak/InkyPi/pull/623). Priority: Medium.
18-file hardening batch. Part of it we already have via our own stricter linting; part may not. Issue asks the assignee to *first* diff and produce a "hunks still needed" shortlist before coding.

### 8. `image_url` plugin configurable download timeout — **[JTN-774](https://linear.app/jtn0123/issue/JTN-774)**

Upstream: [PR #600](https://github.com/fatihak/InkyPi/pull/600). Priority: Low.
Lets users opt into a longer HTTP timeout when fetching slow image sources. Small server-side validation wrap. Addresses a real complaint class.

### 9. Servo control plugin (rotating frame) — **[JTN-775](https://linear.app/jtn0123/issue/JTN-775)**

Upstream: [PR #598](https://github.com/fatihak/InkyPi/pull/598). Priority: Low.
Hardware feature for users building a physically rotating frame. Niche but novel, no existing alternative. Large effort because of hardware testing, safety interlocks, and docs. Kept as Port because upstream won't land this and it's additive (won't regress anything).

---

## Maybe later

These have real merit but were held back by (1) architectural cost in our fork, (2) niche demand, (3) unresolved upstream design questions. No Linear issue filed — revisit in a future review.

| # | Item | Why deferred |
|---|------|--------------|
| M1 | [PR #567](https://github.com/fatihak/InkyPi/pull/567) Weather plugin translations | Adds a `translations.py` dict for the weather plugin only. Our project has a `translations/` tree with an `extracted.json` pipeline — we should do i18n *project-wide* (weather, calendar labels, year_progress), not as a one-off. Worth a dedicated design issue. |
| M2 | [PR #584](https://github.com/fatihak/InkyPi/pull/584) Dynamic font loading | Adds a 268-line `docs/fonts.md` and ~470 LOC to `utils/app_utils.py`. Genuinely useful but our `app_utils` has diverged (HEIF/vendor paths, device-ram adaptive loading). Re-architect later; single monolithic patch is wrong shape for our tree. |
| M3 | [PR #651](https://github.com/fatihak/InkyPi/pull/651) Calendar: adjustable number of days | Small, useful. Deferred only because PR still under discussion upstream (days-per-week vs. days-total semantics). Port once their API settles. |
| M4 | [PR #640](https://github.com/fatihak/InkyPi/pull/640) Weather: manual lat/lon input | We already accept lat/lon via our own widget (see `src/templates/widgets/weather_map.html` + validation in `weather.py`). The upstream UX is slightly different (no map, just fields); revisit if users complain about the map being unreliable on low-RAM browsers. |
| M5 | [PR #659](https://github.com/fatihak/InkyPi/pull/659) Third-party plugin CLI `update` command | We already have the `inkypi plugin install/uninstall/list` CLI (ported earlier from upstream #548). Adding `update` is cheap — port once upstream merges so we inherit the exact flag surface. |
| M6 | [PR #660](https://github.com/fatihak/InkyPi/pull/660) Live preview widget on plugin settings | Real UX improvement. Deferred because we already have `live-preview-lightbox` scaffolding in `progressive_disclosure.js`; adding full live preview is better done as part of a dedicated JTN issue aligned with our CSS tokens and the existing preview modal. |
| M7 | [PR #625](https://github.com/fatihak/InkyPi/pull/625) Immich OOM + video handling | Our `image_loader.py` already has memory-adaptive loading (which upstream partially mirrored in #427). Check if we still crash on oversized Immich photos and on video-asset responses, and port the targeted fixes *only* once we can reproduce. Don't drop in upstream wholesale. |
| M8 | [PR #593](https://github.com/fatihak/InkyPi/pull/593) Home Assistant Addon ingress compatibility | Legitimate integration path; we've never validated HA Addon compatibility. Worth a spike — file when someone asks for it. |

---

## Rejected (with reason)

Grouped by reason. One-line each.

### Already have it / already ported

- **Commits `f0bf9ea`, `73c21a1` (PR #592)** Bump requirement versions — we maintain our own `install/requirements.in` lock via a separate pipeline; upstream's numbers are frequently out of date for us.
- **`e5f8a44` (PR #537)** AVIF support — already present (`src/utils/app_utils.py`, `src/plugins/image_folder/image_folder.py`).
- **`7913283` (PR #536)** Static path traversal check — we have our own hardened static serving with CSP and path normalization.
- **`116a00b` (PR #545)** Request timeouts — we already thread explicit timeouts through `http_client.py`; plugin calls use `_request_timeout()` helpers.
- **`68c3be1` (PR #487)** Open-Meteo Kelvin fix — already in our `weather_api.py`.
- **`b823100` (PR #482)** Visibility miles/km — already in `src/plugins/weather/weather_data.py:452`.
- **`bd9e3e4`** webcal URL handling — already in `src/plugins/calendar/calendar.py:365`.
- **`73b1dc2` (PR #471)** Hourly weather — already in `weather.py` (`parse_hourly` + `parse_open_meteo_hourly`).
- **`954206d` (PR #530)** Inky driver saturation — already in `src/display/inky_display.py:65`.
- **`2d50ccd` (PR #494)** Bi-color display support — already in `waveshare_display.py` (`split_image_for_bi_color_epd`).
- **`dcd6d30` / `5955853` (PRs #469, #476)** Immich shared albums + EXIF orientation — already in our Immich path.
- **`9a42af5` (PR #548)** Third-party plugins install/uninstall CLI — already ported (`install/cli/inkypi-plugin`, `inkypi plugin install|uninstall|list`).
- **`12083ee` (PR #544)** Plugin grid + API keys UI — we have a richer version of both (see `src/blueprints/apikeys.py`, our plugin grid CSS).
- **`647ce2f` (PR #427)** Image memory optimization — we built our own `src/utils/image_loader.py` with adaptive strategies; upstream approach is simpler but less aware of Pi-Zero memory pressure.
- **`f355735` (PR #460)** Update plugin refresh time — we already have `refresh_settings_manager` in `src/static/scripts/` and our own refresh-time UI (see `src/blueprints/plugin.py` + `_find_latest_plugin_refresh_time`).
- **`af6fa3c` (PR #499)** `libheif-dev` for 32-bit RPi OS — already in our `install/debian-requirements.txt`.
- **[PR #459](https://github.com/fatihak/InkyPi/pull/459)** Device debug info box — we have a dedicated `/api/diagnostics` endpoint (`src/blueprints/diagnostics.py`) that covers uptime, memory, disk, refresh-task state, plugin health, log tail, and version info. Port of the upstream box would just be UI polish; revisit once we have a settings-page redesign.
- **[PR #662](https://github.com/fatihak/InkyPi/pull/662)** System Info dashboard — 2,100 LOC PR largely duplicating what our diagnostics blueprint already exposes. Our approach is JSON-first (consumable by the UI, CLI, and healthchecks); upstream is HTML-first.
- **[PR #402](https://github.com/fatihak/InkyPi/pull/402)** `/current_image` polling — we already have `GET /api/current_image` in `src/blueprints/main.py:176`.
- **[PR #365](https://github.com/fatihak/InkyPi/pull/365)** Local moon-phase calculation — already in our weather plugin (`get_moon_phase_icon_path`).
- **[PR #388](https://github.com/fatihak/InkyPi/pull/388)** Image folder subdirectory listing — already done (`os.walk(folder_path, followlinks=False)` in `image_folder.py:41`).
- **[PR #428](https://github.com/fatihak/InkyPi/pull/428)** OOM-killer service restart — already handled via our `OnFailure=inkypi-failure.service` + `Restart=on-failure` config (see `install/inkypi.service`).
- **[PR #356](https://github.com/fatihak/InkyPi/pull/356)** Playlists spanning midnight — we already handle HH:MM → minutes with `24:00` sentinel (`src/model.py:290`, wrap logic at 494).
- **[PR #407](https://github.com/fatihak/InkyPi/pull/407)** Zoom preview image onclick — we already have a `imagePreviewModal` + `thumbnail-preview-modal` + `live-preview-lightbox`.
- **[PR #405](https://github.com/fatihak/InkyPi/pull/405)** Dark mode — we have a full theme pipeline (`src/static/scripts/theme.js`, CSS tokens in `_tokens.css`).
- **[PR #410](https://github.com/fatihak/InkyPi/pull/410)** HEIF/HEIC support — already supported via `pi_heif` in `image_loader.py`.
- **[PR #615](https://github.com/fatihak/InkyPi/pull/615)** Installer hang hardening — our installer has diverged so far (idempotent, wheelhouse-based, `preflash_smoke.py`, etc.) that cherry-picking doesn't make sense. Our own installer hardening backlog covers the same ground.
- **[PR #588](https://github.com/fatihak/InkyPi/pull/588)** piwheels install — we build our own wheelhouse (`build-wheelhouse.yml`) which supersedes this.

### Pure docs / branding / churn

- **`c546ac0` (PR #541)** Fix typos — cherry-pick any typos that land in *our* copies during other PRs; not worth a standalone sync.
- **`90ed2e6`** Fix CLI install + display plugin name in playlist preview — first half is for upstream's CLI layout which doesn't match ours; second half (playlist name display) we already do.
- **`c333584` (PR #542)** `config.txt` path update — upstream's installer layout; we install differently.
- **[PR #572](https://github.com/fatihak/InkyPi/pull/572)** macOS Chrome default path — our `devbox.json` + `scripts/venv.sh` handle this differently.
- **[PR #591](https://github.com/fatihak/InkyPi/pull/591)** Disable browser features + temp cleanup — our `image_utils.py` already locks down browser flags; revisit only if we find a new leak.
- **[PR #608](https://github.com/fatihak/InkyPi/pull/608)** "Minor issues & lost prints" — grab-bag; low value, high merge cost.
- **[PR #214](https://github.com/fatihak/InkyPi/pull/214)** Dev container — we have `devbox.json`, Docker Compose, and full dev docs already.
- **[PR #414](https://github.com/fatihak/InkyPi/pull/414)** Jetify devbox auto-setup — we already have a devbox-based dev setup.
- **[PR #360](https://github.com/fatihak/InkyPi/pull/360)** Add `.idea` to `.gitignore` — already done.
- **[PR #374](https://github.com/fatihak/InkyPi/pull/374)** Add `.editorconfig` — already done.
- **[PR #373](https://github.com/fatihak/InkyPi/pull/373)** Bundle JS/CSS instead of CDN — already done (we ship vendored assets).
- **[PR #371](https://github.com/fatihak/InkyPi/pull/371)** Improve `development.md` — our docs diverged.
- **[PR #379](https://github.com/fatihak/InkyPi/pull/379)** System packages for Trixie — our `debian-requirements.txt` is more comprehensive.
- **[PR #420](https://github.com/fatihak/InkyPi/pull/420) / #417 / #398 / #377** Various typo fixes, Jost.ttf replacement, transparent icon backgrounds, GitHub Sponsors plugin branding — trivially small; skip or port opportunistically in plugin-specific work.
- **[PR #454](https://github.com/fatihak/InkyPi/pull/454)** Custom hostname during install — marked CONFLICTING upstream; our install flow sets hostname differently via our `install.sh`.
- **[PR #434](https://github.com/fatihak/InkyPi/pull/434)** Tab title update progress messages — marked CONFLICTING upstream; our playlist/plugin pages diverged.
- **[PR #385](https://github.com/fatihak/InkyPi/pull/385)** Weather icons day/night — already ported in an earlier sync.
- **[PR #455](https://github.com/fatihak/InkyPi/pull/455)** Contributions grid month labels — already addressed in our `github_contributions` plugin.
- **[PR #457](https://github.com/fatihak/InkyPi/pull/457)** Orphan image cleanup + thumbnails — we have `src/utils/history_cleanup.py` and plugin thumbnails.
- **[PR #399](https://github.com/fatihak/InkyPi/pull/399)** Newspaper/wpotd orientation-aware — we've already done this per-plugin.

### Architectural mismatch / niche / low quality

- **[PR #581](https://github.com/fatihak/InkyPi/pull/581)** "Add Plugin Manager" (620 + 697 LOC) — overlaps with our plugin grid + API keys UI; upstream approach adds a *second* page for plugin discovery. Net negative for us.
- **[PR #532](https://github.com/fatihak/InkyPi/pull/532)** Hardware button support (2,000 LOC) — legitimate feature but touches `settings.py` + `inkypi.py` + CSS + UI very invasively and upstream has been sitting unreviewed. Better shape: file as a from-scratch design issue against our architecture when a user actually asks.
- **[PR #531](https://github.com/fatihak/InkyPi/pull/531)** APOD image-fit options — our `apod` plugin uses the shared image-loader's resize; duplicating the upstream settings UI is not worth the drift.
- **[PR #629](https://github.com/fatihak/InkyPi/pull/629)** "Fix scheduled refresh not updating correctly" — our scheduling is handled by the `refresh_task` package which has been audited separately (JTN-671 neighbourhood). If the upstream bug class exists for us, catch via a new test rather than porting their patch.
- **[PR #631](https://github.com/fatihak/InkyPi/pull/631)** Playlist inline editing — our playlist UI uses modal-based editing; different UX philosophy.
- **[PR #641](https://github.com/fatihak/InkyPi/pull/641)** Year_progress localization — one plugin only; better to ship i18n as a platform (see M1 above).
- **[PR #677](https://github.com/fatihak/InkyPi/pull/677) / #614 / #625** Immich API tweaks — three overlapping PRs touching the same file. Port a consolidated version only if we see concrete Immich failures in our fork; don't inherit upstream's churn.
- **[PR #598](https://github.com/fatihak/InkyPi/pull/598) Servo Control** — listed under Port above as opt-in; rejected in its current form (unsafe pulse on boot, no mock-mode) and ported only with safety work.

---

## Maintenance note

Upstream merge pace has slowed: the last upstream-main commit is from 2026-02-13, and most open PRs have sat without maintainer response since early March. We should not assume upstream will land our fixes; treat this review as a "here is what is worth extracting" scan, not as a sync.

Next scheduled review: file a recurring "re-scan upstream" ticket for 2026-10 (6-month cadence is enough given the pace).
