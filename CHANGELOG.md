# CHANGELOG


## v0.56.0 (2026-04-15)

### Features

- **observability**: In-app status badge wired to /api/diagnostics (JTN-709)
  ([#494](https://github.com/jtn0123/InkyPi/pull/494),
  [`49f0b09`](https://github.com/jtn0123/InkyPi/commit/49f0b09435dd775e577c0ca13fb0805ae818bd9c))

* feat(observability): in-app status badge wired to /api/diagnostics (JTN-709)

Surfaces a tiny fixed-position badge on every page that polls /api/diagnostics every 30s (plus on
  page load and on visibilitychange) and flips to warning or error when something is wrong. Hidden
  by default when healthy — no UI noise. Click opens a popover listing active issues with links to
  /download-logs, the pretty diagnostics payload, and the settings updates page (when
  last_update_failure is present).

Server-side: /api/diagnostics now returns a `recent_client_log_errors` summary ({count_5m,
  warn_count_5m, last_error_ts, window_seconds}) backed by a bounded 100-entry in-memory ring buffer
  populated from /api/client-log POSTs. In-memory only; intentionally no disk persistence.

Graceful degradation: 401/403 from /api/diagnostics hides the badge and stops polling (viewer isn't
  on the local network). Tests can opt out with `<meta name="status-badge-disabled" content="1">`.

JTN-707 supplied the diagnostics contract — this consumes it without breaking any existing fields.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* fix(lint): ruff B007 + black formatting for JTN-709 tests

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.55.1 (2026-04-15)

### Bug Fixes

- **install**: Pin Waveshare driver + safe device.json mutation (JTN-701)
  ([#492](https://github.com/jtn0123/InkyPi/pull/492),
  [`b3c9214`](https://github.com/jtn0123/InkyPi/commit/b3c9214016ba2a1975008fb693c88d76b096b9a0))

Two hardening changes in install/install.sh that made the installer fragile:

1. fetch_waveshare_driver was pulling drivers from the `master` branch of waveshareteam/e-Paper. A
  silent upstream change could brick a previously-working device on the next install. Introduce
  install/waveshare-manifest.txt pinning every supported driver to a specific upstream commit sha +
  expected sha256, and rewrite the fetch helper to verify the hash after download (fails fast on
  mismatch).

2. update_config mutated device.json with `sed` regexes — fragile on malformed input or unusual
  whitespace and prone to silent corruption when the ending `}` is on its own line. Replace with a
  small Python helper (install/_device_json.py) that uses json.load/json.dump, preserves unrelated
  keys + their ordering, and writes atomically via tempfile + fsync + os.replace.

Tests added to tests/unit/test_install_scripts.py: - waveshare manifest is sha-pinned (40-char git
  sha + 64-char sha256 per row) - install.sh references the manifest + verifies sha256 + no longer
  hard-codes /master/ - update_config contains no sed + delegates to _device_json.py - helper
  preserves unrelated keys / ordering when setting display_type - helper keeps existing display_type
  position when updating - helper rejects malformed JSON, non-object root, missing file, empty
  display_type — and leaves a malformed file untouched (atomicity) - helper source uses tempfile +
  os.replace + os.fsync

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Testing

- **observability**: Unit-test log rotation (JTN-712)
  ([#491](https://github.com/jtn0123/InkyPi/pull/491),
  [`3ea723b`](https://github.com/jtn0123/InkyPi/commit/3ea723b7e8d028a394e8c4e7890b747c91d90df8))

Rotation is load-bearing on the Pi Zero 2 W's 16GB SD, but no test exercised RotatingFileHandler
  wiring or behavior. Runaway logging could silently fill the disk (see JTN-671 restart-loop
  disk-wear context) and CI would not catch it.

Adds tests/unit/test_log_rotation.py with 12 tests covering: * logging.conf declares a
  [rotating_file] section with class RotatingFileHandler and non-zero maxBytes/backupCount (proves
  rotation is configured, not defaulted). * read_rotation_config() rejects maxBytes=0,
  backupCount=0, and a missing section — breaking the conf fails the test. * Actual rotation
  behavior: emitting > maxBytes creates a .1 backup, primary file stays <= maxBytes, total files
  capped at backupCount + 1. * Stress test: ~10x maxBytes forces many rotations, oldest files are
  dropped, backupCount limit is respected. * Ordering: newest content in primary, oldest in backup.
  * setup_logging() attaches a RotatingFileHandler when INKYPI_LOG_FILE is set, and does not when
  unset.

Minimal product-code additions to make rotation testable: * src/config/logging.conf: new
  [rotating_file] section with maxBytes=1MB, backupCount=5 (not wired into fileConfig so default
  behavior is unchanged — console-only). * src/app_setup/logging_setup.py: read_rotation_config()
  and attach_rotating_file_handler() helpers; setup_logging() attaches the handler only when
  INKYPI_LOG_FILE env var is set. Misconfigured rotation raises loudly rather than silently falling
  back to an unbounded file.


## v0.55.0 (2026-04-15)

### Features

- **dev**: Watch-mode CSS + asset rebuild script (JTN-713)
  ([#490](https://github.com/jtn0123/InkyPi/pull/490),
  [`1fb126e`](https://github.com/jtn0123/InkyPi/commit/1fb126e971f6f082949c9fb9e15d723da8474ca7))

Add scripts/dev_watch.sh + scripts/_dev_watch_dispatch.py, a thin watchmedo-driven wrapper that
  auto-runs build_css.py / build_assets.py when partials change. Debounces IDE save bursts (200 ms
  window), logs one line per rebuild in the documented format, and exits cleanly on Ctrl+C. watchdog
  is declared in requirements-dev.in as an optional dev convenience. Documented alongside
  ./scripts/dev.sh in docs/development.md.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.54.0 (2026-04-15)

### Features

- **observability**: Batch + raise cap on /api/client-log (JTN-711)
  ([#488](https://github.com/jtn0123/InkyPi/pull/488),
  [`e38e438`](https://github.com/jtn0123/InkyPi/commit/e38e438f02a723a87ee9988995dcec7bc26bdffc))

* feat(observability): batch + raise cap on /api/client-log (JTN-711)

- Raise server rate-limit bucket to capacity=60, refill=10/s so bursts of console errors from a
  broken page aren't silently dropped. - Accept either a single-object payload (legacy) or an array
  of up to 50 entries in a single POST. Each POST consumes exactly one rate-limit token regardless
  of entry count. - All-or-nothing validation on batches: any invalid entry returns 400 with
  per-entry errors in `details.entry_errors` so the client can self-correct. - Raise body cap to 256
  KB to fit worst-case batches (50 x ~4 KB). - client_log_reporter.js coalesces emitted reports
  within a 500ms window into a single batched POST; chunks across multiple POSTs if > 50. - Raise
  client-side self-disable threshold from 5x429 to 10x429 now that server capacity is higher. -
  Flush pending queue via sendBeacon on pagehide/beforeunload so reports aren't lost when navigating
  mid-window. - Add tests/unit/test_client_log_batch.py covering batch accept/reject, per-entry
  validation, token accounting, newline stripping, field capping, and the 30-errors-in-a-burst
  acceptance case.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* refactor(client_log): share size+rate-limit helper with client_error

Extract the body-size + rate-limit guard into ``enforce_size_and_rate`` in
  ``utils/client_endpoint``. The old inline block in ``receive_client_log`` was the same 16 lines as
  the one in ``client_error`` — SonarCloud flagged the duplication on the JTN-711 PR. The helper
  returns the raw body so callers can still do their own JSON parsing (single-dict vs batch array).

* fix(security): close CodeQL reflected-XSS alerts on client-log errors

CodeQL flagged both error paths in ``receive_client_log`` as flowing user-controlled data into the
  response body. The messages were already server-controlled literals, but the taint tracker
  couldn't prove it across the helper boundary / error-list indirection. Rebuild both responses from
  server-controlled strings:

- Size/rate-limit failure: use ``reissue_json_error`` to preserve the HTTP status (413/429) while
  swapping the body for a fixed string. - Per-entry validation failure: use a single fixed top-level
  message; the actual per-entry error list stays under ``details.entry_errors`` for debuggability.

Follows the pattern from feedback_codeql_url_redirection — rebuild from validated parts rather than
  reusing tainted values, even when the reuse is provably safe by inspection.

* test(client_log): adapt XSS regression to new error envelope

The top-level ``error`` field is now a fixed server-controlled string ("One or more batch entries
  failed validation") per JTN-711; the per-entry "Invalid level: ..." message moved under
  ``details.entry_errors``. Update the reflective-xss regression to check both locations — the point
  of the assertion (the raw attacker payload never appears anywhere in the body) is unchanged.

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.53.0 (2026-04-15)

### Features

- **update**: Surface update failures in web UI (JTN-710)
  ([#487](https://github.com/jtn0123/InkyPi/pull/487),
  [`ec96220`](https://github.com/jtn0123/InkyPi/commit/ec96220c2a560dad80b1735e06d76f135fde8777))

* feat(update): surface update failures in web UI (JTN-710)

Wire the ``.last-update-failure`` JSON record (JTN-704) written by ``install/update.sh``'s EXIT trap
  through the ``/settings/update_status`` endpoint so the Settings -> Updates page can show *why*
  the last update failed without the user SSHing in to read the system journal.

- Add ``_update_status.py`` helper that reads ``/var/lib/inkypi/.last-update-failure`` defensively
  (missing -> ``None``, malformed -> ``{parse_error: true}``, caps oversized files to 64 KiB). -
  Extend ``GET /settings/update_status`` with a ``last_failure`` field. - Tighten ``POST
  /settings/update`` validation: an explicit null, empty, whitespace-only, or non-string
  ``target_version`` now returns 400 with the standard validation envelope (``code:
  validation_error``, ``details.field: target_version``). Previously the request silently fell
  through to the "latest semver tag" path in ``do_update.sh``, producing "No semver tags found" only
  visible in the system journal. - Surface the failure record in ``settings.html`` as an inline
  banner with timestamp, exit code, last step, and a collapsible journal tail. The JS refreshes the
  banner on page load and after every update poll.

Depends on JTN-704's ``.last-update-failure`` JSON contract (#484).

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* refactor(update): address SonarCloud findings on JTN-710

- _update_status.py: drop redundant ``UnicodeDecodeError`` catch (S5713); it's a ``ValueError``
  subclass and ``errors="replace"`` means decode cannot raise anyway. - settings_page.js: hoist
  ``renderUpdateFailureBanner`` out of the ``createSettingsPage`` closure to module scope (S7721)
  and split the two render branches into ``renderUpdateFailureUnreadable`` /
  ``renderUpdateFailureFields`` helpers to drop cognitive complexity from 22 to well under the 15
  threshold (S3776).

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.52.1 (2026-04-15)

### Bug Fixes

- **update**: Timeout-based service startup wait (JTN-706)
  ([#486](https://github.com/jtn0123/InkyPi/pull/486),
  [`560829a`](https://github.com/jtn0123/InkyPi/commit/560829a16ff4a31a32ee32e74d3afe1ce25f9b31))

* fix(update): timeout-based service startup wait (JTN-706)

The previous 3-attempt loop (sleep 1 between attempts) in update_app_service() capped the total wait
  at 3 seconds. On a Pi Zero 2 W the inkypi service routinely takes 5-8 seconds to become active
  (flask import + plugin discovery), so updates reported false-failure while the service was healthy
  a few seconds later.

Replace the fixed-attempt loop with a `timeout 45` bounded wait and distinguish the two failure
  modes in the error message:

- systemctl reports the unit as `failed` -> show a genuine failure message and dump status +
  journal. - 45s elapsed without becoming active -> report a timeout, still dump status + journal so
  the user can investigate.

The existing JTN-704 EXIT trap path is unchanged: exit 1 on either branch triggers the structured
  failure record and lockfile cleanup.

Regression test (tests/unit/test_install_scripts.py): test_update_service_wait_uses_timeout_bound
  asserts the old max_attempts=3 pattern is gone and the new timeout/45/is-failed wording is
  present.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* fix(update): env-override timeout + tighten test assertion

Address CodeRabbit review feedback on PR #486:

- Make the 45s ceiling overridable via INKYPI_SERVICE_START_TIMEOUT, mirroring the
  INKYPI_LOCKFILE_DIR test-flexibility pattern. Reject non-numeric overrides with a fallback to 45
  so `timeout` never errors on bad input. Production callers do not set this.

- Tighten test_update_service_wait_uses_timeout_bound to match an actual 45-second assignment
  (`wait_seconds=...45` with optional env expansion, or a literal `timeout 45`) instead of any
  occurrence of "45" in the function body. Prevents future false-positive matches from comments or
  URLs.

Skipped CodeRabbit nit about extracting shared start-service helper for install.sh: that's a
  separate concern (install.sh start_service has no verification at all today) and belongs in its
  own issue.

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.52.0 (2026-04-15)

### Features

- **observability**: Add /api/diagnostics consolidated endpoint (JTN-707)
  ([#483](https://github.com/jtn0123/InkyPi/pull/483),
  [`ee24e31`](https://github.com/jtn0123/InkyPi/commit/ee24e3119390d748f5a45e6fa1071053679d5994))

* feat(observability): add /api/diagnostics consolidated endpoint (JTN-707)

Consolidates uptime, memory, disk, refresh-task state, plugin health, log tail, version info, and
  last-update failure into a single JSON endpoint so operators can diagnose a wedged Pi Zero 2 W
  without SSH. This also unblocks the M2 in-app status badge and the K3 rollback UI.

* New blueprint src/blueprints/diagnostics.py exposing GET /api/diagnostics * Reads prev_version and
  .last-update-failure from /var/lib/inkypi when present (null when absent — JTN-704 will start
  writing the latter) * Plugin health is a flat "ok"/"fail"/"unknown" map over every registered
  plugin so the UI shape is stable even before the first refresh cycle * Access gated on the
  app-wide PIN auth hook; when PIN auth is off, only private/loopback callers (or INKYPI_ENV=dev)
  are allowed — avoids leaking internals on un-auth'd deployments * Log tail reuses
  blueprints.settings._read_log_lines so journald and dev-mode in-memory buffers are both supported,
  capped at 100 lines * tests/unit/test_diagnostics_endpoint.py covers shape, missing-file branches,
  plugin health mapping, log-tail cap, and access control

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* test(diagnostics): add fallback-branch coverage (JTN-707)

Pushes coverage on src/blueprints/diagnostics.py from 69% to 89% so SonarCloud's 80% New Code gate
  passes. New tests exercise:

* _uptime_seconds /proc/uptime fallback and total-failure path * _memory_info /proc/meminfo fallback
  and total-failure path * _disk_info shutil.disk_usage error path * _read_version VERSION-missing
  fallback to APP_VERSION and 'unknown' * _refresh_task_snapshot missing-task,
  multi-error-most-recent-wins, and health-snapshot-raises paths * _plugin_health_summary
  broken-registry still returns a dict * _is_private_address classifier (loopback, RFC1918,
  link-local, v6, public, empty, None, unparseable) * unparseable REMOTE_ADDR gets 403 (fail closed)

* refactor(diagnostics): extract helpers to cut cognitive complexity (JTN-707)

Addresses two SonarCloud S3776 findings on the new blueprint:

* _refresh_task_snapshot cognitive complexity 26 -> well under 15 by extracting _latest_refresh_ts,
  _safe_health_snapshot, and _most_recent_plugin_error * _plugin_health_summary cognitive complexity
  21 -> under 15 by reusing _safe_health_snapshot and extracting _status_to_label

Behavior is unchanged; all 27 existing tests still pass and line coverage on the module stays at
  89%.

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.51.11 (2026-04-15)

### Bug Fixes

- **install**: Atomic swap + flock concurrent-install guard (JTN-696)
  ([#489](https://github.com/jtn0123/InkyPi/pull/489),
  [`956afae`](https://github.com/jtn0123/InkyPi/commit/956afae16eae9243393064d0b125554f4029bd42))

* fix(install): atomic swap + flock concurrent-install guard (JTN-696)

install_src() previously did `rm -rf "$INSTALL_PATH"` in place before repopulating. Ctrl+C
  mid-delete left dangling symlinks / a half-populated directory which crashed the display on next
  refresh. Two concurrent `sudo bash install.sh` invocations had no lock and could race each other
  through the rm/repopulate sequence.

Fix: - Add a concurrent-install guard: re-exec install.sh under `flock -n -E 42
  /var/lock/inkypi.install.flock` before the main install body. The second caller exits fast with a
  clear "Another install/update is already running" message. - Replace in-place delete with an
  atomic swap: stage the new tree at `$INSTALL_PATH.new`, move the current tree aside to
  `$INSTALL_PATH.old`, `mv -T` the staging dir into place, then rm the backup. An interruption
  before the final mv leaves the prior install fully intact. - Install an EXIT trap
  (`_cleanup_staging`) that removes leftover `$INSTALL_PATH.new` / `.old` staging dirs after an
  interrupted run. The trap deliberately does NOT touch `$LOCKFILE` (JTN-607 policy: leave it in
  place on failure so the user must rerun) and does NOT remove `$INSTALL_PATH` itself (so a healthy
  prior install is preserved).

Cooperates with JTN-704's trap-cleanup on update.sh and JTN-607's install-in-progress lockfile —
  those files are untouched.

Tests (tests/unit/test_install_scripts.py): - test_install_uses_flock_concurrent_guard — asserts
  FLOCK_PATH, `flock -n`, and the user-facing error message are present and that flock runs before
  `touch "$LOCKFILE"`. - test_install_uses_atomic_swap_not_in_place_rm — asserts `rm -rf
  "$INSTALL_PATH"` is gone from install_src() and `mv -T` + `.new` staging suffix are present. -
  test_install_exit_trap_cleans_staging_not_lockfile — asserts the new EXIT trap exists, does not
  touch $LOCKFILE, and _cleanup_staging never bare-removes $INSTALL_PATH.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* fix(install): use fd-based flock to avoid exec permission issue

flock's exec form `flock -n "$FLOCK_PATH" "$0" "$@"` tried to exec ./install.sh directly without a
  shell interpreter, failing with "Permission denied" on the trixie install-matrix runner where the
  script was invoked as `./install.sh` without `bash` in front.

Switch to the fd-based form: exec 9>"$FLOCK_PATH" flock -n -E 42 9 || exit ...

This takes the lock on fd 9 in the current shell — no re-exec needed. The kernel releases the lock
  automatically when the shell exits.

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Testing

- **ui**: Parametrize click sweep over all registered plugins (JTN-698)
  ([#485](https://github.com/jtn0123/InkyPi/pull/485),
  [`3b6bed6`](https://github.com/jtn0123/InkyPi/commit/3b6bed6bafa3b84e4bb6c6c50df9ca1f9abc9dc2))

Adds a new `test_click_sweep_plugin_pages` parametrize that sweeps `/plugin/<id>` for every plugin
  discovered via plugin-info.json at collection time, catching handler regressions in
  weather/todo/comic/image pickers — previously only the clock plugin was covered, and JTN-681's
  clock-face-picker bug was caught incidentally because we happened to sweep it. Any plugin handler
  class of bug is now in net.

- Extract the click-sweep body into a shared `_run_click_sweep()` helper so both the core-pages and
  plugin-pages tests use identical logic. - Discover plugin IDs at collection time by scanning
  `src/plugins/*/plugin-info.json` — parametrize IDs show up in `pytest --collect-only` output (one
  case per plugin). - Gate the new test behind `@pytest.mark.plugin_sweep` so CI can route it to a
  dedicated job if runtime pressure grows. Registered the marker in pytest.ini. - Tighter
  `_PLUGIN_MAX_CLICKS_PER_PAGE = 15` cap keeps the full 21-plugin sweep to ~60s wall-time on a local
  run. - Desktop-only by design: plugin settings pages don't have mobile reflow, so mobile coverage
  would ~2x runtime for no new signal. - Tag the shared "Update Preview" / "Save Settings" / "Update
  Instance" buttons with `data-test-skip-click="true"` — they submit the settings form and trigger
  validation 400s when clicked with a default form state; dedicated submission tests already
  exercise the real path. - Surfaced two pre-existing plugin handler bugs (weather, todo_list)
  xfailed with tracking links (JTN-716, JTN-717) so the infra lands green and the bugs are fixed
  separately.

Runtime: 21 plugin cases in ~60s locally. Full `test_click_sweep.py` suite (core + plugin sweeps, 2
  xfails) runs in ~87s.

D1 item from the 2026-04-14 codebase audit (.claude/grade-report.md).

Refs: https://linear.app/jtn0123/issue/JTN-698

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.51.10 (2026-04-15)

### Bug Fixes

- **install**: Verify wheelhouse integrity after extraction (JTN-697)
  ([#482](https://github.com/jtn0123/InkyPi/pull/482),
  [`0fbc3bb`](https://github.com/jtn0123/InkyPi/commit/0fbc3bb0d6d31fd78ae139177b71cb0269fd5f29))

fetch_wheelhouse previously only checked that at least one .whl existed after extracting the
  tarball. A truncated-but-decompressing tarball can leave a zero-byte numpy-*.whl behind; pip
  "installs" it and the ImportError only surfaces on first display refresh.

Add a two-layer integrity gate after extraction:

1. Per-wheel sha256 manifest (preferred). build-wheelhouse.yml now emits <tarball>.manifest.sha256
  alongside the tarball — one sha256sum line per wheel with basenames only. fetch_wheelhouse
  downloads the manifest when available and runs `sha256sum -c` (or shasum -a 256 -c) against every
  extracted wheel. Any mismatch falls back to source install.

2. Structural fallback (for releases predating the manifest). Every extracted wheel must be
  non-empty and must pass `python -m zipfile -l` so pip never sees a malformed archive.

Any failure path keeps the existing rm -rf + return 1 contract so the caller transparently falls
  back to source install.

Tests: - test_fetch_wheelhouse_verifies_integrity — structural assertions on _common.sh (empty
  guard, zipfile check, manifest verification, ordering against WHEELHOUSE_DIR assignment). -
  test_fetch_wheelhouse_rejects_empty_wheel_integration — end-to-end: builds a tarball containing a
  0-byte wheel, stubs curl/uname, sources _common.sh, asserts fetch_wheelhouse exits 1 with
  WHEELHOUSE_DIR empty. - test_workflow_publishes_per_wheel_manifest — guards the new manifest
  output in build-wheelhouse.yml.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- **update**: Trap-cleanup lockfile + record failure cause (JTN-704)
  ([#484](https://github.com/jtn0123/InkyPi/pull/484),
  [`3d080bb`](https://github.com/jtn0123/InkyPi/commit/3d080bb51eadcf76b93cb87c584231f2deb3de83))

Previously, `install/update.sh` only removed `/var/lib/inkypi/.install-in-progress` on the success
  path. Any non-zero exit (OOM, pip failure, CSS build failure, network hiccup, signal) orphaned the
  lockfile, which `inkypi.service`'s ExecStartPre refuses to accept, leaving the service permanently
  disabled until the user `rm`'d it by hand. Worse, the *reason* for the failure was only in the
  journal — nothing the UI could surface.

This inverts the policy:

* EXIT trap now *unconditionally* removes the lockfile on every exit (success, explicit `exit N`,
  errexit, SIGINT, SIGTERM, SIGHUP). * On non-zero exit the trap writes
  `/var/lib/inkypi/.last-update-failure` with a JSON record containing `timestamp`, `exit_code`,
  `last_command`, and `recent_journal_lines` for UI / diagnostics consumption. JSON is written
  atomically (tmpfile + mv) so partial writes are impossible. * On success exit the trap clears any
  stale failure record so downstream consumers see a clean signal. * The old `_lockfile_keep`
  sentinel is removed — all `exit 1` paths now funnel through the same trap. * `_current_step` is
  updated before each top-level phase so the failure record pinpoints which step failed.

Test hooks are behind env vars that production callers never set:

* `INKYPI_UPDATE_TEST_FAIL_AT=<step>`: `exit 97` at the named step. *
  `INKYPI_UPDATE_TEST_EXIT_AFTER_TRAP=1`: `exit 0` right after trap install, exercising the
  success-path trap branch. * `INKYPI_LOCKFILE_DIR=<path>`: redirect state writes to a tempdir.

Tests:

* `tests/integration/test_update_failure_recovery.py` — drives `update.sh` with the env hooks and
  asserts (a) lockfile cleared on failure, (b) `.last-update-failure` is valid JSON with the
  required keys + correct exit_code / last_command, (c) success path writes nothing and clears stale
  failure records. * `tests/unit/test_install_scripts.py` — `test_update_has_exit_trap_for_lockfile`
  updated for the new unconditional-cleanup policy; new
  `test_update_exposes_test_failure_injection_env_var` structural check.

Closes JTN-704.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Testing

- **ui**: Form round-trip persistence (JTN-690) ([#478](https://github.com/jtn0123/InkyPi/pull/478),
  [`e47c0b7`](https://github.com/jtn0123/InkyPi/commit/e47c0b78fdcb91c13d6eb445d2b02223343dbd31))

* test(ui): form round-trip persistence (JTN-690)

Adds a Playwright integration test that catches "POST returns 200 but didn't actually save" bugs — a
  class invisible to the existing handler audit, click-sweep, client-log tripwire, and axe-a11y
  layers.

For each covered form the test: 1. Navigates to /settings and captures a baseline. 2. Fills
  known-good values across text, select, slider, and checkbox inputs. 3. Submits. 4. Navigates away
  to '/' and back to force a full template re-render from disk (not in-memory client state). 5.
  Asserts the submitted values are re-populated. 6. Restores the baseline in teardown via
  try/finally so the test is idempotent on failure.

A second test specifically exercises the unchecked-checkbox round-trip (HTML forms omit unchecked
  checkboxes from the POST body — a common source of "toggle-off didn't stick" bugs).

Slice 4 of the pre-dogfooding UI/UX coverage plan.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* fix(tests): skip test_form_roundtrip when playwright browser missing (JTN-690)

Add test_form_roundtrip.py to UI_BROWSER_TESTS so CI runners without chromium installed skip it
  instead of erroring at browser_page fixture setup. Matches prior fixes in PRs #475/#477.

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.51.9 (2026-04-14)

### Bug Fixes

- **install**: Gate service-enable on CSS build success (JTN-695)
  ([#481](https://github.com/jtn0123/InkyPi/pull/481),
  [`deb3f70`](https://github.com/jtn0123/InkyPi/commit/deb3f70c5bd5904dca5d95c3829566cd46010d8f))

Reorder install.sh so update_vendors.sh and build_css_bundle run BEFORE install_app_service.
  Previously a vendor-CDN timeout or CSS build error after systemctl enable left the unit enabled
  with src/static/styles/main.css absent — the user booted into an unstyled web UI with no
  indication why.

Also add a post-build assertion that main.css exists AND is non-empty (-s) before calling
  install_app_service, so a silent truncation can't slip past build_css_bundle's existence-only
  check.

Regression tests in tests/unit/test_install_scripts.py: - test_service_enable_gated_on_css_build:
  asserts vendor + CSS build call sites precede install_app_service in the main body. -
  test_install_asserts_main_css_exists_before_service_enable: asserts the -s assertion on main.css
  lands between build_css_bundle and install_app_service.

The JTN-607 lockfile behavior is unchanged — rm -f "\$LOCKFILE" still follows both the CSS build and
  service-enable steps, so any failure in the gating path leaves the lockfile in place.

Linear: https://linear.app/jtn0123/issue/JTN-695

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Documentation

- **readme**: Recommend do_update.sh as primary update path (JTN-694)
  ([#480](https://github.com/jtn0123/InkyPi/pull/480),
  [`53614e0`](https://github.com/jtn0123/InkyPi/commit/53614e081919c04ab37c54fd38bba732bab1758f))

`install/update.sh` performs no git operations — it only rebuilds deps, CSS, and the systemd unit
  against the current checkout. Following the old README (`git pull` + `update.sh`) on a stale tree
  produced a silent no-op that still reported "Update completed" (reproduced live on a Pi stuck on
  v0.51.1).

Rewrite the Update section to promote `sudo bash install/do_update.sh` as the recommended path for
  version bumps (it fetches, resolves the latest semver tag, checks it out, then delegates to
  update.sh). Keep the `git pull` + `update.sh` flow documented as the alternative for pinning to a
  specific branch or SHA, and explicitly call out that `update.sh` alone does not advance the
  checkout.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Testing

- **ui**: Interactive element overlap detector (JTN-689)
  ([#475](https://github.com/jtn0123/InkyPi/pull/475),
  [`2348593`](https://github.com/jtn0123/InkyPi/commit/2348593295474773a6504df9a1632edadfb58815))

* test(ui): interactive element overlap detector (JTN-689)

Adds tests/integration/test_layout_overlap.py — a Playwright-based integration test that walks every
  visible interactive element on each main page and flags visually-colliding clickables (the "this
  button is under the modal header" class of bug).

For each (page, viewport) combo: - Enumerates button/a/input/[role=button]/[data-*-action]
  candidates that pass clickability checks (visible, not pointer-events:none, not aria-hidden/inert,
  not disabled) and have a >=2px rect. - Computes pairwise overlap as overlap_area / min(area_a,
  area_b). - Skips ancestor/descendant pairs so icons inside buttons don't false positive. - Fails
  with the top offending pairs listed at 0.25 threshold.

Runs at 1280x900 and 360x800 across home, settings, history, playlist, plugin_clock, api_keys — same
  page set as the click sweep. All 12 parametrized combinations pass today; no real collisions
  found.

Part of the pre-dogfooding UI/UX coverage plan (item #3, sibling to the click-sweep work in
  JTN-681/682 and client-log tripwire JTN-680).

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* test(ci): defer test_layout_overlap.py when Playwright browsers absent

Add tests/integration/test_layout_overlap.py to UI_BROWSER_TESTS so pytest_ignore_collect skips it
  in environments without the Chromium headless shell, matching the pattern used for other
  browser-driven tests.

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- **ui**: Per-plugin Update Preview smoke (JTN-691)
  ([#477](https://github.com/jtn0123/InkyPi/pull/477),
  [`5955e4b`](https://github.com/jtn0123/InkyPi/commit/5955e4bd8a78adde0c0e0c99c3a81c3061079ba9))

* test(ui): per-plugin Update Preview smoke (JTN-691)

Add a Playwright integration test that, for each plugin in a fixture dict, navigates to
  /plugin/<id>, fills minimum-viable inputs, clicks Update Preview, and asserts the #previewImage
  src actually changed. Inherits the client-log tripwire from conftest, so any console.warn /
  console.error during the flow fails the test automatically.

Closes the plugin-level correctness blind spot surfaced in JTN-681 (clock face picker handler
  silently no-opped). Initial coverage: clock, year_progress, todo_list — parametrized so adding
  plugins is a one-line dict entry in fixtures/plugin_inputs.py.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* test(ci): skip plugin_preview_smoke when Playwright Chromium missing

The new tests/integration/test_plugin_preview_smoke.py uses the browser_page fixture but wasn't
  registered in UI_BROWSER_TESTS, so pytest_ignore_collect treated it as a non-browser test and
  collected it even when Chromium isn't installed. CI's pytest job doesn't run `playwright install`,
  so the tests errored at BrowserType.launch ("Executable doesn't exist ... chrome-headless-shell").

Add the file to UI_BROWSER_TESTS so collection defers to _playwright_browser_available() and skips
  cleanly, matching every other browser-dependent test in tests/integration/.

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.51.8 (2026-04-14)

### Bug Fixes

- **install**: Copy inkypi-failure.service in update.sh (JTN-686)
  ([#470](https://github.com/jtn0123/InkyPi/pull/470),
  [`76f5aa0`](https://github.com/jtn0123/InkyPi/commit/76f5aa06761debb55a40798482c3ed4fb8db4ac1))

Add install_failure_service_unit helper to _common.sh and call it from both install.sh and update.sh
  so every update path copies inkypi-failure.service alongside inkypi.service, preventing the "Unit
  inkypi-failure.service not found" OnFailure= dangle on pre-JTN-671 installs that update to
  v0.51.1+.

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>

- **update**: Remove lockfile before systemctl start, add EXIT trap (JTN-685)
  ([#472](https://github.com/jtn0123/InkyPi/pull/472),
  [`a00c115`](https://github.com/jtn0123/InkyPi/commit/a00c1156b2223d252f3bf5e8072f388390578f8d))

* fix(update): remove lockfile before systemctl start, add EXIT trap (JTN-685)

The lockfile /var/lib/inkypi/.install-in-progress was removed AFTER update_app_service() called
  `systemctl start`, causing ExecStartPre to see the lockfile and reject every first-boot after an
  update.

Fix: - Move `rm -f "$LOCKFILE"` to just before update_app_service() so the lockfile is gone when
  ExecStartPre runs. - Add `trap ... EXIT` with a `_lockfile_keep` sentinel for defense-in- depth:
  abnormal exits (SIGTERM, unhandled errors) clear the lockfile automatically; intentional failure
  exits set _lockfile_keep=1 to preserve it and force a manual rerun. - Update
  test_install_scripts.py: replace the now-stale assertion that rm came after update_app_service
  with the correct JTN-685 assertion (rm must come BEFORE), and add a new test for the EXIT trap.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* style: apply black formatting to test_install_scripts.py

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Refactoring

- **playlist**: Reduce update_playlist complexity, dedupe string
  ([#479](https://github.com/jtn0123/InkyPi/pull/479),
  [`2ed09cf`](https://github.com/jtn0123/InkyPi/commit/2ed09cf9fb64a025691339fbb07f14a6bed90215))

Address SonarCloud findings on the JTN-658 PR: - S3776: extract _validate_update_playlist_payload so
  update_playlist stays under the cognitive-complexity budget. - S1192: hoist "Playlist not found"
  into _MSG_PLAYLIST_NOT_FOUND.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Testing

- **ui**: Responsive mobile click-sweep (JTN-693)
  ([#473](https://github.com/jtn0123/InkyPi/pull/473),
  [`c07cca2`](https://github.com/jtn0123/InkyPi/commit/c07cca28b5e23722f7425376606b79d8836e1c8d))

Parametrize test_click_sweep over viewport so the sweep runs at both desktop (1280×900) and mobile
  (360×800). The mobile fixture already existed in tests/integration/conftest.py; this reuses it via
  indirect fixture lookup rather than duplicating sweep logic.

Adds _MOBILE_XFAIL_PAGES as an empty parking spot for mobile-only breaks discovered during rollout.
  Existing _XFAIL_PAGES entries continue to apply to both viewports.

No mobile-only breaks found during local runs; mobile failures exactly mirror desktop failures (and
  those desktop failures exist on main, unrelated to this change).

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- **ui**: Toggle state-reflection sweep (JTN-688)
  ([#474](https://github.com/jtn0123/InkyPi/pull/474),
  [`89980f4`](https://github.com/jtn0123/InkyPi/commit/89980f4f7f86d459048d286e238808986971611e))

* test(ui): add toggle state-reflection sweep (JTN-688)

Parallel to the existing click sweep but focused on toggle-like elements ([role=switch],
  input[type=checkbox], [data-toggle], collapsible/playlist toggles, [aria-pressed]). For each
  toggle: snapshot aria-checked, aria-pressed, aria-expanded, checked, classList, data-state before
  click; click; assert at least one field changed. This closes the "handler fires but UI doesn't
  reflect" gap that slipped JTN-681.

Filters out toggles that navigate away or open modals — those are covered by the dedicated
  click-sweep and modal-lifecycle tests.

Dispatches clicks via element.click() in page context so styled sibling overlays (e.g. .toggle-label
  covering .toggle-checkbox) don't swallow coordinate-based Playwright clicks.

playlist page is xfailed pending JTN-692 (playlist-toggle-button is a visible no-op on desktop
  because setPlaylistExpanded short-circuits for non-mobile viewports) — exactly the class of bug
  this sweep is designed to catch.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* test(ui): register test_toggle_reflection in UI_BROWSER_TESTS (JTN-688)

Without this entry, the new integration test is collected under the jsdom/no-browser path, which
  causes Playwright browser launches to fail on CI runners where the chromium-headless-shell binary
  is not installed. Adding it to UI_BROWSER_TESTS triggers the playwright install step and gates the
  test on browser availability, matching every other UI test.

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.51.7 (2026-04-14)

### Bug Fixes

- **clock**: Activate face picker handler when color fields are outside widget (JTN-681)
  ([#466](https://github.com/jtn0123/InkyPi/pull/466),
  [`f9a75f2`](https://github.com/jtn0123/InkyPi/commit/f9a75f2355e6b50808d4b8ff51f86ed0800d9591))

* fix(clock): activate face picker handler when color fields are outside widget (JTN-681)

`initClockFacePicker` was scoped to the widget wrapper when looking up `primaryColor` /
  `secondaryColor` inputs, but those fields live in a sibling schema section on the plugin form. The
  early-return guard fired, so no click handler was ever attached and the initial `.selected` class
  was never applied.

Fix: scope the colour-field lookup to the settings-schema root and drop the color inputs from the
  required-input guard. Also dispatch `input`/`change` events when syncing colour values so any
  bound preview swatches stay in sync.

Remove `plugin_clock` from `_XFAIL_PAGES` in the Layer-3 click sweep and add a dedicated regression
  test that asserts both the initial selection state and the post-click class/value sync.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* test(jtn-681): gate new clock face picker test on Playwright availability

The test uses the `browser_page` fixture which requires Chromium. Add it to `UI_BROWSER_TESTS` so
  it's collected only when Playwright browsers are available (or SKIP_BROWSER / SKIP_UI aren't set),
  matching how the existing click sweep test is gated.

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.51.6 (2026-04-14)

### Bug Fixes

- **security**: Pin DNS for plugin URL fetches to block rebinding SSRF (JTN-656)
  ([#467](https://github.com/jtn0123/InkyPi/pull/467),
  [`d1f23ef`](https://github.com/jtn0123/InkyPi/commit/d1f23ef64d32c811a0ef143ff1cef9c8a3ab59ce))

* fix(security): pin DNS for plugin URL fetches to block rebinding SSRF

`validate_url` resolved DNS once to reject private targets, but the subsequent
  `http_get`/`session.get` call resolved DNS *again*. An attacker-controlled authoritative server
  can flip the second answer to a private IP (127.0.0.1, 169.254.169.254 metadata, 192.168.x)
  between the two resolutions, bypassing the SSRF guard.

Fix: resolve once, pin the result.

- `validate_url_with_ips` returns the validated URL **and** the IPs observed at validation time.
  `validate_url` still returns a bare string for backward compat. - New `pinned_dns(hostname, ips)`
  context manager in `utils.http_utils` swaps `socket.getaddrinfo` for a thread-coordinated wrapper
  that returns only the pinned IPs for the matching hostname, then restores the previous resolver on
  exit. Because only the socket connect step sees the IP, TLS SNI and certificate validation still
  happen against the original hostname (HTTPS vhost + cert matching unchanged). - `safe_http_get`
  combines validation + pinning around `http_get`. - `image_utils.get_image` /
  `fetch_and_resize_remote_image` now validate and pin internally; plugins inherit the fix with no
  call-site change. - `ImageAlbum` / `ImmichProvider` propagate the pinned IPs and bracket each
  Immich API call in `pinned_dns`.

Tests (`tests/unit/test_ssrf_dns_rebind.py`, 10 cases) simulate the rebind by swapping
  `socket.getaddrinfo` between the two resolutions and assert the fetch connects to the
  originally-vetted IP.

Closes JTN-656.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* refactor(http_utils): split getaddrinfo wrapper to cut cognitive complexity

Addresses SonarCloud S3776: the inline wrapper inside `_make_patched_getaddrinfo` had cognitive
  complexity 31. Broken into three tiny helpers — `_normalize_host`, `_coerce_port`,
  `_addrinfo_for_pinned_ip` — each with a single responsibility. No behavior change.

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.51.5 (2026-04-14)

### Bug Fixes

- **security**: Nonce-based CSP eliminates inline script violations (JTN-687)
  ([#476](https://github.com/jtn0123/InkyPi/pull/476),
  [`caf71f4`](https://github.com/jtn0123/InkyPi/commit/caf71f4f798f3ad8407e16626ccd94a0b24719a5))

* fix(security): nonce-based CSP to allow inline scripts (JTN-687)

Replace the monolithic script-src 'self' with a per-request nonce so inline <script> blocks that
  pass Jinja data into static page scripts are explicitly allowed without using 'unsafe-inline'.

- Generate secrets.token_urlsafe(16) per request in new setup_csp_nonce(); stored on
  flask.g.csp_nonce and injected into every Jinja template via a context_processor. -
  _DEFAULT_CSP_TEMPLATE: script-src now includes 'nonce-{nonce}'. Custom INKYPI_CSP overrides remain
  verbatim (operator's responsibility). - All inline <script> blocks in base.html, inky.html,
  plugin.html, settings.html, history.html, playlist.html and refresh_settings_form.html gain
  nonce="{{ csp_nonce }}". - tests/conftest.py wires setup_csp_nonce() and mirrors the nonce in the
  test-app's CSP after_request hook. - Two new unit tests assert nonce presence and per-request
  uniqueness.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* style: apply black formatting to test_security_headers_csp_hsts.py

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.51.4 (2026-04-14)

### Bug Fixes

- **ci**: Wire build-wheelhouse to Release workflow_run (JTN-683)
  ([#469](https://github.com/jtn0123/InkyPi/pull/469),
  [`17b2641`](https://github.com/jtn0123/InkyPi/commit/17b2641d5fa57a7e75441ae8cf07f270bccbce93))

The `on: release: types: [published]` trigger never fired because semantic-release creates releases
  via GITHUB_TOKEN, and GitHub blocks GITHUB_TOKEN-created events from triggering downstream
  workflow listeners (documented security boundary).

Added `workflow_run: workflows: ["Release"] types: [completed]` trigger so the wheelhouse build
  chains off the Release workflow directly — this mechanism works regardless of which token the
  upstream run used. A new `check-trigger` guard job evaluates the event type, skips if the upstream
  run didn't succeed, and resolves the release tag (from the event payload for
  `release`/`workflow_dispatch`, or from `gh release list` for `workflow_run`). The `release` event
  trigger is kept for forward compatibility.

Also updated the "Attach wheelhouse to release" step condition to include `workflow_run` events so
  wheels are attached to the release (not uploaded as ephemeral artifacts) in the automated path.

Follow-up: manually backfill wheels for v0.51.1 via workflow_dispatch after this merges.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- **install**: Check systemctl is-active after start in update_app_service (JTN-684)
  ([#471](https://github.com/jtn0123/InkyPi/pull/471),
  [`4846440`](https://github.com/jtn0123/InkyPi/commit/4846440b7a386250042f2af4f1c5a9a3f21be9dd))

Previously update_app_service() called `sudo systemctl start` without verifying the service actually
  reached the active state. systemctl start exits 0 even when the unit's ExecStart subsequently
  fails (e.g. bad ExecStart path, missing dep), causing update.sh to print "Update completed ✔" and
  exit 0 while inkypi.service sat in a failed state.

Add an explicit retry loop (3× 1 s) that calls `systemctl is-active --quiet` after the start. On
  failure: dump `systemctl show` properties and the last 20 journal lines to stderr, print a clear
  error, and exit 1. On success, the existing success path is unchanged.

Three new tests in TestUpdateScript assert that update_app_service() contains an is-active check, an
  exit 1, and a --no-pager journalctl call.

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>


## v0.51.3 (2026-04-14)

### Bug Fixes

- **playlist**: Return details.field from every validator (JTN-658)
  ([#468](https://github.com/jtn0123/InkyPi/pull/468),
  [`c2c2451`](https://github.com/jtn0123/InkyPi/commit/c2c245188e170e8c2c27b4327272267fbb4528c4))

Only `validate_plugin_refresh_settings` previously populated `details.field` in its error envelope.
  Every other validation failure returned a generic message with no field attribution, so the
  frontend couldn't highlight the offending input.

Standardize every validator in `src/blueprints/playlist.py` to emit the canonical `{code:
  "validation_error", details: {field: "..."}}` envelope and stop wrapping validator output through
  `reissue_json_error` (those messages are static strings — safe to surface verbatim, and masking
  them was the main source of "can't tell which field broke" dogfood reports).

Hook the frontend up via a small `applyFieldErrorFromResponse` helper on `playlist.js` that reads
  `details.field` and defers to the existing `FormState.setFieldError` utility (aria-invalid + focus
  + scroll into view). Keeps `field_errors` as a fallback so partial deploys don't regress the UI.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Testing

- **ui**: Skip historyRefreshBtn in click sweep (JTN-682)
  ([#465](https://github.com/jtn0123/InkyPi/pull/465),
  [`8436fab`](https://github.com/jtn0123/InkyPi/commit/8436fabf77df13566765e7106f056ac6ada6ab9e))

The Refresh button on /history calls location.reload(), which restarts the page mid-sweep and
  destabilises subsequent clicks. Tag it with data-test-skip-click="true" so the sweep walks around
  it, and remove history from _XFAIL_PAGES now that the page passes cleanly.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.51.2 (2026-04-14)

### Bug Fixes

- **install**: Add libffi-dev and libsystemd-dev to debian-requirements (JTN-675)
  ([#464](https://github.com/jtn0123/InkyPi/pull/464),
  [`fcb44be`](https://github.com/jtn0123/InkyPi/commit/fcb44be7ed3cf646aee52dd9f05688bbffe8e316))

`install/requirements.txt` pins `cffi` and `cysystemd`, both of which need native headers when built
  from source. On Python 3.13 armv7 (Pi Zero 2 W / Trixie), piwheels has no prebuilt wheels, so pip
  falls back to source builds and fails with:

fatal error: ffi.h: No such file or directory fatal error: systemd/sd-daemon.h: No such file or
  directory

Add the two missing -dev packages to the apt preflight list so install.sh / update.sh succeed on a
  fresh Pi Zero 2 W.

Also add a regression test (test_install_scripts.py) that asserts the apt list keeps libffi-dev and
  libsystemd-dev in sync with the pinned Python deps. The test fails on the old
  debian-requirements.txt and passes with the fix.

Verified on inkypi.local during v0.38.0 -> v0.49.20 update: after `apt install -y libffi-dev
  libsystemd-dev`, both wheels built cleanly.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.51.1 (2026-04-14)

### Bug Fixes

- **benchmarks**: Parameterize/validate SQL identifiers in benchmark_storage
  ([#463](https://github.com/jtn0123/InkyPi/pull/463),
  [`5beaf73`](https://github.com/jtn0123/InkyPi/commit/5beaf73991e634f7b141adb87d6d027d75b3eac0))

* fix(benchmarks): validate SQL identifiers in benchmark_storage to prevent injection

Add allow-list validation for table names and a strict regex check for column identifiers before
  interpolating them into PRAGMA/ALTER TABLE statements, resolving code-scanning alerts #119-#122
  (sqlalchemy-execute-raw-query / formatted-sql-query rules).

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

* test(benchmarks): add tests for _validate_identifier and _ensure_optional_columns

- Assert _validate_identifier raises ValueError on bad inputs (spaces, hyphens, SQL injection
  strings, empty string, digit-leading names) - Assert _validate_identifier accepts valid
  identifiers unchanged - Assert _ensure_optional_columns raises ValueError for unknown table names
  - Assert _ensure_optional_columns correctly adds missing columns - Assert _ensure_optional_columns
  is idempotent on existing columns

---------

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>

- **ci**: Prevent shell injection in workflows via env vars
  ([#460](https://github.com/jtn0123/InkyPi/pull/460),
  [`66ea219`](https://github.com/jtn0123/InkyPi/commit/66ea219ea9262aeb46bcb3a9b7b85bad6c0b941d))

Move \`\${{ github.* }}\` interpolations in run: scripts into env: blocks and reference them as
  shell variables — fixes GitHub code-scanning alerts 108, 109, 110, 111
  (yaml.github-actions.security.run-shell-injection) in os-drift-nightly.yml (lines 61, 219),
  build-wheelhouse.yml (line 52), and build-pi-image.yml (line 73).

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>

- **docker**: Non-root USER, HEALTHCHECK, combined apt RUN
  ([#462](https://github.com/jtn0123/InkyPi/pull/462),
  [`6749e2d`](https://github.com/jtn0123/InkyPi/commit/6749e2d8412fc627a5860be2c111b8f0eee1f77e))

Addresses Dockerfile security alerts DS-0002, DS-0026, DS-0017:

- Dockerfile: add appuser (uid 1000), chown /app, USER appuser, and a real HEALTHCHECK for the Flask
  server on port 8080 (alerts 112, 130) - scripts/Dockerfile.install-matrix: add explicit USER root
  + HEALTHCHECK NONE (install.sh requires root; explicit USER satisfies DS-0002); remove standalone
  apt-get update from raspi.list RUN — install.sh runs its own update, eliminating the stale-cache
  layer (DS-0017, alert 131, 133, 135, 137) - scripts/Dockerfile.sim-install: same USER root +
  HEALTHCHECK NONE pattern; same standalone apt-get update removal (DS-0017, alert 132, 134, 136)

Fixes alerts: 112, 130, 131, 132, 133, 134, 135, 136, 137.

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>

- **scripts**: Use defusedxml in coverage_gate.py
  ([#461](https://github.com/jtn0123/InkyPi/pull/461),
  [`27caee9`](https://github.com/jtn0123/InkyPi/commit/27caee9f4e4208f69d8a5348022e679465ab7c49))

* fix(scripts): use defusedxml in coverage_gate.py

Replace stdlib xml.etree.ElementTree with defusedxml.ElementTree in scripts/coverage_gate.py to
  resolve Semgrep alert #113 (python.lang.security.use-defused-xml-parse.use-defused-xml-parse). The
  defusedxml API is drop-in compatible; no behaviour change.

Add defusedxml>=0.7,<1 to install/requirements-dev.in so the dependency is explicit in the
  source-of-truth constraints file.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

* fix(lint): sort imports in coverage_gate.py (ruff I001)

Move defusedxml third-party import below stdlib imports to satisfy ruff's isort rule I001.

---------

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>

### Testing

- **ui**: Layer 3 click sweep + backend route smoke (JTN-679)
  ([#459](https://github.com/jtn0123/InkyPi/pull/459),
  [`6e2ec41`](https://github.com/jtn0123/InkyPi/commit/6e2ec4119f08885e99d3762f74a6d8d7d8f136a3))

* test(ui): add Layer 3 click sweep + backend route smoke (JTN-679)

Stand up the runtime half of the UI breakage detection net:

* `tests/smoke/test_route_smoke.py` — walks `app.url_map.iter_rules()` and GETs every
  unparameterized route via the `client` fixture. Asserts no 5xx, status in a controlled set
  (200/302/400/401/403/404/405/422), and that HTML responses have a `<title>` and no `Internal
  Server Error`/`Traceback` marker. Allowlist lives at `tests/smoke/route_allowlist.yml`.

* `tests/integration/test_click_sweep.py` — Playwright sweep (gated by `SKIP_BROWSER`/`SKIP_UI`)
  over 6 pages (home, settings, history, playlist, plugin/clock, api_keys). For each visible
  `<button>`/`<a>`/`[data-*-action]` that isn't `data-test-skip-click="true"`, clicks it and asserts
  no pageerror, no `console.error`, no 5xx, AND an observable change
  (URL/DOM/network/modal/full-document reload sentinel).

* Destructive controls tagged `data-test-skip-click="true"` in their templates with HTML comments
  explaining why: settings (Safe Reset, Isolate/Unisolate, Reboot, Shutdown, Clear Logs), history
  (Clear All, per-row Delete), playlist (Delete playlist, Delete instance), api_keys (Delete row
  `×`, Delete stored key).

Two pages currently xfail pending fixes tracked in follow-up issues: * `plugin_clock` → JTN-681
  (clock face picker clicks show no DOM mutation) * `history` → JTN-682 (Refresh button reload not
  detected as observable)

Part of the JTN-677 epic. Reuses `browser_page`/`RuntimeCollector` from `tests/integration/`,
  `client`/`flask_app` from `tests/conftest.py`, and the existing `SKIP_BROWSER` gating.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* test(ui): gate click sweep on Playwright availability

The Tests (pytest) CI job doesn't install Playwright Chromium — browser tests are expected to
  auto-skip there via the `UI_BROWSER_TESTS` registry in `tests/conftest.py`. Register
  `test_click_sweep.py` so it obeys the same gating as the other e2e browser tests.

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.51.0 (2026-04-14)

### Features

- **test**: Wire /api/client-log into Playwright tripwire (JTN-680)
  ([#458](https://github.com/jtn0123/InkyPi/pull/458),
  [`6c7115e`](https://github.com/jtn0123/InkyPi/commit/6c7115e2c732935c45f806cd0bb8dcfa0bdbbd5c))

Layer 4 of the UI breakage detection net. Convert the existing always-on /api/client-log endpoint
  into a test-time tripwire so any console.warn / console.error that bubbles through
  client_log_reporter.js during a Playwright test fails the test with the message visible.

Changes: - src/blueprints/client_log.py: add env-var-gated capture hook. When
  INKYPI_TEST_CAPTURE_CLIENT_LOG is truthy, every validated report is appended to a process-wide
  (lock-protected) list; unset -> bit-identical to pre-hook behaviour (single dict lookup +
  short-circuited compare). - tests/integration/conftest.py: add autouse client_log_capture fixture
  that sets the env var, resets storage, and asserts the list is empty on teardown.
  browser_page/mobile_page inject the client-log-enabled and client-log-test-mode meta tags so the
  reporter opts in and skips its 50% sampling during tests. -
  src/static/scripts/client_log_reporter.js: honour the test-mode meta so the tripwire is
  deterministic (no sampling). - tests/unit/test_client_log_capture.py: new test file proving
  capture is off by default, on with env var, resets, invalid reports are not captured, returned
  list is a copy, and the prod-path response body is bit-identical with capture on vs off.

Parent epic: JTN-677.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Testing

- **ui-audit**: Add Layer 1 static handler audit (JTN-678)
  ([#457](https://github.com/jtn0123/InkyPi/pull/457),
  [`748e30c`](https://github.com/jtn0123/InkyPi/commit/748e30c85432b3f7b50ee5f3c7df0d62c98e4909))

Introduces `tests/ui_audit/` — a stdlib-only pytest that parses every template in `src/templates/`
  and every JS file in `src/static/scripts/` and proves every clickable element has a reachable
  handler.

Three rules enforced: 1. data-X-action="value" must have a JS file that reads dataset.Xaction (or
  uses [data-x-action]) AND the action literal must appear in some JS file (cross-file delegation is
  common: plugin_page.js -> plugin_form.js). 2. <button type="button"> without any data-*-action,
  hx-*, delegated marker, or id/class referenced from JS is an orphan. 3. <a href="#anchor"> must
  resolve to an id in some template or have a JS handler.

Findings: zero dead handlers today. Regression-tested by deleting history_page.js'
  dataset.historyAction read (rule 1 trips) and renaming #historyRefreshBtn (rule 2 trips).

No new deps — uses html.parser + regex. Runs in ~0.2 s.

Part of epic JTN-677 (UI breakage detection net, Layer 1 of 4).

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.50.3 (2026-04-14)

### Bug Fixes

- **css**: Untrack src/static/styles/main.css from git (JTN-672)
  ([#455](https://github.com/jtn0123/InkyPi/pull/455),
  [`540d3ea`](https://github.com/jtn0123/InkyPi/commit/540d3ea0e060707004b3c0f56e94cdd95fcc1f68))

* fix(css): untrack src/static/styles/main.css from git (JTN-672)

main.css was simultaneously tracked in the index and listed in .gitignore, causing `git checkout
  <tag>` to abort ("please stash your changes") whenever build_css.py --minify rewrote the file
  during an update. Running `git rm --cached` removes it from the index so the .gitignore entry
  takes effect; install.sh and update.sh already call build_css.py --minify to regenerate it fresh
  on every deploy.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

* ci: build CSS before running pytest (JTN-672)

main.css is now gitignored and no longer tracked in the repository. Three static CSS tests read the
  file directly and were failing in CI with 404 / FileNotFoundError because the file wasn't present.
  Add a `python scripts/build_css.py` step before `pytest` so the generated file exists during the
  test run.

* ci: add build_css.py step to browser-smoke and flake-detection jobs (JTN-672)

The browser smoke and flake detection jobs also serve main.css through the Flask test client and
  need it present on disk. Add the same `python scripts/build_css.py` step before the test runs in
  those two jobs so they regenerate the file after checkout.

---------

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>

### Chores

- Untrack editor/agent config and add to .gitignore
  ([`26b69e1`](https://github.com/jtn0123/InkyPi/commit/26b69e16dda00777330cf08909e2e5a21a8f59d7))

Remove per-user tooling files from version control and ignore the directories so they stay out: -
  .claude/ (Claude Code launch.json, scheduled_tasks.lock) - .vscode/ (settings.json) - .codex/
  (environments/environment.toml) - .envrc (direnv)

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.50.2 (2026-04-14)

### Bug Fixes

- **install**: Update.sh uses uv + --require-hashes for supply-chain parity (JTN-670)
  ([#456](https://github.com/jtn0123/InkyPi/pull/456),
  [`9c11b6a`](https://github.com/jtn0123/InkyPi/commit/9c11b6a560c0259f4a3bf58ef83edb96cfe24a75))

* fix(install): update.sh now uses uv + --require-hashes for supply-chain parity (JTN-670)

Previously update.sh used bare `pip install --upgrade` without uv or --require-hashes, eroding the
  JTN-516 supply-chain guarantee for all existing Pis that update (only fresh installs were
  hash-verified).

Changes: - Install uv into the venv before the requirements update (JTN-605 parity) - Use `uv pip
  install --require-hashes --no-cache` when uv is available - Fall back to `pip install
  --require-hashes --no-cache-dir` otherwise - Both paths prefix UV_HTTP_TIMEOUT=60 / --retries 5
  for Pi Zero 2 W flaky Wi-Fi resilience (JTN-534 parity) - uv_extra_args already wired into
  fetch_wheelhouse --find-links path - Add 6 new tests covering uv install, --require-hashes
  enforcement, UV_HTTP_TIMEOUT presence, and pip fallback integrity

Part of epic JTN-529 (install path hardening).

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* fix(install): clarify uv_extra_args comment — no --only-binary=:all:

CodeRabbit noted the comment incorrectly implied --only-binary=:all: was being used; only
  --find-links is appended to uv_extra_args. Update the comment to accurately describe the actual
  behavior.

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Refactoring

- **install**: Factor shared helpers into _common.sh (JTN-674)
  ([#454](https://github.com/jtn0123/InkyPi/pull/454),
  [`1662840`](https://github.com/jtn0123/InkyPi/commit/1662840cfeda99eb2d60c2455f7046b5ef54f87f))

* refactor(install): factor shared helpers into _common.sh (JTN-674)

Move duplicated logic from install.sh and update.sh into a single source of truth in
  install/_common.sh: - Formatting helpers: echo_success, echo_error, echo_header, echo_blue,
  echo_override, show_loader (bold/normal/red tput vars) - get_os_version - stop_service (stop +
  disable so systemd cannot restart mid-install) - setup_zramswap_service / setup_earlyoom_service -
  build_css_bundle (extracted from inline CSS build block)

Both scripts now source _common.sh early (right after SCRIPT_DIR is set) so formatting helpers are
  available for every subsequent function. The only code left exclusively in each script is what is
  genuinely unique: install.sh keeps enable_interfaces, fetch_waveshare_driver, install_config,
  ask_for_reboot, wait_for_clock; update.sh keeps update_app_service, update_cli, and the
  pip-upgrade / venv-activation block.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* test(install): update test_install_scripts to look up shared helpers in _common.sh (JTN-674)

Functions moved to _common.sh (stop_service, setup_zramswap_service, get_os_version, echo_*) are no
  longer defined in install.sh/update.sh. Update affected tests to use self.combined (script content
  + _common.sh) so assertions about shared logic keep passing after the JTN-674 refactor.

Also update test_install_removes_lockfile_at_end_on_success to check for the build_css_bundle call
  instead of the inline "CSS bundle built" string (which now lives inside the shared helper in
  _common.sh).

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.50.1 (2026-04-14)

### Bug Fixes

- **service**: Add StartLimitBurst + OnFailure sentinel to stop runaway restart loops (JTN-671)
  ([`322b12e`](https://github.com/jtn0123/InkyPi/commit/322b12e947ba0d30ee8db94e68b1f4c6f044de4f))

* fix(service): add StartLimitBurst + OnFailure sentinel to stop runaway restart loops (JTN-671)

Without StartLimitBurst the JTN-665 incident drove 4,091 restart attempts (~68 h @ 60 s apart),
  burning ~27 min CPU and accelerating SD card wear.

- inkypi.service [Unit]: add StartLimitIntervalSec=1800 + StartLimitBurst=5 so systemd enters
  "start-limit-hit" after 5 failed starts in 30 min - inkypi.service [Unit]: add
  OnFailure=inkypi-failure.service so the failure is written to /var/lib/inkypi/.start-limit-hit for
  healthchecks - install/inkypi-failure.service: new oneshot unit that touches the sentinel file and
  logs via systemd-cat - install/install.sh: install_app_service() now also copies
  inkypi-failure.service into /etc/systemd/system/ - tests: add TestSystemdFailureService +
  test_service_start_limit_burst + test_service_on_failure_references_failure_helper +
  test_install_app_service_installs_failure_helper

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* fix(tests): remove accidentally-included JTN-670 test_update_* guards from JTN-671 PR

The stash-pop when switching branches accidentally included JTN-670's
  test_update_{uv,require_hashes,...} tests which assert features not yet in update.sh on main. This
  commit strips them out — they will land with the JTN-670 PR instead. Only the 6 JTN-671-specific
  tests remain.

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.50.0 (2026-04-14)

### Bug Fixes

- **install**: Make update.sh fail loudly on pip/apt errors (JTN-665)
  ([#446](https://github.com/jtn0123/InkyPi/pull/446),
  [`d80e72f`](https://github.com/jtn0123/InkyPi/commit/d80e72f4c4abbc6b2b8cd7d62b7a81c3744648a9))

Replace silent `&& echo_success` patterns in update.sh with explicit `if !` guards that print an
  error and exit 1 on failure, matching the hardened style already used in install.sh. Covers
  apt-get install, pip upgrade, pip install -r requirements.txt, and update_vendors.sh so a compile
  error (e.g. metadata-generation-failed) can no longer silently fall through to the service restart
  and trigger a boot loop.

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>

- **install**: Set TMPDIR to disk-backed /var/tmp before pip in update.sh (JTN-668)
  ([#447](https://github.com/jtn0123/InkyPi/pull/447),
  [`065796c`](https://github.com/jtn0123/InkyPi/commit/065796cb15844e82eba76908cb79704fcf897f0c))

/tmp on Pi OS Trixie is a 213 MB tmpfs — not enough room for numpy's intermediate build artefacts
  (>500 MB). pip defaults to TMPDIR which defaults to /tmp, so numpy compilation fails with "No
  space left on device".

Fix: export TMPDIR=/var/tmp/pip-build before every pip call in update.sh. /var/tmp is disk-backed
  and has gigabytes free on the affected Pi. The directory is created at runtime and cleaned up on
  success.

Also align the zramswap OS-version guard with install.sh — update.sh was checking only for Bookworm
  (12); now checks Bullseye/Bookworm/Trixie (11/12/13).

Add --retries 5 --timeout 60 --no-cache-dir to pip invocations for parity with install.sh (Pi Zero 2
  W flaky Wi-Fi + SD card space).

Part of epic JTN-529 (install path hardening).

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>

- **install**: Share wheelhouse helpers via _common.sh so update.sh uses pre-built wheels (JTN-669)
  ([#450](https://github.com/jtn0123/InkyPi/pull/450),
  [`a43ae20`](https://github.com/jtn0123/InkyPi/commit/a43ae20dc61fe8dc10e194534b5f9ec13b51dfc7))

* fix(install): share wheelhouse helpers via _common.sh so update.sh uses pre-built wheels (JTN-669)

- Extract fetch_wheelhouse / cleanup_wheelhouse from install.sh into install/_common.sh; both
  install.sh and update.sh now source it. - update.sh calls fetch_wheelhouse before pip upgrade and
  passes --find-links / --prefer-binary when the bundle is available, cutting update time on Pi Zero
  2 W from ~15 min / OOM risk to ~2-3 min. - Adds --retries 5 --timeout 60 --no-cache-dir to
  update.sh pip calls for parity with install.sh (JTN-534 / JTN-602). - Updates
  TestInstallWheelhouseFetch to check install.sh sources _common.sh; adds
  TestCommonWheelhouseFunctions for _common.sh; adds wheelhouse assertions to TestUpdateScript.

Closes JTN-669. Part of epic JTN-529 (install path hardening).

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* style: apply black formatting to test_install_scripts.py

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- **install**: Widen narrow git fetch refspec in do_update.sh (JTN-673)
  ([#452](https://github.com/jtn0123/InkyPi/pull/452),
  [`533d8d9`](https://github.com/jtn0123/InkyPi/commit/533d8d9487ae6b2ee20b669b7ca161a90ce23da4))

Older installers could pin remote.origin.fetch to a single-tag refspec (e.g.
  +refs/tags/v0.28.1:refs/tags/v0.28.1), causing `git fetch origin` to skip all branches. Before
  fetching, check whether the full branch glob is present; if not, wipe and re-add it so subsequent
  fetches pull all remote-tracking branches and tags correctly.

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>

- **release**: Regenerate uv.lock + keep lockfile in sync on release (JTN-655)
  ([#419](https://github.com/jtn0123/InkyPi/pull/419),
  [`3053b81`](https://github.com/jtn0123/InkyPi/commit/3053b81c26a62e448b7b792667a7de1d7afb4ed1))

- Regenerate uv.lock to match pyproject.toml 0.49.19 to unblock the Lockfile drift CI check that was
  failing on every new PR. - Extend semantic-release build_command to run `uv lock` alongside the
  VERSION write, and add uv.lock to `assets` so the refreshed lockfile is included in the release
  commit. This is the durable fix the JTN-655 description called out as item (2).

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- **security**: Close plugin_io xss + plugin path-injection (JTN-326)
  ([#431](https://github.com/jtn0123/InkyPi/pull/431),
  [`6e3011a`](https://github.com/jtn0123/InkyPi/commit/6e3011a2e28b5f4fc1d052a58f7e3a39688031c6))

* fix(security): close plugin_io xss + plugin path-injection (JTN-326)

Addresses two CodeQL alerts in the blueprint layer:

- py/reflective-xss at src/blueprints/plugin_io.py:103 — the 404 for a missing export instance
  interpolated the user-supplied instance name directly into the JSON error body. Return a generic
  "Plugin instance not found" message and log the tainted value server-side via sanitize_log_field,
  matching the PR #425/#426 pattern.

- py/path-injection at src/blueprints/plugin.py:142 — the /images/<id>/<path> route passed
  user-controlled plugin_id and filename straight through to send_from_directory. Follow the PR #424
  pattern: validate the plugin directory with utils.security_utils.validate_file_path (realpath +
  commonpath containment), then resolve each filename segment against os.listdir() so the value
  passed to send_from_directory is rebuilt from trusted filesystem data rather than raw URL input.
  Null-byte and absolute-path inputs are rejected up front.

Regression tests: - tests/test_plugin_io.py: XSS payload in ?instance= is not echoed, raw or
  HTML-escaped. - tests/integration/test_plugin_images_route.py: nested subpaths still serve, while
  traversal, unknown plugin, unknown file, and absolute/dot segments return 404/308 without escaping
  the plugin directory.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* fix(security): derive plugin image path from os.listdir (JTN-326)

Iteration on CodeQL taint-flow recognition: even with validate_file_path in place, CodeQL still
  reported py/path-injection on the image route because real_plugin_dir was traced back to the
  user-supplied plugin_id. Mirror the pattern used in history.py's sidecar cleanup (PR #424, commit
  3): resolve plugin_id and every filename segment by scanning a server-owned directory via
  os.listdir() and keeping the listdir-derived name for the final filesystem call.
  send_from_directory now only ever sees values that originated from os.listdir(), not from the URL.

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- **security**: Close py/path-injection in history blueprint (JTN-326)
  ([#424](https://github.com/jtn0123/InkyPi/pull/424),
  [`277dd77`](https://github.com/jtn0123/InkyPi/commit/277dd7718f4af3f10663ca423ea5b23136db1414))

* fix(security): validate user-supplied paths in history blueprint (JTN-326)

Route user-supplied filenames through utils.security_utils.validate_file_path so that CodeQL sees an
  os.path.realpath-based containment check in addition to the existing commonpath guard. This closes
  py/path-injection alerts on src/blueprints/history.py (lines 163, 342, 346, 347, 350, 351)
  reported by CodeQL. The helper resolves both the candidate and the allowed directory with
  realpath, rejecting .. traversal, absolute paths, and symlink escapes.

The delete sidecar path is now re-derived from the validated primary filename and run back through
  the same helper, so the secondary remove() call no longer consumes a path taint-traced from raw
  user input. Null-byte filenames and absolute paths are rejected up-front for defence in depth.

Adds integration tests covering .., absolute paths, null bytes, symlink escape, valid basenames, and
  sidecar removal on delete.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* fix(security): sanitize sidecar path through validate_file_path directly (JTN-326)

CodeQL did not recognise _resolve_history_path as a py/path-injection sanitiser; call
  validate_file_path directly on the candidate sidecar path so the sanitiser flows are picked up.

* fix(security): isolate sidecar remove() from user input via listdir match (JTN-326)

CodeQL's py/path-injection analysis still followed the taint flow through validate_file_path() for
  the sidecar removal. Rewrite the sidecar cleanup so the argument to os.remove() is constructed
  from os.listdir() output (not user-controlled) while still performing a realpath+commonpath
  containment check as defence-in-depth.

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- **security**: Close py/reflective-xss at main.py:280 (JTN-326)
  ([#428](https://github.com/jtn0123/InkyPi/pull/428),
  [`f57278a`](https://github.com/jtn0123/InkyPi/commit/f57278afffbfcebed4a9addff7e201ed201af055))

* fix(security): close py/reflective-xss at main.py:280 (JTN-326)

Remove reflection of user-supplied plugin IDs in /api/plugin_order error responses. Replace f-string
  interpolation of `invalid_ids` and `missing_ids` with generic messages. Although `json_error`
  returns application/json (minimising practical XSS risk), removing the reflection closes the
  CodeQL alert at its root and hardens against future content-type handling regressions — matching
  the pattern used in PRs #425/#426 for sibling blueprints.

Regression test: POST various XSS payloads as plugin IDs and assert they do not appear in the
  response body.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* test: update stale plugin_order error-message assertion (JTN-326)

Sibling test in test_blueprint_coverage.py still asserted the old interpolated error message. Update
  to match the new generic wording and add a negative assertion that the tainted value is not
  reflected.

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- **security**: Close py/reflective-xss in apikeys blueprint (JTN-326)
  ([#429](https://github.com/jtn0123/InkyPi/pull/429),
  [`b67d7da`](https://github.com/jtn0123/InkyPi/commit/b67d7dae5cb5809a8cf7b6e471645792a5c9e3df))

Replace f-string interpolation of user-controlled entry ``key``/``value`` in
  ``_validate_api_key_entry`` error messages with generic strings so attacker-controlled input is
  never echoed back in JSON error bodies.

Adds ``tests/integration/test_apikeys_xss.py`` which POSTs XSS payloads to ``/api-keys/save``
  (invalid key format, non-string value, control chars, bad keepExisting) and asserts the raw
  payload does not appear in the response body.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- **security**: Close py/reflective-xss in client_log blueprint (JTN-326)
  ([#427](https://github.com/jtn0123/InkyPi/pull/427),
  [`04fb615`](https://github.com/jtn0123/InkyPi/commit/04fb6155589a79fa7336a0ecf8fda580d7c40a3b))

The invalid-level branch of POST /api/client-log echoed the rejected ``level`` value back inside an
  f-string error message. CodeQL flagged this as reflective-xss (alerts on
  src/blueprints/client_log.py lines 58 and 62). Even though json_error emits application/json —
  which browsers do not render as HTML — removing the reflection closes the alert and hardens
  against future content-type handling changes.

Fix mirrors PR #425/#426 precedent: - Response body carries a generic "Invalid level: must be one of
  [...]" message with no taint. - Raw value is routed to logger.warning via sanitize_log_field so
  debugging information is preserved server-side.

Adds tests/integration/test_client_log_xss.py which posts six XSS payloads (<script>, img onerror,
  svg onload, javascript:, quote-break variants) and asserts the raw payload never appears in the
  JSON response body, the response is application/json, and the sanitized value is logged.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- **security**: Close py/reflective-xss in history blueprint (JTN-326)
  ([#430](https://github.com/jtn0123/InkyPi/pull/430),
  [`9a81ee1`](https://github.com/jtn0123/InkyPi/commit/9a81ee1072ae6000f94a51cd0bdc6893216048f1))

Closes CodeQL py/reflective-xss alerts in `src/blueprints/history.py` at lines 355, 359, 378, 382.
  These `return err` sites propagated a response object that was conditionally produced from the
  request body, so CodeQL's taint tracker tied the response back to user input even though the
  messages themselves were already module-level constants.

Refactor the two internal helpers (`_parse_filename_from_request`,
  `_validate_and_resolve_history_file`) to return plain string error-code sentinels instead of
  pre-built `json_error` responses. Callers map the code to a response via a new
  `_filename_error_response` helper whose every branch calls `json_error(...)` with a module-level
  constant string only. This mirrors the precedent from PRs #422/#425/#426: generic messages in the
  response body + tainted values logged server side via `sanitize_log_field`.

Add `tests/integration/test_history_xss.py` covering `/history/redisplay`, `/history/delete`, and
  `/history/image/<path>` with common XSS payloads (<script>, img onerror, svg onload, iframe
  srcdoc); asserts raw payload never reflects and responses carry application/json.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- **security**: Close py/reflective-xss in playlist blueprint (JTN-326)
  ([#425](https://github.com/jtn0123/InkyPi/pull/425),
  [`8f64e3f`](https://github.com/jtn0123/InkyPi/commit/8f64e3f461e6def62c992406aa57b4e915e2d1c7))

Replace f-string interpolation of user-controlled playlist names in error and success messages with
  generic messages. CodeQL flagged the tainted values flowing from request JSON / URL path
  parameters into response bodies via jsonify. Even though json_error/json_success emit
  application/json (which browsers do not render as HTML), removing the reflection closes the alerts
  and hardens against future content-type handling changes.

Sites closed (all in src/blueprints/playlist.py): - create_playlist duplicate-name error (was line
  533) - update_playlist not-found error (was line 640) - update_playlist success message (was lines
  678-679) - delete_playlist not-found error + success (was lines 692, 698) - reorder_plugins
  not-found error (was line 742) - display_next_in_playlist not-found error (was line 778) -
  playlist_eta not-found error (was line 820)

Adds tests/integration/test_playlist_xss.py which POSTs/PUTs/DELETEs/GETs crafted payloads
  (<script>, img onerror, svg onload, javascript:) to each affected route and asserts the raw
  payload is not echoed in the response body and that handler-produced responses carry
  application/json.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- **security**: Close reflected-xss + stack-trace exposure in plugin blueprint (JTN-326)
  ([#426](https://github.com/jtn0123/InkyPi/pull/426),
  [`a64d66d`](https://github.com/jtn0123/InkyPi/commit/a64d66d8a0ae678d018d5ab5f2b1bd7151b67608))

Addresses CodeQL alerts in src/blueprints/plugin.py:

- py/reflective-xss at lines 90, 304, 394, 398, 429, 756 — error messages previously interpolated
  user-controlled values (instance names, playlist names, URL path plugin_id) into the JSON body via
  sanitize_response_value(). Replace every site with a fully generic message and log the tainted
  value server-side via sanitize_log_field. - py/stack-trace-exposure at line 705 —
  _update_now_direct returned sanitize_response_value(str(e)) for plugin RuntimeErrors, echoing
  exception text to the client. Return a generic "An internal error occurred" message instead;
  logger.exception already captures the full traceback for operators.

This follows the same pattern as PR #422 (main blueprint). Regression tests assert that XSS payloads
  sent to each affected endpoint are not echoed in response bodies and that deliberate plugin
  RuntimeError exceptions return the generic message without leaking RuntimeError text.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- **security**: Redact secrets in weather plugin logs (JTN-326)
  ([#423](https://github.com/jtn0123/InkyPi/pull/423),
  [`c3a2946`](https://github.com/jtn0123/InkyPi/commit/c3a29469d9719e3bef4eb479137f6d413e125e96))

Wrap tainted log arguments in src/plugins/weather/weather_api.py (error response bodies at lines
  39/52/65) and src/plugins/weather/weather_data.py (timezone field at line 98) with the existing
  redact_secrets() helper from utils.logging_utils so any credential-shaped substring is masked
  before it reaches log handlers. Removes the prior lgtm[] suppression comments in favor of a real
  root-cause fix, closing CodeQL py/clear-text-logging-sensitive-data at those sites.

Adds tests/plugins/test_weather_redaction.py covering all four call sites: asserts the fake API key
  is absent from caplog output and that the ***REDACTED*** sentinel appears.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- **security**: Redact sensitive data in base_plugin logs (JTN-326)
  ([#421](https://github.com/jtn0123/InkyPi/pull/421),
  [`d8b508f`](https://github.com/jtn0123/InkyPi/commit/d8b508f07ff6eb4a4585220c0ed90ba1eb9e99f1))

* fix(security): redact sensitive fields before logging in base_plugin (JTN-326)

Addresses CodeQL py/clear-text-logging-sensitive-data alerts #16/#17 at
  src/plugins/base_plugin/base_plugin.py:201 and :214. Both call sites logged values derived from
  template_params (plugin settings), which CodeQL taints as potentially sensitive. Previous # lgtm
  suppressions were ignored by CodeQL.

Fix: route the logged values through a new public redact_secrets() helper in utils.logging_utils,
  which reuses the existing secret-pattern sanitizer already used by SecretRedactionFilter. The
  helper serves as an explicit sanitizer barrier for CodeQL and masks any api_key=, Bearer <token>,
  or 32+ hex secrets that happen to flow through CSS path or extra_css error paths. Also applied to
  the _build_css_files warning at line 187 which shares the same taint.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* chore: sync uv.lock with pyproject version bump

* test: cover base_plugin CSS exception paths; fix UnboundLocalError

Adds unit tests for the three redact_secrets() call sites in base_plugin (addresses Sonar new-code
  coverage gate) and fixes an UnboundLocalError where extra_css could be referenced in the except
  block before its assignment succeeded.

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- **security**: Suppress stack-trace exposure in main.py (JTN-326)
  ([#422](https://github.com/jtn0123/InkyPi/pull/422),
  [`cbaea8c`](https://github.com/jtn0123/InkyPi/commit/cbaea8c46d5b6c87c62882afbac9459342ee992d))

* fix(security): stop leaking exception detail from main blueprint error handlers (JTN-326)

CodeQL py/stack-trace-exposure flagged two sinks in src/blueprints/main.py where raw exception text
  was formatted into JSON error responses returned to the client (lines 344 and 360, plus the
  /refresh alias that reaches the same code via display_next at line 476).

Replace both with generic messages and rely on logger.exception() for server-side diagnostics.
  Update the two existing tests that asserted the leaky text, and add one regression test explicitly
  guarding that a secret RuntimeError message does not appear anywhere in the response body.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* chore: sync uv.lock with pyproject.toml version bump

Lockfile-drift CI check requires uv.lock's inkypi entry to match pyproject version 0.49.20.
  Pre-existing drift on main; regenerated via `uv lock`.

* refactor(main): narrow manual_update catch to RuntimeError

Addresses CodeRabbit review on #422. refresh_task.manual_update only raises RuntimeError when its
  queue is full; catching bare Exception here would mask unexpected failures as a 400 when they
  should fall through to the outer 500 handler.

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- **ui**: Close js/xss-through-dom on playlist.js (JTN-326)
  ([#420](https://github.com/jtn0123/InkyPi/pull/420),
  [`154310f`](https://github.com/jtn0123/InkyPi/commit/154310f5b7e2e9c59a3049722cc74e190197a03c))

* fix(ui): validate thumbnail URL before img.src assignment (JTN-326)

Closes CodeQL js/xss-through-dom alert on playlist.js:818. The previous `lgtm[...]` comment did not
  suppress the CodeQL alert. Instead of suppressing, rebuild a safe same-origin path from the
  DOM-sourced data-src attribute and reject anything else, giving CodeQL a recognizable sanitizer
  boundary.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* chore(lockfile): sync uv.lock with pyproject.toml v0.49.20

* fix(ui): use strict regex allowlist for thumbnail URL (JTN-326)

Replaces the URL-parse approach with a hard regex allowlist that CodeQL recognizes as a sanitizer
  barrier. Only matches site-relative paths under /static/ with a whitelisted character set, closing
  the js/xss-through-dom taint flow from img data-src to img.src.

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- **ui**: Hide raw plugin-instance keys in UI (JTN-618, JTN-619, JTN-620)
  ([#393](https://github.com/jtn0123/InkyPi/pull/393),
  [`a0f123b`](https://github.com/jtn0123/InkyPi/commit/a0f123bdb69a8cb81c51d46e14f4037a1595b69e))

* fix(ui): hide raw plugin-instance keys across dashboard, playlists, history (JTN-618, JTN-619,
  JTN-620)

Introduce a display-name layer for plugin instances so internal settings keys like
  `weather_saved_settings` no longer leak into user-facing UI surfaces:

- NOW SHOWING / Next up on the dashboard (JTN-618) - History "Source" metadata row (JTN-619) -
  Playlists list — visible labels, aria-labels, delete confirmation, thumbnail caption (JTN-620)

A new `utils.display_names` module centralises the fallback chain: 1. user-renamed instance name
  (unchanged) 2. plugin's `display_name` from plugin-info.json 3. humanised plugin id (e.g.
  `image_folder` -> "Image Folder") 4. raw instance name as last resort

Templates use new Jinja filters (`friendly_instance_label`, `instance_suffix_label`); the
  `/refresh-info` and `/next-up` endpoints annotate responses with `plugin_display_name`,
  `plugin_instance_label`, and `plugin_instance_is_auto` for the dashboard JS. Data attributes and
  element ids continue to carry the raw settings key because the JS layer needs it to make API calls
  against the filesystem settings file — but the raw key is no longer visible text or screen-reader
  content.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* a11y(playlist): add sr-only text to icon buttons to match aria-labels

Sonar S7927 flagged four icon-only buttons/links whose accessible name (aria-label) has no visible
  text counterpart. Add a hidden <span class="sr-only"> containing the same label so the accessible
  name is part of the visible label per WCAG 2.5.3.

* fix(playlist): show visible labels for plugin actions

* style: apply black formatting to test files

Fix CI lint failure by running black on the two test files modified during the main merge.

* fix(a11y): keep visible labels in accessible name for playlist actions

SonarCloud S7927: the accessible name must contain the visible label text. Replace aria-label (which
  overrides visible text entirely) with visually-hidden sr-only spans so the accessible name becomes
  "<visible label> <additional context>", e.g. "Edit plugin <name>". Keep the longer descriptive
  text as a title attribute for pointer hover tooltips.

* chore: sync uv.lock with pyproject.toml after main merge

Bump inkypi version in lockfile to 0.49.16 to match pyproject.toml pulled in during the main merge.

* chore: sync uv.lock with pyproject.toml

Bump inkypi lockfile version to 0.49.19 after second main merge.

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- **update**: Stop + disable inkypi.service before venv update (JTN-666)
  ([#449](https://github.com/jtn0123/InkyPi/pull/449),
  [`850e5d5`](https://github.com/jtn0123/InkyPi/commit/850e5d5e78a9bcb441e01231321566625e77d5c5))

update.sh never stopped the service before pip install, causing systemd to restart-loop the
  half-installed venv every 60s during updates. On a 512 MB Pi Zero 2 W this caused load-14 thrash
  and required physical power-cycling.

- Port stop_service() + show_loader() from install.sh (JTN-600 parity) - Call stop_service before
  apt/pip work; update_app_service re-enables at end - Add /var/lib/inkypi/.install-in-progress
  lockfile (JTN-607 parity) so even a manual `systemctl start` cannot bite mid-update; removed only
  on success - Fix zramswap OS-version guard to cover Bullseye/Bookworm/Trixie (11/12/13) - Guard
  setup_zramswap_service against Trixie's preinstalled zram-swap - Fix Trixie typo in get_os_version
  comment (Trixe -> Trixie) - Add tests covering all new invariants

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>

### Chores

- **deps-dev**: Bump pytest from 8.4.2 to 9.0.3 in /install
  ([#443](https://github.com/jtn0123/InkyPi/pull/443),
  [`785ead4`](https://github.com/jtn0123/InkyPi/commit/785ead49d5903d5212f577b30093bee06f6dd12c))

Bumps [pytest](https://github.com/pytest-dev/pytest) from 8.4.2 to 9.0.3. - [Release
  notes](https://github.com/pytest-dev/pytest/releases) -
  [Changelog](https://github.com/pytest-dev/pytest/blob/main/CHANGELOG.rst) -
  [Commits](https://github.com/pytest-dev/pytest/compare/8.4.2...9.0.3)

--- updated-dependencies: - dependency-name: pytest dependency-version: 9.0.3

dependency-type: direct:development ...

Signed-off-by: dependabot[bot] <support@github.com>

Co-authored-by: dependabot[bot] <49699333+dependabot[bot]@users.noreply.github.com>

- **lint**: Enable ruff DTZ and RET rule families
  ([#442](https://github.com/jtn0123/InkyPi/pull/442),
  [`3912dc1`](https://github.com/jtn0123/InkyPi/commit/3912dc1fae4f9aca82e6ab9534330b1016ca5f9e))

* chore(lint): enable ruff DTZ rule family and fix violations

Enable flake8-datetimez (DTZ) in ruff to catch timezone-naive datetime usage — a real bug class for
  the scheduler and history subsystems.

Production fixes (src/, scripts/): 21 violations replaced naive
  datetime.now()/today()/utcnow()/fromtimestamp() calls with tz-aware datetime.now(tz=UTC) (or
  device tz where one was already plumbed) and paired strptime() calls with an immediate
  .replace(tzinfo=...) or with a narrow # noqa where the parsed value is used only as a pure format
  validator (scheduled HH:MM times, YYYY-MM-DD date inputs).

Tests: DTZ is ignored under tests/** via per-file-ignores. The test suite leans heavily on naive
  fixture datetimes for deterministic clock stubs; enforcing tz-awareness there would bloat fixtures
  without exercising new behavior. Production paths still get full coverage.

One test (tests/unit/test_wpotd_unit.py) patched datetime with a stub that only implemented
  today()/strptime(); added a now() shim so the frozen-date fixture keeps working after
  wpotd._determine_date() switched to datetime.now(tz=UTC).

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* chore(lint): enable ruff RET rule family and fix violations

Enable flake8-return (RET) in ruff to clean up return-statement smells.

Breakdown: - 30 violations auto-fixed via ``ruff --fix`` (safe fixes): RET505
  (superfluous-else-return), RET501 (unnecessary-return-none), RET502 (implicit-return-value),
  RET506 (superfluous-else-raise). - 31 violations auto-fixed via ``ruff --fix --unsafe-fixes``: all
  RET504 (unnecessary-assign-before-return) plus three RET503 sites where a branch fell off the end
  of a function that otherwise returned a value.

Potentially-real return-path bugs surfaced: -
  ``src/refresh_task/task.py::RefreshTask.manual_update``: the ``else`` branch logged a warning but
  fell off the function implicitly returning ``None``. The caller expected ``RefreshResult | None``
  so the behavior is preserved after the fix, but the previous code was ambiguous about whether
  ``None`` was intentional. Now it's explicit. - ``tests/unit/test_security_csrf_rate_limit.py``:
  two Flask ``before_request`` handlers used bare ``return`` (implicit None) on the happy path and a
  value on error paths; made both explicit so the handler's return contract is unambiguous.

No runtime behavior changes — all fixes are semantic-preserving.

* chore(lint): drop redundant trailing return in build_settings_schema

SonarCloud python:S3626 flagged the bare `return` left behind by the RET autofix on
  `BasePlugin.build_settings_schema`. The function has no return type annotation and just falls
  through to implicit None, so dropping the statement entirely keeps the existing semantics while
  clearing the alert.

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- **quality**: Expand strict helper subset ([#438](https://github.com/jtn0123/InkyPi/pull/438),
  [`3714061`](https://github.com/jtn0123/InkyPi/commit/3714061a0ded42d6de284264af8f3b1de6151f1b))

- **quality**: Tighten helper typing and ruff rules
  ([#437](https://github.com/jtn0123/InkyPi/pull/437),
  [`cfe5e1c`](https://github.com/jtn0123/InkyPi/commit/cfe5e1c20fe3392a8a9c3c3b8772de7bfa13aa42))

- **quality**: Tighten refresh task typing ([#439](https://github.com/jtn0123/InkyPi/pull/439),
  [`4bbf1ad`](https://github.com/jtn0123/InkyPi/commit/4bbf1adce858f7b7762cf00c7559da0db973f7e2))

- **security**: Add dependency review, Semgrep, and Trivy
  ([#436](https://github.com/jtn0123/InkyPi/pull/436),
  [`26fd4d0`](https://github.com/jtn0123/InkyPi/commit/26fd4d056bf24a841a1960c5768ff7556a551b93))

* chore(security): add dependency review and code scanning workflows

* fix(ci): unblock security workflow checks

* fix(ci): address workflow review feedback

- **typing**: Split advisory mypy into src and tests passes
  ([#440](https://github.com/jtn0123/InkyPi/pull/440),
  [`b7769c1`](https://github.com/jtn0123/InkyPi/commit/b7769c1172ef2503f30690de586df9f0f930f8ca))

* chore(typing): split advisory mypy into src and tests passes

Split the advisory whole-codebase mypy invocation into two labeled runs (src/ and tests/) with
  separate error counts so that production-code type drift stays visible and we can continue
  ratcheting the strict subset. Both remain non-blocking; the strict subset is unchanged.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* refactor(lint): harden mypy error counting and dedup advisory runs

- count_mypy_errors now accepts exit code; distinguishes failed-without-summary from "0 errors"
  (addresses CodeRabbit major feedback) - extract run_advisory_mypy helper to remove duplication
  between src/ and tests/ advisory blocks (addresses CodeRabbit nitpick)

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- **typing**: Strictify src/model.py ([#445](https://github.com/jtn0123/InkyPi/pull/445),
  [`a6599e9`](https://github.com/jtn0123/InkyPi/commit/a6599e913c6735cff7ea265c1737f18d06f409ef))

* chore(typing): add src/model.py to blocking strict subset

Adds src/model.py to the CI-blocking --strict mypy subset. This commit only wires up the
  configuration and documentation — class-level type fixes land in subsequent commits. With 54
  errors in src/model.py, scripts/lint.sh will fail until the per-class commits land.

Refs JTN-663.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* chore(typing): strictify RefreshInfo in src/model.py

Adds type annotations to RefreshInfo.__init__, to_dict, from_dict, and get_refresh_datetime.
  Tightens the plugin_meta parameter to dict[str, Any] to close the generic type-arg complaint. No
  behavior change.

mypy --strict error count in src/model.py: 54 -> 49.

* chore(typing): strictify PluginInstance in src/model.py

Adds type annotations to PluginInstance.__init__, update, to_dict, from_dict, get_image_path, and
  get_latest_refresh_dt. Tightens _UPDATABLE to frozenset[str]. settings/refresh typed as dict[str,
  Any] matching their free-form persisted shape.

In should_refresh(), switches the scheduled lookup from .get("scheduled") to direct indexing since
  the 'scheduled' in self.refresh check immediately above guarantees presence. This keeps the
  strptime(...) argument type as Any (the dict's value type) rather than Any | None, satisfying
  --strict without changing behavior.

mypy --strict error count in src/model.py: 49 -> 39.

* chore(typing): strictify PlaylistManager in src/model.py

Adds type annotations to all PlaylistManager methods: __init__, get_playlist_names,
  add_default_playlist, find_plugin, determine_active_playlist, get_playlist,
  add_plugin_to_playlist, add_playlist, update_playlist, delete_playlist, to_dict, from_dict, and
  the static should_refresh helper. No behavior change.

Remaining "Call to untyped function" errors originate from PlaylistManager consuming not-yet-typed
  Playlist methods and will resolve in the final Playlist commit.

mypy --strict error count in src/model.py: 39 -> 30.

* chore(typing): strictify Playlist in src/model.py

Completes the strict-subset migration for src/model.py. Adds type annotations to all Playlist
  methods: __init__, is_active, add_plugin, update_plugin, delete_plugin, find_plugin,
  get_next_plugin, peek_next_plugin, get_next_eligible_plugin, peek_next_eligible_plugin,
  reorder_plugins, get_priority, get_time_range_minutes, to_dict, and from_dict.

Supporting changes: - Adds `from __future__ import annotations` so cross-class forward references
  (Playlist -> PluginInstance, PlaylistManager -> Playlist) resolve cleanly without quoted strings
  at each site. - to_dict(): replaces `getattr(self, "cycle_interval_seconds", None)` with a direct
  `self.cycle_interval_seconds is not None` check so mypy can narrow the int() argument. Behavior is
  equivalent because the attribute is unconditionally assigned in __init__. - from_dict(): drops the
  explicit `, None` default on data.get("current_plugin_index") since the dict value type now makes
  it redundant (SIM910). - src/utils/refresh_info.py: removes a now-redundant cast on
  RefreshInfo.to_dict() — the return type is concrete dict[str, Any] which is structurally identical
  to the RefreshInfoDict alias.

mypy --strict error count in src/model.py: 30 -> 0. Full file is now clean under the blocking strict
  subset.

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Continuous Integration

- **release**: Install uv in release workflow so semantic-release build_command can run `uv lock`
  ([`c99cd19`](https://github.com/jtn0123/InkyPi/commit/c99cd1934cc1627fd13c85ebb947858d165ce22f))

The release workflow's build_command (`printf ... > VERSION && uv lock`) failed with `uv: command
  not found` (exit 127), aborting the 0.50.0 release. Add astral-sh/setup-uv before semantic-release
  so uv is on PATH.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Features

- **schemas**: Dev-mode JSON response validator middleware
  ([#444](https://github.com/jtn0123/InkyPi/pull/444),
  [`f152b33`](https://github.com/jtn0123/InkyPi/commit/f152b33b81528dd9abf4208ae80835098e5ec243))

* refactor(schemas): extract validate_typeddict to src/schemas/validator.py

Move the hand-rolled TypedDict validator out of tests/contract/ so it can be reused by the upcoming
  dev-mode response-schema middleware (JTN-664). Zero behavior change; contract tests still drive
  through the same implementation.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* feat(schemas): add endpoint to TypedDict map

Introduce schemas.endpoint_map.ENDPOINT_SCHEMAS, which maps Flask endpoint names
  (blueprint.view_name) to the canonical response TypedDict declared in schemas.responses. Consumed
  by the upcoming dev-mode response-schema validator middleware (JTN-664); endpoint names were
  verified empirically against request.endpoint from the test client.

* feat(schemas): add dev-only response-schema validator middleware

Add app_setup.schema_validator.register(), an after_request hook that validates JSON bodies for
  endpoints listed in ENDPOINT_SCHEMAS against their TypedDict. Drift is logged at WARNING with
  endpoint + JSON path; the response is never mutated and the hook never raises.

Wired in create_app() behind DEV_MODE or INKYPI_STRICT_SCHEMAS=1 so production traffic is untouched
  by default. Closes the runtime half of JTN-664; the contract tests in tests/contract/ continue to
  catch drift at CI time.

* test(schemas): cover dev-mode schema validator middleware

Add tests/unit/test_schema_validator_middleware.py exercising:

* valid responses emit no WARNING from the validator logger * shape drift is logged with endpoint
  name + offending field path, without mutating the response * production mode (DEV_MODE=False,
  INKYPI_STRICT_SCHEMAS unset) skips registration entirely * INKYPI_STRICT_SCHEMAS=1 escape hatch
  forces registration

* fix(schemas): address review feedback on validator

- Refactor _check_type into per-origin helpers to drop cognitive complexity from 29 to under the
  SonarCloud S3776 threshold. - Drop raw mismatched values from error messages so WARNING-level
  schema-drift logs can't echo response payloads (CodeRabbit review). - Remove dead errs_per_arm
  accumulator in the union branch. - Drop the redundant first ENDPOINT_SCHEMAS monkeypatch in the
  middleware tests.

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Testing

- **contract**: Add JSON response shape contract tests
  ([#441](https://github.com/jtn0123/InkyPi/pull/441),
  [`4ce4a5c`](https://github.com/jtn0123/InkyPi/commit/4ce4a5c3f0e4f36420a560b2376a4a69bd693ead))

Add TypedDict response schemas in src/schemas/responses.py for 9 high-traffic JSON endpoints
  (version info, uptime, refresh-info, next-up, stats, health, isolation, history storage) and
  pytest contract tests in tests/contract/ that assert every response keeps its documented shape.

The hand-rolled validator walks TypedDict annotations (no pydantic dependency) and catches missing
  required keys plus wrong value types, including nested TypedDicts and list/dict generics.

Annotate the version_info and stats route producers with their TypedDict payloads so mypy can catch
  shape drift on the producing side as well.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- **plugins**: Anchor apod/wpotd date tests to UTC to fix boundary flakes
  ([#451](https://github.com/jtn0123/InkyPi/pull/451),
  [`cb1c4dc`](https://github.com/jtn0123/InkyPi/commit/cb1c4dcf4b0eadb4717c49eaa1ba883a37eccfde))

The APOD and WPOTD plugins resolve "today" via datetime.now(tz=UTC).date() (hardened in PR #442),
  but several tests were still comparing against the local date.today(). Near UTC midnight on
  non-UTC hosts, local and UTC dates diverge by one day, producing ~11 intermittent failures across:

- tests/plugins/test_apod_validation.py - tests/plugins/test_wpotd.py (test_determine_date_today) -
  tests/plugins/test_wpotd_validation.py

Fix: introduce a _today_utc() helper in each validation test file and replace date.today() /
  datetime.today() with datetime.now(tz=UTC).date() so tests reference the same UTC anchor the
  plugins use. No plugin bugs found; the plugins' tz handling is correct.

Verified clean under frozen UTC times 00:30, 04:30, 08:30, 12:00 and under TZ=UTC / Los_Angeles /
  Tokyo / Kiritimati (all 62 tests pass).

JTN-663

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.49.20 (2026-04-13)

### Bug Fixes

- **ui**: Add Plugins breadcrumb level and plugin chip context (JTN-637, JTN-638)
  ([#406](https://github.com/jtn0123/InkyPi/pull/406),
  [`64b8f23`](https://github.com/jtn0123/InkyPi/commit/64b8f23207cd6efb4f43109e51c75a89180a00a8))

* fix(ui): add Plugins breadcrumb level and plugin chip context (JTN-637, JTN-638)

- Plugin page breadcrumb now includes an intermediate "Plugins" link back to the home page plugin
  grid (#plugins-grid anchor), so users can jump between plugins without reaching for the browser
  back button. - Home page "now showing" chip now renders as "Showing: <plugin>" with a "Currently
  displayed plugin" tooltip, giving first-time users context for an otherwise bare plugin-name chip.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* chore(lockfile): sync uv.lock after rebase on main

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.49.19 (2026-04-13)

### Bug Fixes

- **auth**: Close open-redirect by rebuilding next URL from validated parts (JTN-654)
  ([#418](https://github.com/jtn0123/InkyPi/pull/418),
  [`1e40f3f`](https://github.com/jtn0123/InkyPi/commit/1e40f3f708347a31baa1575e6adb9b39617e61d4))

* fix(auth): close open-redirect by rebuilding next URL from validated parts (JTN-654)

CodeQL py/url-redirection (#55, #56) flagged `src/blueprints/auth.py:69` and `:96` because
  `_safe_next_url` previously returned the raw request string after a structural check — a
  validate-then-reuse pattern that CodeQL's taint tracker does not follow through.

Rewrite `_safe_next_url` so the returned value is reconstructed from validated structural
  components: reject control chars / protocol-relative / backslash-authority up front, run the value
  through `urlsplit`, then rebuild the path from `quote()`'d segments whose decoded form matches a
  strict allow-list regex. Optional query string is independently validated before being appended.
  The returned string has no taint-tracked data flow from the raw request attribute.

Add 17 parameterized regression tests covering unsafe inputs, safe paths, and safe query-string
  preservation.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* fix: sync uv.lock after rebase onto main

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.49.18 (2026-04-13)

### Bug Fixes

- **plugin**: Validate WPOTD custom date range at save time (JTN-651)
  ([#415](https://github.com/jtn0123/InkyPi/pull/415),
  [`72b5325`](https://github.com/jtn0123/InkyPi/commit/72b5325093682945c1333271d1bc1b20564fa2ca))

* fix(plugin): validate WPOTD custom date range at save time (JTN-651)

The Wikipedia POTD plugin mirrored JTN-379's pre-fix APOD behavior: `customDate` had no `min`/`max`
  attributes and no server-side `validate_settings` hook, so obviously out-of-range dates
  (1900-01-01, 2099-12-31) were persisted with a success toast and only failed later when Wikipedia
  returned no `Template:POTD/<date>`.

Reject dates outside [2007-01-01, today] at save time and advertise the same window via `min`/`max`
  on the date field.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* chore(deps): refresh uv lock metadata

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- **settings**: Validate timezone against IANA zones (JTN-650)
  ([#414](https://github.com/jtn0123/InkyPi/pull/414),
  [`efa956a`](https://github.com/jtn0123/InkyPi/commit/efa956aebc887fbaf31ba520de247dd8855843d9))

* fix(settings): validate timezone against IANA zones on save (JTN-650)

The Time Zone field on Settings → Device → Time & Locale previously only checked for presence. Any
  non-empty string (e.g. "NotATimezone") would persist to device.json, producing a misleading
  success toast and silently breaking downstream ZoneInfo lookups.

Now we validate timezoneName against zoneinfo.available_timezones() — the same set used to populate
  the input's datalist — and return a 422 validation_error with field=timezoneName when it fails, so
  the existing inline-field-error UI surfaces the issue next to the input.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* fix: sync uv lockfile

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.49.17 (2026-04-13)

### Bug Fixes

- **a11y**: Use human-readable timestamps in history aria-labels (JTN-642)
  ([#390](https://github.com/jtn0123/InkyPi/pull/390),
  [`65829b2`](https://github.com/jtn0123/InkyPi/commit/65829b21a8012695c491e5d9853cf09664ea5f33))

* fix(a11y): use human-readable timestamps in history aria-labels (JTN-642)

History action buttons (Display / Download / Delete) and thumbnail preview links previously
  announced the raw timestamp-based filename (e.g. "Delete display_20260408_200114.png"). Screen
  reader users had to hear that string 20+ times per page.

Swap the filename for the already-computed `img.mtime_str` (e.g. "Apr 08, 2026 08:01 PM") in each
  aria-label and the thumbnail img alt, so announcements read "Delete image from Apr 08, 2026 08:01
  PM". Filename is still available as the visible `history-name` text and the element `title`/`id`,
  so nothing functional changes.

Updated the existing aria-label integration test to assert the new human-readable prefix and
  explicitly reject the old filename-based labels.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* fix(a11y): drop redundant "image" from history thumb alt (JTN-642)

Sonar S6851: img alt already implies image, so "History image from …" becomes "History from …" to
  avoid redundancy while retaining the human-readable timestamp.

* test(history): harden aria-label assertions for filenames

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.49.16 (2026-04-13)

### Chores

- **lockfile**: Sync uv.lock after main merge
  ([`8b85e4a`](https://github.com/jtn0123/InkyPi/commit/8b85e4af18e0f568555efc465950821fa1dd831a))


## v0.49.15 (2026-04-12)

### Bug Fixes

- **plugin**: Use app-level toast for Update Preview validation errors (JTN-648)
  ([`ecc5e06`](https://github.com/jtn0123/InkyPi/commit/ecc5e06a444b1b731646745bbba5868efffcbb0d))

Empty required fields on Image URL and RSS Feed plugin pages showed the browser's native HTML5
  tooltip instead of the labelled app toast that JTN-378 introduced for Save Settings / Add to
  Playlist. Add `novalidate` to the settings form so the browser never surfaces its own bubble, and
  route the form's implicit Enter-key submit through the same validateAllInputsDetailed /
  buildValidationMessage / focusFirstInvalid helpers the Update Preview click path already uses.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Chores

- **deps**: Sync uv.lock inkypi version bump
  ([`e4962db`](https://github.com/jtn0123/InkyPi/commit/e4962dbcc738a2068cc4777d734e1c93bd7779ec))

Pick up the 0.49.6 -> 0.49.11 version drift that accumulated on main so the "Lockfile drift check"
  CI gate passes. No dependency changes.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.49.14 (2026-04-12)

### Bug Fixes

- Sync uv lockfile
  ([`7faaea3`](https://github.com/jtn0123/InkyPi/commit/7faaea3b39da206a4c00ccca498dee801cb9a47e))

- **csp**: Drop redundant UnicodeDecodeError in except clause (JTN-653)
  ([`4addf70`](https://github.com/jtn0123/InkyPi/commit/4addf7040846bc2536693e3256d757db5c5e0c75))

SonarCloud python:S5713 on src/blueprints/csp_report.py:68 flagged the `except (ValueError,
  UnicodeDecodeError)` tuple as redundant because UnicodeDecodeError is a subclass of ValueError and
  is therefore already caught by the base branch.

Drop UnicodeDecodeError from the tuple and leave a comment noting that non-UTF-8 payloads are still
  covered via inheritance. No behavior change; all 18 CSP-report tests (including malformed-JSON
  coverage) still pass.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- **security**: Clarify Sonar suppression comment
  ([`b82d0c0`](https://github.com/jtn0123/InkyPi/commit/b82d0c03f7fd2357b767c935a4ad5ed4e5d90dc7))

- **security**: Rebuild redirect URL to close CodeQL open-redirect alert (JTN-317)
  ([`5afe67f`](https://github.com/jtn0123/InkyPi/commit/5afe67f765b20f7e1c35d329443f8a09b07a99e7))

Validate-then-reuse of request.full_path left CodeQL py/url-redirection alert #52 open even after
  the host allow-list was added in PR #317: the taint flow from the untrusted Host header into
  redirect() was still present because the final URL was built by f-string concatenation with
  request.full_path.

Rebuild the redirect target from individually validated components using urlunsplit: hard-coded
  "https" scheme literal + allow-listed authority + re-quoted path + re-urlencoded query. This
  breaks the taint flow and matches the repo's established fix pattern for this rule.

Add regression tests covering: * path re-quoting (spaces survive as %20) * multi-value query
  round-trip * spoofed "@evil.com/path" in the request path cannot shift the authority in the
  Location header.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Chores

- **lockfile**: Sync uv.lock with project version
  ([`d74bb9e`](https://github.com/jtn0123/InkyPi/commit/d74bb9e9c68b1b55f8ebcc821287b6e38d9b3af5))


## v0.49.13 (2026-04-12)

### Bug Fixes

- **playlist**: Add confirmation + success toast to Display Next (JTN-630)
  ([`b076fc3`](https://github.com/jtn0123/InkyPi/commit/b076fc3113ffc514e494384aa02aa177b208b6c6))

On a Pi Zero 2 W, the per-playlist "Display Next" button used to fire immediately with no
  confirmation and no visible success feedback, leaving the user unsure whether the command was
  sent. Now:

- Click opens a confirmation modal that names the playlist being advanced. - Confirming fires the
  existing request and surfaces a success toast ("Display updated — refreshing…") before the page
  reloads. - Cancel/backdrop-click/Escape all close the modal; a11y attributes and wiring follow the
  Delete Playlist / Delete Instance modal pattern.

Tests: - tests/static/test_display_next_confirmation.py — 8 new assertions covering the modal
  markup, a11y attrs, click-handler rewire, success toast, cancel button, and escape/backdrop
  registration. - tests/integration/test_playlist_empty_state.py — updated to match on
  `.run-next-btn` instead of the literal "Display Next" string, since the confirm modal now renders
  as page chrome even for empty playlists.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Testing

- **a11y**: Guard Style accordion chevron flip (JTN-643)
  ([#413](https://github.com/jtn0123/InkyPi/pull/413),
  [`1768b29`](https://github.com/jtn0123/InkyPi/commit/1768b29c746f5542d08f6158ce0a0df3f762200a))

PR #389 (JTN-623) already fixed the "Style ▼ stays ▼" behaviour on plugin pages by letting CSS
  rotate `.collapsible-icon` 180deg off `[aria-expanded="true"]`. The existing coverage asserted the
  CSS rule is bundled and that JS toggles aria-expanded, but nothing exercised the live browser path
  on a plugin page or pinned down the hidden prerequisite — `transform` only applies if the chevron
  span is a non-inline box.

Add two regression guards so the "stuck ▼" symptom cannot silently return: - Static test:
  `.collapsible-icon` must keep `float: right` (or declare an explicit non-inline `display:`) so the
  rotate transform actually renders. Dropping the float without a replacement would visually revert
  the fix while aria-expanded still flipped. - E2E test: on `/plugin/weather`, clicking the Style
  header flips `aria-expanded` to `true` AND computes `transform: matrix(-1,0,0,-1,0,0)` on the
  chevron, and clears both on a second click.

Closes JTN-643.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.49.12 (2026-04-12)

### Bug Fixes

- **a11y**: Wire Escape + focus management into settings reboot/shutdown modals (JTN-652)
  ([`a6ef079`](https://github.com/jtn0123/InkyPi/commit/a6ef079f6862e4115ea1d613e4ca2d907a9db2b7))

Sibling of JTN-461/463 in a different code path. The reboot and shutdown confirmation modals added
  in JTN-621 skipped the modal-a11y pattern used everywhere else in the app: Escape did nothing,
  focus never moved into the modal on open, never returned to the trigger on close, and the is-open
  class + body.modal-open backdrop lock were never applied.

This aligns the /settings device-action modals with the scheduleModal, playlist modals, image
  lightbox, and history modals — so users can actually cancel a destructive action with the
  keyboard.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- **deps**: Refresh uv lockfile
  ([`a6668a9`](https://github.com/jtn0123/InkyPi/commit/a6668a9d8b3d1120848a2bfe50f9fab87ec0f878))

- **history**: Polish pass — source fallback, metric tooltip, danger zone
  ([#409](https://github.com/jtn0123/InkyPi/pull/409),
  [`8a53afc`](https://github.com/jtn0123/InkyPi/commit/8a53afc71b61f4c7d50a2275dc25d07a831afddd))

JTN-626: Metric chips (Request / Generate / Preprocess / Display) now carry both a title tooltip and
  a descriptive aria-label so users can tell what "2622 ms" actually measures. The strip is labelled
  as a region with a screen-reader-only describedby paragraph.

JTN-631: Every history entry now renders a Source line for consistency.

Entries without sidecar provenance show "Source: Unknown" in a muted italic style with a tooltip
  explaining older entries predate source tracking.

JTN-649: The reset-cache section is now a proper danger zone: a horizontal divider separates it from
  the grid, a red "Danger zone" pill label sits above the heading, the heading uses the error color,
  padding and border are beefed up, and on narrow viewports it stacks vertically with a full-width
  Clear All button. The section is exposed as a region landmark for assistive tech.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.49.11 (2026-04-12)

### Bug Fixes

- **ui**: Restore main nav on 404 page (JTN-641)
  ([#399](https://github.com/jtn0123/InkyPi/pull/399),
  [`ab28051`](https://github.com/jtn0123/InkyPi/commit/ab280516a6c4b331e548f63e4882c3529cb37885))

* fix(ui): restore main nav on 404 page (JTN-641)

Users hitting a broken URL saw only Home and theme toggle, with no path to History, Playlists, or
  Settings. Add the standard site navigation <nav> block to the 404 template so every broken URL
  remains a discovery entry point, matching the header used on inky/playlist/settings pages.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* a11y: address Sonar S7927 on 404 nav links (JTN-641)

SonarCloud flagged the three icon-only nav links (History/Playlists/ Settings) because their
  accessible name came from aria-label only, not from visible content. Replace aria-label with a
  visually-hidden span inside the link so the accessible name is derived from
  (screen-reader-visible) content, and add title attributes for sighted hover tooltips. No visual
  regression.

* chore(deps): sync uv.lock to pyproject 0.49.6

Resolves Lockfile drift check — pyproject was bumped to 0.49.6 on main but uv.lock still pinned
  0.49.5.

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.49.10 (2026-04-12)

### Bug Fixes

- **plugin**: Show empty-state in progress block on Weather and AI Image (JTN-634)
  ([#403](https://github.com/jtn0123/InkyPi/pull/403),
  [`9be4e5a`](https://github.com/jtn0123/InkyPi/commit/9be4e5a936e712e73d7f665e609345530f27d1ff))

PR #377 (JTN-347/348/331/332) made the Last progress button work on Clock, To-Do, Calendar, and
  Screenshot by clearing the inline display:none left by progress.stop(). Weather and AI Image still
  appeared to "show no feedback" because their required settings fields (latitude / longitude /
  textPrompt) frequently fail client-side validation, so the very first Update Now click
  short-circuits in handleAction before sendForm runs and no progress snapshot is ever persisted. A
  later click of Last progress then hit the no-data branch, which surfaced only a transient toast —
  easy to miss and not anchored to the button.

Move the empty-state message inside the requestProgress block itself: the button now always reveals
  a clearly visible panel, either with real snapshot data or with "No progress data yet — run Update
  Now to see progress here." The progress bar is reset to 0% in the empty state so the UI doesn't
  imply a completed run. Adds regression tests that confirm the button and block render on
  /plugin/weather and /plugin/ai_image and that the no-data branch unhides the progress block.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.49.9 (2026-04-12)

### Bug Fixes

- **ai_text**: Show input AND output token prices in model labels (JTN-635)
  ([#400](https://github.com/jtn0123/InkyPi/pull/400),
  [`bfe3b2d`](https://github.com/jtn0123/InkyPi/commit/bfe3b2d6192f9ad2e1597060ebf0466716d76f91))

Model dropdown labels only displayed input token pricing (e.g. "$2.50/1M in"), which is misleading
  because output tokens are typically 3-4x the input rate for LLMs. Users evaluating cost were
  under-estimating actual spend.

Updated labels to the compact form "$X in / $Y out per 1M" for all OpenAI and Google models, added a
  pricing reference comment pointing at provider pricing pages, and expanded the callout to note
  that output tokens cost more than input. Added a regression test that parses the schema and
  asserts every model label exposes both prices.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.49.8 (2026-04-12)

### Bug Fixes

- **image_upload,image_folder**: Pre-select Background Fill radio in draft (JTN-632)
  ([#402](https://github.com/jtn0123/InkyPi/pull/402),
  [`fce6102`](https://github.com/jtn0123/InkyPi/commit/fce610288cc10f4e7f1907f7dd85d94c7685b3dc))

The Background Fill radio group rendered two inputs both marked `checked` on /plugin/image_upload
  and /plugin/image_folder because the legacy Style collapsible in plugin.html hardcodes a second
  `<input ... name="backgroundOption" value="color" checked>`. The schema-driven Blur radio was
  correctly checked, but the hidden Style radio added a competing checked state, so browsers treated
  the group as indeterminate and users could save without picking a background fill option.

Both plugins already expose their own schema-driven Background Fill field and do not consume any of
  the Style collapsible fields (Frame, Margins, Text Color, etc.), so disabling `style_settings` is
  safe and removes the name collision. With Style off, the schema's `default="blur"` pre-selects
  exactly one radio in DRAFT mode, matching the `generate_image` fallback.

Tests: - Schema assertion that `backgroundOption.default == "blur"` for both plugins. - Integration
  regression: GET /plugin/image_upload and /plugin/image_folder in DRAFT mode, parse all
  `name="backgroundOption"` inputs, assert exactly one is `checked` and that its value is `blur`.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.49.7 (2026-04-12)

### Bug Fixes

- **playlist**: Use native time input for arbitrary HH:MM schedules (JTN-647)
  ([#401](https://github.com/jtn0123/InkyPi/pull/401),
  [`41e974c`](https://github.com/jtn0123/InkyPi/commit/41e974c0a16c829f3f3f1c130799052d8cc78522))

Replace the 15-minute-increment <select> dropdowns for playlist start/end time with <input
  type="time" step="60">. Users can now schedule times like 09:05 or 07:10, which the backend
  already accepts. The edit modal normalises the legacy "24:00" sentinel to "23:59" so native time
  inputs can display it.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.49.6 (2026-04-12)

### Bug Fixes

- **release**: Stop shipping literal {version} placeholder in VERSION (JTN-624)
  ([#391](https://github.com/jtn0123/InkyPi/pull/391),
  [`20dc553`](https://github.com/jtn0123/InkyPi/commit/20dc55369a6fa4d8b43a4f7057115146a8a9a7f9))

* fix(release): stop shipping literal {version} placeholder in VERSION (JTN-624)

The Settings -> Updates tab was reporting `INSTALLED: 0.1.0` while the latest release was 0.47.0.
  Root causes:

1. `pyproject.toml` had `build_command = "echo '{version}' > VERSION"`, but python-semantic-release
  does NOT expand `{version}` inside shell build commands — it passes the literal string through.
  Every release since #349 therefore wrote the seven characters `{version}` to VERSION. Switch to
  `printf '%s\n' "$NEW_VERSION" > VERSION` so the release pipeline uses the env var PSR actually
  exports. 2. `version_toml` only pointed at `tool.semantic_release.version`, so the canonical
  PEP-621 `[project].version` was never bumped and has been drifting since the uv-lock migration
  (JTN-616). Add `project.version` to `version_toml` so every release rewrites both keys. 3.
  `_read_version()` / `_read_app_version()` surfaced the literal `{version}` string (or `0.1.0`) to
  the UI verbatim. Add a pyproject.toml fallback and treat `{version}`, `0.1.0`, and empty strings
  as "no usable VERSION file" so the UI still shows a real version even if a future release
  regresses VERSION again.

Also bump VERSION and `[project].version` to 0.47.0 so the checked-in state matches the latest tag.

Regression tests:

- `test_version_file_on_disk_is_not_placeholder` — fails CI if VERSION ever contains `{version}`,
  `0.1.0`, or a non-semver string. -
  `test_pyproject_project_version_matches_semantic_release_version` — fails CI if the two
  version_toml targets drift. - `test_read_version_placeholder_falls_back_to_pyproject` — covers the
  runtime fallback path so a broken VERSION doesn't break the UI.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* chore(deps): regenerate uv.lock after version bump (JTN-624)

The [project].version bump in pyproject.toml shifted the lockfile's project version metadata.
  Regenerate with `uv lock` to clear the advisory Lockfile drift check.

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.49.5 (2026-04-12)

### Bug Fixes

- **plugin**: Surface DRAFT state when Add to Playlist is clicked (JTN-633)
  ([#398](https://github.com/jtn0123/InkyPi/pull/398),
  [`c3986b2`](https://github.com/jtn0123/InkyPi/commit/c3986b2474ee16422d0b6d20420137e2700a0648))

* fix(plugin): surface DRAFT state when Add to Playlist is clicked (JTN-633)

Add a defensive direct click listener on the DRAFT-state Add-to-Playlist button so it can never
  silently no-op. If the scheduling modal is missing the user now sees a clear toast/response modal
  telling them to refresh. Also clarify the inline help text to explain that current settings are
  captured when the playlist entry is saved.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* test: skip new Playwright test module when browser unavailable (JTN-633)

Register test_plugin_draft_add_to_playlist.py in UI_BROWSER_TESTS so pytest_ignore_collect skips it
  on the CI pytest runners that don't install Playwright Chromium, matching the existing
  test_plugin_add_to_playlist_ui.py treatment.

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.49.4 (2026-04-12)

### Bug Fixes

- **plugin**: Warn on API Required navigation when form has unsaved changes (JTN-629)
  ([#397](https://github.com/jtn0123/InkyPi/pull/397),
  [`0db65fb`](https://github.com/jtn0123/InkyPi/commit/0db65fb9216ff33941a7c67b16b538d28cc5ce13))

On plugin pages that require an API key (AI Image, GitHub, etc.), the "API Required" chip in the
  header was a plain <a> link that immediately navigated to /settings/api-keys. A user who had typed
  a long prompt and tapped the chip lost all of it without warning.

The chip is now intercepted by plugin_page.js. On first page load the settings form is snapshotted;
  on chip click, we compare the current form state to the snapshot. If the form is dirty, a
  confirmation modal opens warning about discarding unsaved changes — matching the Reboot/Shutdown
  modal UX introduced in JTN-621. If the form is clean, navigation proceeds normally. The confirm
  button is still an <a href> to the API keys page so no-JS fallback keeps working.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.49.3 (2026-04-12)

### Bug Fixes

- **ui**: Small polish pass — pagination, jargon, 24:00, colons (JTN-636, JTN-640, JTN-639, JTN-645)
  ([#396](https://github.com/jtn0123/InkyPi/pull/396),
  [`c165085`](https://github.com/jtn0123/InkyPi/commit/c165085eb55597f9168da1b555b66347ae45fc30))

- JTN-636: Disabled Previous/Next pagination controls now use a dedicated .pagination-disabled class
  (reduced opacity, cursor:default, pointer-events: none, aria-disabled=true) instead of an inline
  style, so page 1 Previous is visually distinguishable from the active Next link. - JTN-640:
  Playlists header chip now reads "Refresh interval" instead of the internal jargon "Device
  cadence". - JTN-639: Playlists whose range spans the full day (00:00 to 24:00/23:59) now render as
  "All day" instead of the non-standard "24:00" end time. - JTN-645: Image Processing slider labels
  (Saturation, Contrast, Sharpness, Brightness, Inky Driver Saturation) no longer end with trailing
  colons, matching the rest of the settings form.

Adds regression assertions in tests/integration/test_history.py, test_playlist_routes.py, and
  test_settings_routes.py.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.49.2 (2026-04-12)

### Bug Fixes

- **plugin**: Hide raw slug subtitle and explain DRAFT badge (JTN-622, JTN-644)
  ([#395](https://github.com/jtn0123/InkyPi/pull/395),
  [`52b5b38`](https://github.com/jtn0123/InkyPi/commit/52b5b38b8a38987783ff3d28c74eea25cba64093))

- Remove the visible plugin.id subtitle from the plugin page header by default. The raw filesystem
  slug (ai_image, clock, weather, ...) is an internal identifier and has no meaning to end users.
  Kept behind ?debug=1 for diagnostics. - Add title and aria-describedby to the Draft status chip so
  users (and screen readers) learn what the badge means and how to clear it. - Extend the
  status_chip macro to accept optional title / describedby args. - Add integration tests covering
  both fixes.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.49.1 (2026-04-12)

### Bug Fixes

- **settings**: Render System Health and Isolation Summary as tables (JTN-646)
  ([#394](https://github.com/jtn0123/InkyPi/pull/394),
  [`0d7b5fb`](https://github.com/jtn0123/InkyPi/commit/0d7b5fbe2f1daebf14d1fea47c8cfe88bdb3af7d))

Extends JTN-384 to the remaining Diagnostics panels. System Health, Plugin Health, and Isolation
  Summary no longer dump raw JSON.stringify output; instead they render as labeled .bench-table
  tables with human-friendly units (percent, uptime) and a "No plugins isolated" empty state.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.49.0 (2026-04-12)

### Features

- **plugin**: Use HTMX for plugin settings form submission (JTN-506)
  ([#383](https://github.com/jtn0123/InkyPi/pull/383),
  [`c6ad4a8`](https://github.com/jtn0123/InkyPi/commit/c6ad4a84eeed03ec08b721a336e95221702ad39f))

* feat(plugin): use HTMX for plugin settings form submission (JTN-506)

The base template already loads HTMX on every page, but nothing on the plugin page was using it —
  the settings form was posting via fetch() and rendering errors through a toast modal. Phase 1 of
  JTN-506 migrates the "Save Settings" button to an HTMX-driven flow so validation errors swap
  inline and successes fire an HX-Trigger-backed toast, while legacy JSON clients still see JSON
  (gated on the HX-Request header).

Progressive enhancement: the form now carries action/method so it stays valid HTML, and an error
  container (#plugin-form-errors) hosts the swap target. update_now, update_instance, and
  add_to_playlist keep using the existing sendForm path; those are deferred to follow-up PRs.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* test(plugin): add coverage for _is_htmx_request RuntimeError + error Content-Type (JTN-506)

Push SonarCloud new_coverage past the 80% gate. Covers two previously unexercised branches: -
  `_is_htmx_request()` called outside a Flask request context - Internal error response sets
  `text/html` content-type (sep from body check)

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.48.1 (2026-04-12)

### Bug Fixes

- **a11y**: Toggle aria-expanded on Style collapsible (JTN-623)
  ([#389](https://github.com/jtn0123/InkyPi/pull/389),
  [`de67e2c`](https://github.com/jtn0123/InkyPi/commit/de67e2ccd3e4e1d7f78ddd7195d5c721ee977629))

The Style accordion on plugin pages (and any `[data-collapsible-toggle]` button) could fall out of
  sync with screen readers: aria-expanded stayed "false" after clicking, and the chevron never
  flipped direction.

Two fixes:

1. Move the click handler into a document-level delegated listener in ui_helpers.js so every
  collapsible button reliably toggles aria-expanded, even if a page-specific binding is missed or
  runs before the button exists. Removed the now-redundant per-button bindings in plugin_page.js and
  settings_page.js.

2. Let CSS own the chevron direction. The JS used to flip textContent between ▼ and ▲ while
  _toggle.css also rotated the icon 180deg via `[aria-expanded="true"]` — the two cancelled out and
  the chevron appeared unchanged. Dropped the textContent swap; the static ▼ character now rotates
  in CSS based on aria-expanded.

Updated test_collapsible_icon_direction.py to cover the new contract: aria-expanded must flip, CSS
  must own the chevron rotation, and a delegated click handler must exist.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- **settings**: Add confirmation dialog to Reboot/Shutdown buttons (JTN-621)
  ([#388](https://github.com/jtn0123/InkyPi/pull/388),
  [`f391829`](https://github.com/jtn0123/InkyPi/commit/f391829d66630b6faf4f9b5b0aabd50ae399b0de))

An accidental tap on the Reboot or Shutdown button in Settings -> Updates immediately severed the UI
  on a Pi Zero 2 W, with no physical recovery path until a power cycle. Both actions now open a
  confirmation modal that clearly states the UI will be unavailable and that physical access is
  required to recover if anything goes wrong.

The click handlers for #rebootBtn and #shutdownBtn now open the respective modal instead of invoking
  handleShutdown directly. The modal's confirm button is what actually fires the action, matching
  the Clear All History pattern.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.48.0 (2026-04-12)

### Bug Fixes

- **security**: Exempt /api/csp-report from CSRF and return 400 on malformed JSON (JTN-628)
  ([#387](https://github.com/jtn0123/InkyPi/pull/387),
  [`500627b`](https://github.com/jtn0123/InkyPi/commit/500627b8711ece5f78fb4c007e52f26624828339))

Browsers never attach a CSRF token or session cookie to automatic CSP violation reports, so POST
  /api/csp-report was being rejected by the global CSRF middleware with HTTP 403. All violation
  reports were silently discarded, and the dev console filled with 403s.

Changes: - Add /api/csp-report to _CSRF_EXEMPT_PATHS and _RATE_EXEMPT so the endpoint's own 20/min
  per-IP sliding-window limiter is authoritative. - Return HTTP 400 (application/json) on malformed
  JSON bodies instead of swallowing them as 204 — surfaces parser bugs and matches RFC expectations.
  The response never echoes the request body. - Cap the accepted body at 16 KiB; oversized payloads
  are discarded silently (204) so the limiter can't be fingerprinted. - Extend tests: integration
  cases proving POST without CSRF succeeds, malformed JSON yields 400, oversized bodies are dropped,
  and application/reports+json (Reporting API v2) is accepted.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- **settings**: Add /settings/diagnostics route to prevent 404 (JTN-627)
  ([#386](https://github.com/jtn0123/InkyPi/pull/386),
  [`4de5857`](https://github.com/jtn0123/InkyPi/commit/4de585728113ab9bc4b92db4a042996c353299a4))

Users who bookmark or follow direct links to /settings/diagnostics previously received a 404.
  Diagnostics is an accordion embedded in the main /settings page rather than a standalone sub-page,
  so add a small redirect route that points visitors at the accordion anchor instead.

- Add GET /settings/diagnostics -> 302 /settings#diagnostics - Add id="diagnostics" anchor target
  next to the Diagnostics accordion so the fragment actually resolves to the right section - Cover
  with integration tests asserting 302 target, no 404, and that following the redirect renders the
  settings page with the anchor

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Features

- **ui**: Unify loading/error states with FormState manager (JTN-505)
  ([#382](https://github.com/jtn0123/InkyPi/pull/382),
  [`7c686ec`](https://github.com/jtn0123/InkyPi/commit/7c686ec2c10cd03c5eaf31d72596cb89d0b94fd2))

* feat(ui): unify loading/error states with FormState manager (JTN-505)

Adds src/static/scripts/form_state.js — a framework-free manager that wires any <form
  data-form-state> element with a uniform submit lifecycle:

- Disables the submit button and shows its .btn-spinner while in flight - Flips aria-busy="true" on
  the form during the request - setFieldError / setFieldErrors render inline next to fields via
  existing aria-describedby validation-message regions; first invalid field receives focus -
  clearErrors resets all inline validation-messages and aria-invalid flags at the start of every
  submit

Settings form and playlist schedule/refresh forms now opt in through data-form-state +
  data-form-state-submit attributes. settings_page.js handleAction and playlist.js
  createPlaylist/updatePlaylist route their save requests through FormState.run() so duplicate
  submissions are no longer possible, and server-side field_errors (when present) surface inline
  instead of only in a dismissible toast.

form_state.js is added to the build_assets.py bundle manifest and to base.html so it loads on every
  page.

Plugin form (plugin.html / plugin_form.js) is intentionally untouched — that path is being migrated
  to HTMX in JTN-506.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* test(a11y): update image preview modal tests for modal() macro

Plugin.html was refactored in JTN-503 to render #imagePreviewModal via the shared modal() macro,
  which emits aria-labelledby and the <h2> title element at render time. The existing text-based
  tests were asserting against the raw plugin.html source and no longer matched. Tests now accept
  either path (direct literal or macro invocation) and also verify the macro itself emits the
  required aria-labelledby + h2 id.

* test(a11y): accept macro-generated title id and quote style

The modal() macro emits aria-labelledby="<id>Title", so invoking it as modal('imagePreviewModal',
  ...) renders id='imagePreviewModalTitle' (not the original hand-written 'imagePreviewTitle').
  Update the rendered-page assertion to accept either id and either quote style, preserving a11y
  coverage without coupling to a specific naming convention.

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Refactoring

- **api**: Standardize JSON response envelope across blueprints (JTN-500)
  ([#384](https://github.com/jtn0123/InkyPi/pull/384),
  [`2122e21`](https://github.com/jtn0123/InkyPi/commit/2122e21b357d0454fcf8d4714ca945fbd041b22e))

Migrates success-shaped ``jsonify({"success": True, ...})`` calls and the remaining raw-error
  payloads in blueprints to the central ``json_success`` / ``json_error`` helpers so every JSON
  response carries the canonical envelope (``success``, ``message`` / ``error``, ``request_id``,
  ...).

- Document the canonical envelope in ``src/utils/http_utils.py`` - Migrate ``main.py``,
  ``plugin.py``, ``stats.py``, and the ``settings/_*`` blueprints to ``json_success`` /
  ``json_error`` - Add ``tests/contracts/test_json_envelope.py`` covering success, error, and
  ``X-Request-Id`` round-trip envelopes for a representative set of routes - Keep legacy top-level
  ``running``/``unit`` fields on the 409 duplicate-update response for backward compatibility with
  existing clients/tests

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Testing

- **plugin_registry**: Use sys.executable for pyenv compatibility (JTN-625)
  ([#385](https://github.com/jtn0123/InkyPi/pull/385),
  [`8c7c146`](https://github.com/jtn0123/InkyPi/commit/8c7c14675d71b96ddeb4321f23c5ce7bd8e45976))

The two shell-based tests (test_venv_shell_sets_pythonpath and test_plugin_import_with_pythonpath)
  invoked a bare `python` via bash, which failed on macOS local dev when a pyenv shim pointed at an
  unavailable interpreter ("pyenv: python: command not found"). The tests were only meant to
  exercise PYTHONPATH propagation, not PATH resolution for `python`.

Switch the in-shell interpreter invocation to the currently-running sys.executable (shell-escaped
  via shlex.quote). Behavior under test is unchanged; the tests now run regardless of whether
  `python` is on PATH.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.47.0 (2026-04-12)

### Bug Fixes

- **ui**: Prevent dashboard header title clipping on narrow viewports (JTN-340)
  ([#381](https://github.com/jtn0123/InkyPi/pull/381),
  [`ef7a092`](https://github.com/jtn0123/InkyPi/commit/ef7a09278ec64126cad6c80473b6d47d7f794be8))

At widths below ~430px the `.app-title` in the dashboard header could render clipped on the right
  because it had no overflow handling and `.title-container` used the default `min-width: auto` on a
  flex child, preventing the title from shrinking below its intrinsic content width.

- `.app-title`: add `min-width: 0`, `overflow: hidden`, `text-overflow: ellipsis`, and `white-space:
  nowrap` so long device names truncate cleanly instead of overflowing the header. -
  `.title-container`: add `min-width: 0` and `flex: 1 1 auto` so the title is allowed to shrink and
  trigger ellipsis truncation. - `inky.html`: expose the full device name via `title="{{ config.name
  }}"` on the `<h1>` so hover tooltips and screen readers still surface the complete name even when
  visually truncated. - Add `tests/static/test_mobile_header.py` asserting the CSS rules and
  template attribute remain in place as a regression guard.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Features

- **deps**: Migrate dependency locking to uv lock (JTN-616)
  ([#380](https://github.com/jtn0123/InkyPi/pull/380),
  [`0364094`](https://github.com/jtn0123/InkyPi/commit/0364094f2dfabcaa2bce14620bf38a6855a0521e))

Replace pip-compile with `uv lock` + `uv export` to eliminate chronic lockfile-drift CI failures.
  The universal cross-platform lockfile resolves every supported platform (Linux
  x86_64/aarch64/armv7l/armv6l + macOS arm64/x86_64) from a single resolution, which fixes all three
  root causes of the historical drift:

- Python version coupling (3.13 vs 3.12) - sys_platform-gated packages (cysystemd, inky, gpiod, ...)
  - Multi-arch wheel hash coverage (gpiod arm64/armhf/aarch64)

Changes: - pyproject.toml: add [project.dependencies] mirroring install/requirements.in plus
  [tool.uv] required-environments for universal resolution - uv.lock: new universal lockfile
  committed - install/requirements.txt: regenerated via `uv export` (hash-pinned, markers
  preserved). install.sh continues to use --require-hashes so JTN-516 supply-chain integrity is
  preserved - scripts/check_requirements_drift.sh: swap pip-compile for `uv lock --check` + `uv
  export` diff - .github/workflows/ci.yml: lockfile-drift job installs uv instead of pip-tools. Kept
  advisory (continue-on-error: true) for this PR; follow-up will promote to required once stable on
  main - docs/dependency_locking.md: document the new workflow and rationale

Phase 3 (retiring install/requirements.in and migrating install/requirements-dev.txt) is deferred
  per the ticket spec.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Refactoring

- **refresh_task**: Decouple subprocess worker from Config via RefreshContext (JTN-495)
  ([#378](https://github.com/jtn0123/InkyPi/pull/378),
  [`3f08eb8`](https://github.com/jtn0123/InkyPi/commit/3f08eb891c6b7050109da01a1b408eaa375afd77))

Introduce a pickle-safe RefreshContext dataclass that snapshots the minimal Config fields needed by
  the subprocess worker. The subprocess now receives RefreshContext instead of the full Config
  object, eliminating the fragile pickle-and-reconstruct dance in _restore_child_config. Legacy
  Config objects are still accepted for backwards compatibility.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Testing

- **snapshots**: Expand baselines to clock, todo_list, image_upload, image_folder (JTN-611)
  ([#373](https://github.com/jtn0123/InkyPi/pull/373),
  [`231e51d`](https://github.com/jtn0123/InkyPi/commit/231e51d83ba114f7fa5fb91184f48b8da3e951ed))

* test(snapshots): expand baselines to clock, image_upload, image_folder (JTN-611)

Add snapshot tests for four more deterministic plugins: - clock: Digital and Word faces with frozen
  datetime (PIL-only, no browser) - todo_list: two-list disc style (browser-gated) - image_upload:
  color-padded fixture PNG (PIL-only) - image_folder: crop-to-fit fixture PNG (PIL-only)

PIL-only tests run in every CI job; browser-gated tests run only when REQUIRE_BROWSER_SMOKE=1 is
  set. Baselines committed alongside the tests.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* test(snapshots): add missing todo_list/two_lists_disc baseline

The browser smoke CI job failed because the snapshot baseline for the todo_list plugin was never
  generated. Generate it so the assertion in test_snapshot_todo_list can find the expected digest.

* fix(snapshots): use CI-generated hash for todo_list baseline

The todo_list snapshot was generated on macOS but CI runs on Ubuntu, producing a different pixel
  hash due to font-rendering differences. Update the sha256 digest to match the CI (Ubuntu +
  Playwright Chromium) rendering, consistent with how other browser-based baselines were
  established.

* test(a11y): update image-preview modal tests for JTN-503 macro refactor

The plugin.html image preview modal is now rendered via the modal() macro introduced in JTN-503
  (#375). The macro derives the heading id from the modal id (imagePreviewModal ->
  imagePreviewModalTitle), replacing the previous hard-coded imagePreviewTitle. Update the three
  tests that asserted the old literal id and replace the raw-template checks with assertions on the
  macro definition itself so the harness survives future templating changes.

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.46.3 (2026-04-12)

### Bug Fixes

- Restore API Keys page button actions (JTN-325, JTN-324, JTN-323)
  ([#379](https://github.com/jtn0123/InkyPi/pull/379),
  [`81f1431`](https://github.com/jtn0123/InkyPi/commit/81f14316dad0a5bf209e4c8359804696209e2dfd))

The inline <script> boot block that initialised the API Keys page JS was silently blocked by CSP
  `script-src 'self'` in production, making all buttons (Delete, Add, preset chips) no-ops.

Move the boot config to data-* attributes on the .api-keys-frame container and have api_keys_page.js
  self-initialise from the DOM, eliminating the need for any inline JavaScript.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.46.2 (2026-04-12)

### Bug Fixes

- Show visible feedback for plugin progress buttons (JTN-347, JTN-348, JTN-331, JTN-332)
  ([#377](https://github.com/jtn0123/InkyPi/pull/377),
  [`4e611be`](https://github.com/jtn0123/InkyPi/commit/4e611beb5f251fa7cab84a927ee6750d38da3eeb))

progress.stop() in plugin_form.js set style.display='none' on the progress block, but
  showLastProgress() in plugin_page.js only removed the HTML hidden attribute — it never cleared the
  inline display:none. The block stayed invisible even when unhidden, producing a silent no-op on
  Clock, To-Do List, Calendar, and Screenshot plugin pages.

Fix: clear inline style.display in showLastProgress and stop using style.display='none' in
  progress.stop() (rely on hidden attribute instead).

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Refactoring

- **config**: Extract paths and refresh_info modules (JTN-494)
  ([#376](https://github.com/jtn0123/InkyPi/pull/376),
  [`ba13405`](https://github.com/jtn0123/InkyPi/commit/ba13405768ca4c3f81e189d9d2801284081c2b56))

Extract path constants and runtime resolution into utils/paths.py and refresh-info loading into
  utils/refresh_info.py, reducing Config from a god-object to a thin facade that delegates to
  focused modules.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.46.1 (2026-04-12)

### Bug Fixes

- **release**: Keep VERSION in sync with semantic-release
  ([#349](https://github.com/jtn0123/InkyPi/pull/349),
  [`a894af0`](https://github.com/jtn0123/InkyPi/commit/a894af06841ea4bd49e79a3c84d9445729d388b2))

Add VERSION to semantic_release assets so the build_command output ("echo '{version}' > VERSION") is
  committed alongside the version bump. Previously build_command wrote the file but it was never
  staged, leaving VERSION stuck at 0.1.0.

Also make SBOM tag selection deterministic: instead of reading the stale VERSION file, discover the
  release tag via `git tag --points-at HEAD` piped through `sort -V | tail -n1`.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.46.0 (2026-04-12)

### Features

- **templates**: Add Jinja2 component-macro library (JTN-503)
  ([#375](https://github.com/jtn0123/InkyPi/pull/375),
  [`4a910d4`](https://github.com/jtn0123/InkyPi/commit/4a910d4122bef0f9918d0cb0067e4993f1f72aad))

* feat(templates): add Jinja2 component-macro library with a11y (JTN-503)

Create reusable macros (button, form_field, modal, status_chip, card) in macros/components.html with
  built-in ARIA attributes. Adopt status_chip and modal in plugin.html as proof-of-concept. Add 24
  unit tests asserting required a11y attributes on every macro.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* fix(macros): guard attrs against None/false values (CR feedback)

Skip rendering attrs entries where the value is None or false to prevent emitting attributes like
  data-x="None".

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.45.2 (2026-04-12)

### Bug Fixes

- **history**: Wire up Next/Prev pagination links (JTN-330)
  ([#366](https://github.com/jtn0123/InkyPi/pull/366),
  [`ba4900d`](https://github.com/jtn0123/InkyPi/commit/ba4900d28e41e59a4760ffe433a0ec38546e5106))

The HTMX pagination swap replaced #history-grid-container but did not scroll the viewport back to
  the grid, so the user saw the same bottom-of-page content after clicking Next. Add
  show:#history-grid-container:top to hx-swap so the browser scrolls the grid into view after each
  page change. Also listen for htmx:afterSettle to re-bind image skeleton handlers on newly swapped
  content.

Four tests added: - HTMX partial returns disjoint images for page 1 vs page 2 - Pagination links
  include the show: scroll modifier - HTMX partial omits the full page shell - JS contains
  htmx:afterSettle listener for image rebinding

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- **settings**: Return specific error for out-of-range cycle interval (JTN-351)
  ([#363](https://github.com/jtn0123/InkyPi/pull/363),
  [`c722324`](https://github.com/jtn0123/InkyPi/commit/c7223244ed4931427212f725900e9bb371e1ed6a))

Replace the generic "Refresh interval is required" error that was returned for negative/non-numeric
  interval values with distinct messages: - Missing/empty → "Refresh interval is required" -
  Non-numeric → "Refresh interval must be a number" - Below minimum → "Refresh interval must be at
  least 1"

The root cause was `str.isnumeric()` returning False for negative numbers (due to the minus sign),
  causing them to fall into the "is required" branch instead of a range-check branch.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- **settings**: Show inline result for Check for Updates (JTN-352)
  ([#374](https://github.com/jtn0123/InkyPi/pull/374),
  [`9a54748`](https://github.com/jtn0123/InkyPi/commit/9a547482898d5893076df5553552f9eb2bd129e6))

Add spinner and disabled state to the Check for Updates button during the version check fetch. The
  badge already displays status text (Checking.../Up to date/Update available/Check failed) but the
  button itself had no loading indicator, making it appear unresponsive.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Refactoring

- **css**: Split components into per-component partials (JTN-504)
  ([#369](https://github.com/jtn0123/InkyPi/pull/369),
  [`543b259`](https://github.com/jtn0123/InkyPi/commit/543b259b555573db652bc3f84675cf5839fba585))

* refactor(css): split _components.css into per-component partials (JTN-504)

Reshape CSS partials from page-oriented to component-oriented: - Split _components.css into
  _button.css, _form.css, _toggle.css - Colocate responsive @media blocks with their component
  definitions - Centralize breakpoint reference values in _tokens.css - Add .stylelintrc.json for
  advisory linting (max specificity, no dupes) - Update _imports.css manifest with new partial order
  - Rebuilt main.css (selector coverage identical: 824 selectors)

No CSS class names changed — templates are unaffected.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* fix(test): read main.css instead of _components.css for .image-option check (JTN-504)

The CSS reshape moved `.image-option` from `_components.css` to `_form.css`. The test was hardcoded
  to read `_components.css`, causing CI failure. Read the built `main.css` instead so the test is
  resilient to future partial reorganizations.

* style: black format test file

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.45.1 (2026-04-12)

### Bug Fixes

- **settings**: Render benchmark results as a labeled table (JTN-384)
  ([#372](https://github.com/jtn0123/InkyPi/pull/372),
  [`b86dde4`](https://github.com/jtn0123/InkyPi/commit/b86dde4f58a185c79744d1beb2c64edd12e9564b))

Replace raw JSON.stringify output in the Diagnostics benchmark panel with formatted HTML tables.
  Summary shows Stage/p50/p95 columns with human-readable labels (Request, Generate, Preprocess,
  Display). Plugin averages render as a separate table. Null values display as em-dash instead of
  literal "null". Adds bench-table CSS and 8 static tests.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.45.0 (2026-04-12)

### Bug Fixes

- Restore History page button actions (JTN-330, JTN-329, JTN-328, JTN-327)
  ([#370](https://github.com/jtn0123/InkyPi/pull/370),
  [`0a383e2`](https://github.com/jtn0123/InkyPi/commit/0a383e2bd773bd07b21deaebf2f0a4a67786a26a))

Move endpoint URLs from an inline JS object literal to data attributes on a hidden DOM element. The
  DOMContentLoaded callback now reads from the data attributes and guards against missing globals,
  making the boot sequence resilient to CSP script-src restrictions and load-order edge cases that
  silently broke Display, Delete, Clear All, and pagination buttons during dogfood testing.

Add 28 regression tests covering all four button flows plus the new boot-config wiring.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Features

- **a11y**: Wire up axe-core scans in Playwright tests (JTN-507)
  ([#368](https://github.com/jtn0123/InkyPi/pull/368),
  [`e9f93e2`](https://github.com/jtn0123/InkyPi/commit/e9f93e2f97853b730b92c8e3a75b5f49a5f9941a))

Add test_axe_a11y.py with parametrized axe-core scans for all 6 main routes. Known pre-existing
  violations are whitelisted with TODO(JTN-xxx) tickets. Add aria-live regions for inline form error
  announcements in plugin.html, settings.html, and response_modal.html. Register the new test file
  in conftest A11Y_BROWSER_TESTS for proper SKIP_BROWSER gating.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- **ci**: Benchmark regression gate (JTN-511) ([#367](https://github.com/jtn0123/InkyPi/pull/367),
  [`6f65b38`](https://github.com/jtn0123/InkyPi/commit/6f65b38072b59706ce137b504436c0b3055c2a3f))

* feat(ci): add benchmark regression gate with stored baseline (JTN-511)

The CI benchmark step now compares current results against a committed baseline
  (tests/benchmarks/baseline.json) and fails when any benchmark regresses beyond +15% (configurable
  via BENCHMARK_THRESHOLD_PCT). Removes stale JTN-293 "future work" comments.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* chore: strip baseline.json to essential stats only (JTN-511)

* fix(ci): use CI-cached baseline for cross-platform accuracy (JTN-511)

The benchmark gate now uses a GitHub Actions cache for the baseline instead of comparing against the
  repo-committed local baseline. On main branch pushes the current run becomes the new baseline.
  First run is informational only (non-blocking) until the cache is populated.

* fix: fail gate when baseline benchmark is missing from current run (JTN-511)

Addresses CodeRabbit feedback — a removed/skipped/renamed benchmark should not silently pass the
  regression gate.

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.44.0 (2026-04-12)

### Features

- **api**: Add async job queue for non-blocking plugin renders (JTN-497)
  ([#371](https://github.com/jtn0123/InkyPi/pull/371),
  [`0f98521`](https://github.com/jtn0123/InkyPi/commit/0f98521931fb00461151398f1ea27e737e4e1685))

Plugin renders now run in a ThreadPoolExecutor-backed job queue when the client sends X-Async: true.
  POST /update_now returns 202 with a job_id; the frontend polls GET /api/job/<id> until done/error.
  The sync path is preserved for backward compatibility. Config.write_config was already
  mutex-protected via _config_lock.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.43.11 (2026-04-12)

### Bug Fixes

- **api-keys**: Wire + Add API Key button into event delegation (JTN-323)
  ([#365](https://github.com/jtn0123/InkyPi/pull/365),
  [`8e39fa5`](https://github.com/jtn0123/InkyPi/commit/8e39fa55e4d985d412965c0042c26743b136a650))

The button relied solely on a direct addEventListener in init(), making it fragile to script-load
  timing. Add data-api-action="add-row" to the button and handle it in the delegation handler,
  consistent with the preset chips and delete buttons.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.43.10 (2026-04-12)

### Bug Fixes

- **settings**: Surface isolation endpoint errors in the UI (JTN-385)
  ([#364](https://github.com/jtn0123/InkyPi/pull/364),
  [`9089b5a`](https://github.com/jtn0123/InkyPi/commit/9089b5a5487c36ea4ee82b4f11c3069ddc1fd4ff))

The backend already validates unknown plugin IDs and returns 422, but the frontend isolatePlugin()
  and unIsolatePlugin() functions were fire-and-forget — they never checked the response status.
  After the POST/DELETE, the code immediately called refreshIsolation() (a GET), which returned
  {"isolated_plugins": [], "success": true}, making it appear the operation succeeded.

Add proper error handling: check resp.ok, parse the error message, and show it via
  showResponseModal() consistent with the rest of the settings page.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Continuous Integration

- **snapshots**: Upload actual PNGs as artifacts on snapshot failure (JTN-612)
  ([#362](https://github.com/jtn0123/InkyPi/pull/362),
  [`3264771`](https://github.com/jtn0123/InkyPi/commit/3264771b1fe49945bc0f45752f16a140a6835d5a))

When a snapshot test detects a digest mismatch, the actual PNG is now saved to
  tests/snapshots/actual/<plugin>/<case>.png so CI can upload it as a GitHub Actions artifact for
  visual inspection. The AssertionError message includes a hint pointing reviewers to the artifact.

- snapshot_helper: save actual PNG on mismatch, enrich error message - ci.yml: add upload-artifact
  step (if: failure()) in browser-smoke job - .gitignore: exclude tests/snapshots/actual/ - New
  test: verify actual PNG is written on mismatch and not on match

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.43.9 (2026-04-12)

### Bug Fixes

- **api-keys**: Add id/name/aria-label to row inputs (JTN-383)
  ([#361](https://github.com/jtn0123/InkyPi/pull/361),
  [`c87957a`](https://github.com/jtn0123/InkyPi/commit/c87957a25997e4ba05419c43dd94410f1110b188))

JS-built rows in api_keys_page.js addRow() had no id, name, or aria-label on their inputs, so screen
  readers could not distinguish rows and browser autofill could not target them. Server-rendered
  rows had aria-label but no id/name. Both paths are now consistent:

- addRow() assigns a unique `apikey-name-new-N` / `apikey-value-new-N` id+name pair and sets an
  initial aria-label on the key input. - updateRowAriaLabels() keeps the value input and delete
  button's aria-labels in sync with the current key name via an input listener. - Server-rendered
  rows get `apikey-name-{loop.index0}` / `apikey-value-{loop.index0}` id+name pairs.

JTN-382 (password masking) already shipped — this change intentionally does not touch the masking
  behavior.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- **playlist**: Validate refresh_settings on update_plugin_instance (JTN-381)
  ([#359](https://github.com/jtn0123/InkyPi/pull/359),
  [`fc10e53`](https://github.com/jtn0123/InkyPi/commit/fc10e531572a341f1ad9a049be68b76190e58786))

/update_plugin_instance previously accepted the frontend's JSON-stringified `refresh_settings` form
  field, stored it verbatim in plugin_instance.settings, returned 200 success, and never touched
  plugin_instance.refresh. Out-of-range intervals (e.g. 5000) silently reverted on reload while the
  modal showed a green success toast.

- Rename the existing `_validate_plugin_refresh_settings` helper in playlist.py to drop the leading
  underscore so it can be reused. - In update_plugin_instance, pop `refresh_settings` out of the
  form dict, JSON-parse it with a 400 on malformed input, route it through the shared validator, and
  persist the validated refresh config inside the same atomic update that writes plugin_settings. -
  Range (1–999) and unit (minute/hour/day) checks are identical to the add_plugin path, so the
  behavior stays consistent.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.43.8 (2026-04-12)

### Bug Fixes

- **ui**: Name the failing field in form validation toasts (JTN-378)
  ([#357](https://github.com/jtn0123/InkyPi/pull/357),
  [`0026cb5`](https://github.com/jtn0123/InkyPi/commit/0026cb540f8e2ccf4c0302f8d2e75e1eccb5fe54))

Replace the generic "N field(s) need fixing before saving" toast with a label-specific message like
  "Prompt is required". The shared FormValidator helper now exposes validateAllInputsDetailed,
  getInputLabel, buildValidationMessage, and focusFirstInvalid. Label lookup prefers data-label,
  then aria-label, then label[for=id] text, then a wrapping label, then a titlecased name, then
  "This field". Selector also now includes textarea[required] which was previously missed, so AI
  Text (and other required textareas) are validated too.

plugin_page.js's Save Settings and Add to Playlist paths route through the new helpers so every
  plugin benefits, not just AI Image.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.43.7 (2026-04-12)

### Bug Fixes

- **settings**: Make sticky Save button selector match real DOM (JTN-572)
  ([#351](https://github.com/jtn0123/InkyPi/pull/351),
  [`08f6777`](https://github.com/jtn0123/InkyPi/commit/08f67778f1d62d090c7e45dc83cd772c87ade5be))

The JTN-599 short-viewport sticky rule used `.settings-panel > .buttons-container` (child
  combinator), but the settings DOM nests buttons-container inside .settings-console-main, so the
  selector matched zero elements and the Save button still disappeared below the fold. Switch to a
  descendant combinator so the sticky rule actually engages on /settings, and add a regression test
  guarding against the broken `>` selector creeping back.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.43.6 (2026-04-11)

### Bug Fixes

- **install**: Anchor update_vendors.sh cwd to repo root (JTN-615)
  ([#360](https://github.com/jtn0123/InkyPi/pull/360),
  [`49c3754`](https://github.com/jtn0123/InkyPi/commit/49c3754a882a3c618b4e6806c50ccc40c4e83ef3))

* fix(install): anchor update_vendors.sh cwd to repo root (JTN-615)

The ci.yml install-matrix job has been failing on every PR and on main since the JTN-534 exit-code
  propagation landed because install.sh calls update_vendors.sh with `install/` as cwd, and the
  script's vendor destinations are specified relative to the repo root (e.g.
  `src/static/styles/select2.min.css`). Curl then tries to write to `$PWD/src/static/...` which
  resolves to `install/src/static/...` — a non-existent directory — and every download fails with
  `curl: (23) Failure writing output to destination`. Six retries all hit the same disk-write error
  and install.sh exits 1.

Before JTN-534 the curl failure was silently ignored, masking the always-broken relative-path
  assumption.

Fix: derive the script's own location via BASH_SOURCE and cd to the repo root at the top of
  update_vendors.sh, so relative destinations always resolve correctly regardless of caller cwd.
  Mirrors the pattern already used by other project scripts.

Adds a regression test class in tests/unit/test_install_scripts.py that asserts (1) the
  cwd-anchoring is present, (2) vendor destinations remain repo-root-relative, and (3) install.sh
  still invokes the script. Verified the fix locally by running update_vendors.sh from
  /tmp/vendor-sim and confirming all five vendor files download successfully.

Unblocks the ci-gate meta-check that every recent PR has been admin-overriding.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* fix(ci): unblock install-matrix — verifier imports + Dockerfile venv/GPG (JTN-615)

The initial JTN-615 fix (commit b666630) correctly anchored update_vendors.sh cwd and got
  `install.sh` past the vendor-download step. Three downstream bugs then surfaced on first CI run:

**Bug A — verifier uses non-existent waitress.__version__**

`ci_install_matrix_verify.sh` Phase 3 ran `python -c "import flask, waitress, PIL; print(...
  waitress.__version__ ...)"`. Flask 3.2 deprecates `flask.__version__` and waitress has never
  exposed a module-level `__version__`, so on bookworm (where uv successfully installed every
  package) the verifier crashed with `AttributeError: module 'waitress' has no attribute
  '__version__'` and incorrectly reported "one or more required packages missing". Rewrite the check
  to use `importlib.metadata.version()` so it's resilient to package-level attribute churn — the
  point of Phase 3 is "can the venv import these modules", a version print is nice-to-have.

**Bug B — bullseye apt rejects `[trusted=yes]` Pi OS repo**

Bullseye's older apt does not honour `[trusted=yes]` the same way bookworm/trixie do when the repo
  emits a NO_PUBKEY InRelease signature. Net effect: `apt-get install chromium-headless-shell
  liblgpio-dev` returned "Unable to locate package", the batch install failed, and **python3-venv
  was silently never installed** — so `python3 -m venv` later bombed inside install.sh with
  "ensurepip is not available". Fetch the real archive.raspberrypi.com GPG key via curl and use
  `[signed-by=...]` so all three codenames behave consistently.

**Bug C — defensive venv bootstrap**

Pre-install `python3 python3-venv python3-pip` in the Dockerfile before install.sh runs. If the Pi
  OS apt layer ever has issues again, the venv creation path still works — separating "container
  bootstrap" from "install.sh happy path" so regressions fail loudly in a known place.

install.sh's own silent-exit-code bug (it ran the pip fallback after ensurepip died with "No module
  named pip" and still exited 0) is tracked separately as a hardening follow-up — fixing the two
  root causes above should take install-matrix green without needing that change.

Updated regression test in TestInstallMatrixWorkflow to assert the new distribution-name-based check
  rather than pinning the old import-statement string.

* fix(ci): revert GPG keyring approach, add C build deps (JTN-615)

The previous commit (c49e525) tried to replace `[trusted=yes]` on the Pi OS apt repo with a
  `[signed-by=...]` keyring approach. That broke the image build entirely on trixie: trixie's sqv
  (sequoia gpg) policy rejects the Raspberry Pi archive key because it carries SHA1 self-signatures,
  which stopped being accepted on 2026-02-01. Even after manually importing the key, sqv refuses to
  bind it and apt-get update exits non-zero. `[trusted=yes]` is the documented workaround for
  exactly this case — restore it and expand the header comment so a future refactor doesn't make the
  same mistake.

Separately, the install-matrix job has never successfully built arm64 C-extension requirements
  inside the Docker image because the Dockerfile doesn't install a C toolchain or the native header
  packages that scripts/test_install_memcap.sh already lists:

gcc, python3-dev, libsystemd-dev, libopenjp2-7-dev, libfreetype6-dev, libheif-dev, swig

Add them here so the two smoke paths can't diverge on build-time deps. Observed on bookworm with the
  previous commit:

error: command 'aarch64-linux-gnu-gcc' failed: No such file or directory

during uv's `Building spidev==3.8` / `Building sgmllib3k==1.0.0` step. Adding gcc + python3-dev
  unblocks the same pip/uv install path that runs on a real Pi (real Pi OS Lite doesn't ship gcc
  either, but the pre-built wheelhouse from JTN-604 papers over that on-device; CI runs with
  INKYPI_SKIP_WHEELHOUSE=1 so it must build from source).

* ci(install-matrix): drop bullseye — Python 3.9 can't install py311 reqs (JTN-615)

Bookworm + trixie now pass the install-matrix after the previous commits (update_vendors.sh cwd fix,
  verifier importlib.metadata, C toolchain in Dockerfile). Bullseye still fails at the uv
  dependency-resolve step:

Because the current Python version (3.9.2) does not satisfy Python>=3.10 and anyio==4.13.0 depends
  on Python>=3.10, we can conclude that anyio==4.13.0 cannot be used. And because you require
  anyio==4.13.0, we can conclude that your requirements are unsatisfiable.

Debian 11 (bullseye) ships python3=3.9.2 in its main archive. InkyPi's requirements.txt pins several
  packages that hard-require Python>=3.10 (anyio is the first to trip the resolver; openai,
  google-genai, pydantic etc. all follow). pyproject.toml also sets `target-version = "py311"` in
  both the black and ruff configs, so bullseye has never been a real install target.

The install-matrix job only appeared to cover bullseye historically because install.sh silently
  swallowed the uv/pip failures (tracked as a follow-up hardening item — install.sh needs to
  propagate dep-install exit codes loudly so this class of regression fails fast in one place).

Drop bullseye from the ci.yml install-matrix to reflect reality. The standalone Install matrix
  (arm64 e2e) workflow still exercises bullseye via scripts/test_install_memcap.sh, which uses a
  python:3.12-slim base image and therefore isn't blocked by the codename's own Python version. That
  job can't catch install.sh misbehavior that's specific to Debian 11, but neither can the broken
  version that existed before this PR — it was failing on every run — so nothing is lost.

Updated TestInstallMatrixWorkflow's matrix assertion to match the new {bookworm, trixie} set, with a
  comment explaining why bullseye is absent.

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.43.5 (2026-04-11)

### Bug Fixes

- **playlist**: Label wrap-past-midnight ranges as "(next day)" (JTN-353)
  ([#354](https://github.com/jtn0123/InkyPi/pull/354),
  [`b5d0408`](https://github.com/jtn0123/InkyPi/commit/b5d04081c9b80f7492b3bafa55de6c9a00b4b759))

New Playlist silently accepted reverse times (e.g. 20:00 - 08:00), and the listing showed them
  identically to a normal 09:00 - 17:00 range, so users couldn't tell if the range wrapped past
  midnight. The model's Playlist.is_active already supports wraparound (start > end), so the
  ergonomic fix is to keep accepting these ranges (night shifts are a real use case) and label them
  in the UI.

Append "(next day)" next to the summary when end_time < start_time so the intent is visible at a
  glance. Regression tests cover acceptance of the reverse range and presence/absence of the wrap
  label.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.43.4 (2026-04-11)

### Bug Fixes

- **rss**: Validate feedUrl at save time (JTN-380)
  ([#356](https://github.com/jtn0123/InkyPi/pull/356),
  [`4356389`](https://github.com/jtn0123/InkyPi/commit/4356389d61f9d20a4b66354291eb612e0f93ea9f))

The RSS Feed plugin previously persisted any string in feedUrl, even values like
  "definitely-not-a-feed-url". This adds both client-side and server-side validation matching the
  JTN-357 Calendar pattern:

- Schema field now uses type="url" with pattern="https?://.+" and required, so the browser rejects
  obviously bad values before submit. - New validate_settings() parses the URL and rejects anything
  without an http(s) scheme or with an empty netloc. Empty/whitespace/None values return a
  "required" error; other bad values return a "not valid" error with the offending input. - Adds 16
  unit/integration tests covering accepted URLs, rejected schemes (javascript/file/ftp/webcal),
  empty/whitespace/None, and the rendered settings template.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.43.3 (2026-04-11)

### Bug Fixes

- **ai_image**: Use textarea for prompt input (JTN-377)
  ([#352](https://github.com/jtn0123/InkyPi/pull/352),
  [`a6dfb1b`](https://github.com/jtn0123/InkyPi/commit/a6dfb1b0ce797212e85ea0b9bbddff8c6a8edfd0))

The AI Image plugin rendered its prompt field as a single-line <input>, so long prompts were clipped
  in the UI. Match the AI Text plugin by switching the textPrompt schema field to type "textarea"
  with rows=4, preserving placeholder, required, and label. Form submission is unchanged since the
  field name stays the same.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- **history**: Clamp ?page upper bound to total_pages (JTN-359)
  ([#353](https://github.com/jtn0123/InkyPi/pull/353),
  [`ac3e72c`](https://github.com/jtn0123/InkyPi/commit/ac3e72c6afc3964feeae190f1a38236a02c73aaa))

GET /history?page=99999 rendered "Page 99999 of 4" over an empty grid because the page parameter
  only had a lower-bound clamp (max(page, 1)). Add the symmetric upper-bound clamp so out-of-range
  page values snap to the last valid page. Handle the empty-history case (total_pages == 1, page
  stays at 1) so the empty-state template still renders.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.43.2 (2026-04-11)

### Bug Fixes

- **ui**: Keep Show Logs action above mobile safe area (JTN-339)
  ([#355](https://github.com/jtn0123/InkyPi/pull/355),
  [`758d185`](https://github.com/jtn0123/InkyPi/commit/758d18544bc257a0915351eab0189e25bedf3a46))

On narrow mobile viewports the floating "Show Logs" button on /settings sat at a flat 16px from the
  bottom edge, which placed it underneath the iOS home indicator and Safari's bottom toolbar — users
  could not tap it without scrolling. The settings page also had no bottom padding to keep in-flow
  content from being covered by the fixed button.

- Use max(16px, env(safe-area-inset-bottom) + 16px) for the toggle's bottom offset and mirror the
  same idea on the right inset. - Reserve padding-bottom on .page-shell-management so the last
  in-flow action (Save/Reset) is never hidden by the floating toggle. - Add a regression test in
  tests/static/test_ui_ia_polish.py asserting the new safe-area handling and the management shell
  padding.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.43.1 (2026-04-11)

### Bug Fixes

- **ci**: Make peak RSS sample actually exercise render path (JTN-613)
  ([#348](https://github.com/jtn0123/InkyPi/pull/348),
  [`feee3cd`](https://github.com/jtn0123/InkyPi/commit/feee3cdb5aa945e0f6ebaedab29f551e95b1ce09))

* fix(ci): make peak RSS sample actually exercise render path (JTN-613)

JTN-608 added idle/peak RSS budgets but the first Phase 4 run reported peak == idle (58 MB both)
  because the render-exercise loop POSTed to /update_now in a --web-only container without a CSRF
  token — the request was rejected with 403 before any plugin code ran. The peak budget was silently
  equivalent to the idle budget and would never catch a render-path regression.

Fix: introduce an opt-in /__smoke/render endpoint (src/app_setup/smoke.py) gated on
  INKYPI_SMOKE_FORCE_RENDER=1. When the env var is set at startup, Flask registers a CSRF-exempt
  POST route that calls plugin.generate_image() directly in-process (no display manager push) and
  returns the image dimensions. Production builds never set the env var, so the route is absent from
  real deployments.

scripts/test_install_memcap.sh Phase 4 now: - Sets INKYPI_SMOKE_FORCE_RENDER=1 in the Phase 3
  Dockerfile - Hits /__smoke/render (not /update_now) with plugin_id=clock three times to build up a
  sustained working set - Aborts loudly if /__smoke/render returns anything other than 200 -
  Enforces a JTN-613 sanity gate: peak RSS must be >= idle + 5 MB or the harness is considered
  broken and fails the CI job

Verified locally: `INKYPI_SMOKE_FORCE_RENDER=1 python src/inkypi.py --dev --web-only` registers
  /__smoke/render and POST clock plugin returns {"ok":true,"width":800,"height":480,...}. Without
  the env var, the route is not in app.url_map and the POST is rejected with 403 as before.

JTN-608 budgets (idle <200 MB, peak <300 MB) are unchanged — this commit fixes HOW we measure peak,
  not the thresholds.

Tests: tests/unit/test_smoke_render.py (20 tests covering registration gating, CSRF exemption,
  generate_image invocation, display-manager isolation, error paths) and a new
  TestInstallMemcapSmoke class in tests/unit/test_install_scripts.py (11 structural tests pinning
  the harness changes).

Parent: JTN-608 (PR #336)

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* fix(ci): avoid useless cat in smoke render error path (SC2002)

CI shellcheck is stricter than the local version and flagged `cat "${LOG_DIR}/smoke-render.json" |
  head -20` as SC2002. Rewrite as `head -20 "${LOG_DIR}/smoke-render.json"` to quiet the warning
  without changing behaviour.

* style: format merged install script tests

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Chores

- **security**: Suppress CodeQL false positives with justification (JTN-320)
  ([#347](https://github.com/jtn0123/InkyPi/pull/347),
  [`a9fb070`](https://github.com/jtn0123/InkyPi/commit/a9fb070ff540c50e7556bd8598240dd2132a7266))

* chore(security): suppress CodeQL false positives with justification (JTN-320)

Triages 12 of 52 open CodeQL alerts. Each suppressed alert lives in code that the taint tracker
  cannot fully model (validation/sanitization helpers, log sites that handle non-credential data, or
  static template assertions). Every suppression carries a specific justification at the call site
  so future maintainers can re-audit it.

- src/plugins/weather/weather_api.py (3) and weather_data.py (1):
  py/clear-text-logging-sensitive-data — logs OWM/Open-Meteo response bodies and IANA timezone
  strings, never the api_key. - src/plugins/base_plugin/base_plugin.py (3):
  py/clear-text-logging-sensitive-data — logs CSS file paths, file-read errors, and user-provided
  extra_css styling string. None are credentials. - src/static/scripts/playlist.js (1):
  js/xss-through-dom — assigning to img.src cannot execute JavaScript. - scripts/diag_network.py
  (1): py/insecure-protocol — ssl.create_default_context() disables TLSv1/1.1 by default since
  Python 3.6; CodeQL heuristic is wrong. - tests/static/test_plugin_settings_polish.py (1):
  py/incomplete-url-substring-sanitization — assertion is checking that a Jinja template's static
  placeholder text contains an example hostname, not validating a URL.

The four py/incomplete-url-substring-sanitization alerts in tests/plugins/ test_apod.py and
  scripts/render_weather_mock.py were refactored to use urlparse().netloc equality (and path/host
  inspection in render_weather_mock) rather than suppressed — that is the cleaner fix for those
  sites.

Adds a "CodeQL suppression policy" section to docs/development.md documenting the lgtm comment
  format, the requirement that every suppression include a justification, and the prohibition on
  suppressing alerts in src/blueprints/ files until JTN-318 lands.

Blueprint FP suppressions (~28 alerts in src/blueprints/** and src/utils/http_utils.py) are deferred
  to a follow-up after JTN-318 closes, since the user is actively rewriting those response paths.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* fix(security): resolve remaining CodeQL alerts

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Continuous Integration

- Add arm64 install.sh end-to-end matrix for Pi OS bases (JTN-530)
  ([#341](https://github.com/jtn0123/InkyPi/pull/341),
  [`1b45c92`](https://github.com/jtn0123/InkyPi/commit/1b45c92d977f71b4051a81c396d3653976ac19a1))

* ci: add arm64 install.sh end-to-end matrix for Pi OS bases (JTN-530)

JTN-528 silently broke Pi Zero 2 W installs on Trixie for an entire release cycle because no CI job
  ran install/install.sh against each supported Pi OS base. A matrix job would have caught the
  regression on PR day.

Adds a new install-matrix CI job that runs install.sh end-to-end inside an arm64 Debian container
  (with the Pi OS apt repo layered on so Pi-only packages resolve) for each supported codename:

* debian:bullseye (Pi OS 11) * debian:bookworm (Pi OS 12) * debian:trixie (Pi OS 13)

Each matrix leg: - builds a dedicated arm64 image (scripts/Dockerfile.install-matrix) with
  raspi-config and systemctl no-op shims, a /boot/firmware/ config.txt stub, and the systemd package
  (for systemd-analyze), - runs install.sh under a 512 MB memory cap (JTN-536 parity) so
  Trixie-specific OOMs during install are also caught, - asserts install.sh exits 0, - asserts the
  venv was created at /usr/local/inkypi/venv_inkypi, - asserts the venv imports flask, waitress, and
  Pillow, - asserts install/inkypi.service parses under systemd-analyze verify.

The matrix feeds into ci-gate.needs and the required-success loop so a failing leg blocks merge.
  INKYPI_SKIP_WHEELHOUSE=1 is set inside the container so the matrix exercises the source pip
  install path — a pre-built wheelhouse would mask a broken requirements.txt.

Design notes: * Chose the Pi OS apt repo approach over vanilla Debian with a skip-list because
  install.sh really does install liblgpio-dev and chromium-headless-shell, and both only resolve via
  archive.raspberrypi.com. The existing Dockerfile.sim-install already has this pattern working. *
  [trusted=yes] is used on the Pi OS apt line as a sim-only workaround for Debian Trixie's sqv
  rejecting the SHA1 signature archive.raspberrypi.com uses. Real Pi OS ships its own patched apt
  and does not hit this; the header comment warns not to copy the line to production configs. *
  Plain debian:<codename> tags are used with no date pins to avoid silent rot. Bumping the base is a
  one-line change inside the matrix. * The existing Install smoke (512 MB memory cap) job (JTN-536)
  is left untouched. This matrix adds to, doesn't replace.

Also adds a TestInstallMatrixWorkflow class in tests/unit/test_install_scripts.py (19 structural
  assertions) that fails CI if the workflow file, Dockerfile, or verification script are silently
  deleted or lose their install-matrix wiring.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* ci: drop ln -sf for systemctl shim on usrmerge layouts (JTN-530)

The first install-matrix run failed on bookworm with:

ln: '/usr/bin/systemctl' and '/bin/systemctl' are the same file

On Debian bullseye/bookworm/trixie, /bin is a usrmerge symlink to /usr/bin so overwriting
  /usr/bin/systemctl already covers /bin/systemctl (they share an inode). Attempting a second `ln
  -sf` fails with "same file" and kills the build. Drop the redundant symlink — the single
  /usr/bin/systemctl write now covers both paths on all three codenames.

* fix(ci): invoke install.sh via bash in install matrix

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Add nightly OS drift detector for install path (JTN-535)
  ([#339](https://github.com/jtn0123/InkyPi/pull/339),
  [`f52da41`](https://github.com/jtn0123/InkyPi/commit/f52da41ec608b9a555b8fbcb885352cf18e11269))

* ci: add nightly OS drift detector for install path (JTN-535)

Add .github/workflows/os-drift-nightly.yml — a daily cron (08:00 UTC) that re-runs the install path
  against the LATEST unpinned debian:trixie, debian:bookworm, and debian:bullseye images. This is
  the unpinned complement to the pinned PR-gating install matrix from JTN-530.

Each matrix leg asserts: - every package in install/debian-requirements.txt resolves via apt-cache
  show on the latest base image - install/requirements.txt still resolves via pip install --dry-run
  - scripts/sim_install.sh (JTN-532) runs install/install.sh end-to-end inside a 512 MB arm64 sim of
  the Pi Zero 2 W

On failure, a dedicated job opens a GitHub issue labelled os-drift/bug with the failing codename(s),
  diagnostic logs, and a link to the run, de-duping against any existing open drift issue so
  consecutive failures append a comment instead of spamming fresh issues. Workflow has no PR trigger
  on purpose — it is a drift detector, not a PR gate, and a broken nightly must never block merges.

Add TestOsDriftNightlyWorkflow in tests/unit/test_install_scripts.py with structural assertions
  (file exists, cron is set, no PR trigger, all three codenames present, unpinned images, end-to-end
  sim invoked, failure path files an issue, references JTN-535) to prevent silent deletion — losing
  this drift detector was the exact class of regression that let JTN-528 (zramswap on Trixie) slip
  through the whole Trixie release cycle.

Document the workflow in docs/testing.md including triage guidance for single-leg vs multi-leg
  failures.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* fix(ci): address os-drift workflow review feedback

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- **image**: Publish pre-installed Pi Zero 2 W image (JTN-533)
  ([#346](https://github.com/jtn0123/InkyPi/pull/346),
  [`6fe2c18`](https://github.com/jtn0123/InkyPi/commit/6fe2c18ce1e5594c12a8c5b37e9c7ee9bbe50731))

* ci(image): publish pre-installed Pi Zero 2 W image (JTN-533)

Adds .github/workflows/build-pi-image.yml — a release-time workflow that builds a pre-installed
  inkypi-<version>-pi-zero-2-w.img.xz, boot-verifies it in qemu-system-aarch64, and attaches it to
  the GitHub release.

Shipping a pre-installed image collapses the ~15 minute on-device install.sh run on a Pi Zero 2 W
  into a ~60 second flash-and-boot, and eliminates the install-failure support surface entirely for
  new users.

How it works: 1. Download + checksum-verify a pinned Pi OS Lite arm64 base image (URL + SHA256 live
  in a clearly-marked top-of-file PIN POINT block). 2. Loop-mount + bind-mount /proc /sys /dev, copy
  qemu-aarch64-static. 3. Drop raspi-config / systemctl no-op stubs on PATH inside the chroot so
  install.sh's runtime hooks don't fail mid-build (does NOT modify install.sh — option 2
  source-install stays self-contained). 4. Clone InkyPi at the release tag, run install/install.sh
  unchanged. 5. Clean caches, zero-fill free space, unmount, shrink with pishrink.sh (pinned by full
  commit SHA), recompress with xz -9. 6. Boot-verify in qemu-system-aarch64 with a 4-minute
  login-prompt grep. 7. Only if verification passes, attach image + .sha256 via
  softprops/action-gh-release@v2 (same pattern as JTN-604 wheelhouse).

Docs (docs/installation.md): - New "Option 1 — Pre-built image" section at the top of the install
  guide, covering download, sha256 verification, Pi Imager advanced options for hostname/Wi-Fi/SSH
  (no credentials are baked into the image), and Pi Zero 2 W-only scope. - Existing install.sh flow
  demoted to "Option 2 — Install from source (contributors, custom boards)".

Tests (tests/unit/test_install_scripts.py): - 20 new structural assertions in
  TestPiImageBuildWorkflow covering trigger events, pinned URL + SHA, chroot + qemu plumbing,
  release-tag clone, pishrink pinning, xz -9 recompression, boot-verify job, and the attach-release
  gate that blocks unverified images from shipping. - 5 new assertions in
  TestInstallationDocPreBuiltImage verifying the new docs section covers .img.xz, .sha256, Pi Zero 2
  W scope, and references JTN-533.

Unverified vs verified (flagged in PR body): - The workflow's qemu boot-verify step proves kernel +
  userspace + getty reach "login:" but cannot simulate Pi GPIO/SPI hardware. Treat the first shipped
  image as dogfood-ready, not production-ready, until real-Pi verification lands (follow-up in the
  same Linear epic). - qemu-user-static + chroot can give false successes — something that works in
  the chroot can still fail on real hardware.

Supply-chain: - Pi OS image: pinned URL + 64-char SHA256 in env block - pishrink.sh: pinned 40-char
  commit SHA, fetched at build time (not vendored — avoids maintaining a third-party script in-tree)
  - Every GitHub action pinned by major version (@v4 / @v2)

113/113 tests pass in tests/unit/test_install_scripts.py (25 new). Two unrelated failures in
  tests/unit/test_plugin_registry.py also fail on main at 4ec7921 — tracked separately.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* chore(deps): regenerate pip-compile lockfiles to clear CI drift

CI's Lockfile drift check has been failing on every recent PR because upstream packages have been
  bumped since the last regeneration. This is a pure `pip-compile --upgrade` refresh — no changes to
  `.in` files, no scope change. Lockfiles are back in sync with both requirements.in and
  requirements-dev.in (verified via scripts/check_requirements_drift.sh).

Notable bumps: werkzeug 3.1.6 -> 3.1.8, cyclonedx-bom 6.1.0 -> 6.1.3, cyclonedx-python-lib 9.1.0 ->
  10.5.0, feedparser 6.0.11 -> 6.0.12, and their transitive closure. All versions still satisfy the
  ranges in install/requirements*.in, so this is a lockfile refresh only.

The manually-maintained Linux-only block at the bottom of requirements.txt (cysystemd, spidev, etc.)
  is preserved verbatim — only the pip-compile region above the sentinel changed.

Split from the JTN-533 image-build workflow commit because it's unrelated to image building and
  should not be gated on that review.

* test(security): avoid substring URL checks in workflow assertions

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.43.0 (2026-04-11)

### Bug Fixes

- Validate NASA APOD date range (1995-06-16..today) (JTN-379)
  ([#345](https://github.com/jtn0123/InkyPi/pull/345),
  [`b246328`](https://github.com/jtn0123/InkyPi/commit/b24632862f25290b718f631b9845ad549361f6af))

The APOD plugin's Date input previously accepted any value, including pre-1995 and far-future dates.
  Saves succeeded with a green toast and only failed later when generate_image tried to fetch a
  non-existent APOD from NASA's API — far from where the user could fix it.

Add a validate_settings hook that rejects custom dates outside the [1995-06-16, today] window (the
  NASA APOD archive begins on 1995-06-16), plus min/max constraints on the date input field for
  client-side feedback.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- **settings**: Enforce HTML5 validation before Save submit (JTN-350)
  ([#344](https://github.com/jtn0123/InkyPi/pull/344),
  [`96d66d4`](https://github.com/jtn0123/InkyPi/commit/96d66d48fded4a56afaf7d88c6416bee0b8c3165))

The Settings Save button enabled itself on any input event without consulting form.checkValidity(),
  letting users click Save with deviceName empty or interval=-5 and only learning about the problem
  from server-side error toasts. The browser's native :invalid popup never fired.

Two changes pin the contract:

1. checkDirty now requires BOTH dirty state AND form.checkValidity() to enable Save. The button
  remains disabled the moment any constraint is violated, on every keystroke (the existing
  input/change listeners already trigger the recheck).

2. handleAction calls form.checkValidity() and form.reportValidity() before posting to the server.
  If anything is invalid, the native HTML5 balloon is shown, the first :invalid field receives
  focus, and the request is bailed out before contacting the server. This is a defense in depth in
  case the disabled gate is bypassed (e.g. programmatic click).

A static-analysis test pins the helper, the validity gate, the reportValidity call ordering, and the
  underlying HTML5 constraints on deviceName / interval so a future refactor can't silently regress
  the fix.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Continuous Integration

- Add arm64 install.sh end-to-end matrix (JTN-530)
  ([#340](https://github.com/jtn0123/InkyPi/pull/340),
  [`7990f47`](https://github.com/jtn0123/InkyPi/commit/7990f47f479b4d621ddfb0b5471ced20785e0d66))

Adds a new install-matrix workflow that runs scripts/test_install_memcap.sh under arm64 QEMU
  emulation against bullseye, bookworm, and trixie. JTN-528 (Trixie zramswap regression) went
  undetected for the entire Trixie release cycle because no CI job exercised install.sh on each Pi
  OS base; this matrix closes that gap. Standalone advisory job for now (not wired into ci-gate).

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Add per-PR startup memory diff comment (JTN-610)
  ([#342](https://github.com/jtn0123/InkyPi/pull/342),
  [`b9c129e`](https://github.com/jtn0123/InkyPi/commit/b9c129efc240ea0e0be1df6f23801fb01e36f24b))

* ci: add per-PR startup memory diff comment (JTN-610)

Every PR now gets a sticky comment showing how its startup allocator breakdown compares to the base
  branch — an early warning for the slow memory creep that JTN-608's hard RSS budgets would only
  catch after cumulative damage.

- scripts/memory_diff.py: profiles `import inkypi` with memray (preferred) or stdlib tracemalloc
  (fallback) and emits a stable JSON summary with the top 20 allocators, peak RSS, and sys.modules
  count. - scripts/format_memory_diff.py: diffs two JSON summaries and renders a collapsible
  Markdown table with a hidden sticky marker so force-pushes overwrite the existing comment instead
  of spamming new ones. - .github/workflows/memory-diff.yml: new pull_request workflow, marked
  continue-on-error so it never blocks the PR (JTN-608 owns hard budgets). Measures both branches
  via `git worktree add`, uploads raw JSON as an artifact, and posts/updates the sticky comment via
  actions/github-script. - install/requirements-dev.in: declares memray (Linux only) so the next
  lockfile regen picks it up; CI installs it explicitly in the meantime. -
  tests/unit/test_install_scripts.py: adds TestMemoryDiffWorkflow with 13 structural assertions
  covering the workflow triggers, non-blocking posture, sticky marker contract, and helper script
  presence.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* fix(memory-diff): use memray Python API + soft-fail on capture errors

The first CI run exposed two bugs:

1. `memray stats --json` does not emit JSON to stdout — it writes a human-readable report. Switched
  to memray's FileReader Python API (`get_high_watermark_allocation_records`) which is the
  documented machine-readable surface and aggregates allocations live at peak RSS (more meaningful
  than total-ever-allocated because short-lived churn is excluded). 2. A memray backend failure
  would crash the whole job. Now wrapped in a try/except that falls back to tracemalloc so the
  comment still posts, matching the JTN-610 "tolerant of first-time setup" requirement.

Also hardened the workflow's PR-measurement step to soft-fail so the formatter always runs and posts
  a "backend unavailable" comment rather than leaving the PR with no signal at all.

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Promote JTN-609 install crash-loop test to a mandatory CI gate (JTN-614)
  ([#343](https://github.com/jtn0123/InkyPi/pull/343),
  [`f6de982`](https://github.com/jtn0123/InkyPi/commit/f6de982bfa28e3fad8cce294bfdfb19b51be8e8a))

JTN-609 landed `tests/integration/test_install_crash_loop.py` as a Docker-based regression gate that
  verifies both JTN-600 (systemctl disable during install) and JTN-607 (install-in-progress
  lockfile) prevent a mid-install crash from spawning a restart loop that would OOM a Pi Zero 2 W.
  The test was left auto-skipping on runners without Docker to avoid a merge conflict with JTN-608
  (PR #336) which was touching the smoke test script in parallel. Both have merged, so it is safe to
  wire this in as a blocking CI gate.

Changes:

- New job `install-crash-loop-gate` in `.github/workflows/ci.yml`, runs on `ubuntu-latest` (Docker
  available), 10 min timeout. Sets `REQUIRE_INSTALL_CRASH_LOOP_TEST=1` so the test fails hard if
  Docker is unexpectedly missing rather than silently skipping. - Added to the `ci-gate` `needs:`
  list and to the required-success loop (`.github/workflows/ci.yml:661`) alongside
  `install-smoke-memcap`, so a regression that breaks JTN-600 or JTN-607 now blocks merge. -
  Documented the CI hookup in `docs/testing.md`'s existing "Pi thrash protection regression gate"
  section.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Features

- Add snapshot/golden-file testing harness for plugin image outputs (JTN-509)
  ([#332](https://github.com/jtn0123/InkyPi/pull/332),
  [`29fc557`](https://github.com/jtn0123/InkyPi/commit/29fc557c0724bcfdb7bbd8377da396d1b233c17b))

* feat: add snapshot/golden-file testing harness for plugin image outputs (JTN-509)

MVP — follow-ups to expand coverage (more plugins, CI diff upload).

- tests/snapshots/snapshot_helper.py: tiny SHA-256 digest helper; no new deps -
  tests/snapshots/test_plugin_snapshots.py: 3 snapshot tests covering year_progress (mid-year,
  start-of-year) and countdown (future date) -
  tests/snapshots/{year_progress,countdown}/*.{png,sha256}: captured baselines -
  scripts/update_snapshots.py: interactive baseline regeneration script - .gitattributes: mark
  tests/snapshots/**/*.png as binary - tests/snapshots/README.md: documents the pattern for future
  contributors

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* fix(tests): snapshot tests now actually render via Chromium (JTN-509)

The original MVP was silently broken: every baseline was a blank white 2247-byte canvas because two
  things conspired to bypass real rendering:

1. The parent `tests/conftest.py` has an autouse `mock_screenshot` fixture that replaces
  `take_screenshot_html` with a blank-canvas stub so the rest of the suite doesn't pay the Chromium
  startup cost. Snapshot tests inherited this stub and always got the blank fallback. 2. The main
  `Tests (pytest)` CI job doesn't install Playwright Chromium, so even without the stub the
  `_screenshot_fallback()` in `base_plugin.py` would have produced the same blank.

The old "tests" compared identical blanks on the sub-agent's macOS env (so they "passed" there),
  then failed on Ubuntu CI because Pillow's PNG encoder emits slightly different bytes for a blank
  canvas across envs.

Fix: - Add `tests/snapshots/conftest.py` that overrides `mock_screenshot` with a no-op so real
  Chromium rendering happens in this directory only. - Gate the tests with `pytestmark = skipif(not
  REQUIRE_BROWSER_SMOKE)` so they skip cleanly anywhere without a working browser (local macOS dev
  and the main pytest CI matrix) and only run in the browser-smoke CI job. - Add `tests/snapshots/`
  to the `browser-smoke` pytest invocation in `.github/workflows/ci.yml`. - Switch
  `snapshot_helper._image_sha256()` to hash the raw pixel buffer (`mode|WxH|tobytes()`) instead of
  PNG bytes, so libpng/zlib version differences between environments don't cause spurious
  mismatches. - Regenerate all 3 baselines inside a `linux/amd64` docker container with the pinned
  requirements + Playwright Chromium installed, matching the browser-smoke CI env. The new baselines
  are real rendered content (16-19 KB each, full 0-255 pixel range, all 3 distinct SHA-256 digests).
  - Document the docker regeneration command and environment gating in `tests/snapshots/README.md`.

Verified: in docker, `SNAPSHOT_UPDATE=1 REQUIRE_BROWSER_SMOKE=1 pytest tests/snapshots/` produces
  real renders in ~6s, and a follow-up verify run without SNAPSHOT_UPDATE passes via digest match.
  Locally on macOS without `REQUIRE_BROWSER_SMOKE` the 3 tests skip cleanly.

* fix(tests): regenerate snapshot baselines in ubuntu:24.04 to match CI

The previous commit captured baselines in a python:3.12-slim-bookworm (debian bookworm) docker
  container, which has a different default-font set than the GitHub Actions ubuntu-latest
  (ubuntu-24.04) runners. Even though plugin CSS injects the bundled Jost font via @font-face with a
  file:// URL, Chromium's text rendering still varies slightly across base OSes — enough to produce
  different pixel buffers and different SHA-256 digests.

Regenerate all 3 baselines inside an ubuntu:24.04 container (which matches ubuntu-latest exactly)
  with the pinned requirements + Playwright Chromium. Update the README's docker regeneration
  command to use ubuntu:24.04 going forward so future updates don't hit the same drift.

Verified in the same container: UPDATE run stores new baselines, VERIFY run passes via digest match.
  All 3 PNGs contain real rendered content (full 0-255 pixel range across all channels) and 3
  distinct SHA-256s.

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Testing

- **install**: Add crash-loop regression gate (JTN-609)
  ([#338](https://github.com/jtn0123/InkyPi/pull/338),
  [`4ec7921`](https://github.com/jtn0123/InkyPi/commit/4ec7921b0b9f816e97139cf0e55043bd3c55fbf7))

On 2026-04-10 a real Pi Zero 2 W went into a memory-thrash cascade during an install because
  install.sh stopped but did not disable inkypi.service. JTN-600 (systemctl disable in stop_service)
  and JTN-607 (install-in-progress lockfile refused by ExecStartPre) are the fix. This commit is the
  regression gate that proves both defenses stay effective.

tests/integration/test_install_crash_loop.py boots a systemd-capable Debian container (privileged,
  512 MB cap), installs inkypi.service verbatim with a stub ExecStart that mimics
  ModuleNotFoundError: flask and touches a marker file the moment it runs, exercises
  stop_service()'s disable contract, creates the install-in-progress lockfile, and then repeatedly
  tries to start the service. The primary assertion is that the stub marker never appears — i.e.
  ExecStart never runs — because the ExecStartPre guard refuses every attempt. A positive-control
  step removes the lockfile and confirms ExecStart does run once the install is "complete" so the
  pass condition is not vacuous.

Observed on a clean run: NRestarts=2 (bounded by default StartLimitBurst), ExecMainPID=0, stub
  marker absent. Mutation-tested by commenting out the lockfile touch — the test fails loudly with
  ExecMainPID=132 and "ExecStart ran while install-in-progress lockfile was present", as expected.

The test skips cleanly when Docker is unavailable; set REQUIRE_INSTALL_CRASH_LOOP_TEST=1 to
  force-run and fail hard if Docker is missing. End-to-end wall-clock is ~55 s, well under the <5
  min budget.

docs/testing.md documents the gate as the canonical "Pi thrash protection regression gate" including
  the three invariants it asserts.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.42.3 (2026-04-11)

### Bug Fixes

- Validate calendar URL + prevent empty row spam (JTN-357)
  ([#337](https://github.com/jtn0123/InkyPi/pull/337),
  [`d8dfae0`](https://github.com/jtn0123/InkyPi/commit/d8dfae05ab465a0a198b0f2b0992113d6a8ada17))

Frontend: The calendar URL input now uses type="url" with a

https?://.+ pattern hint and required, so the browser enforces basic URL constraints before
  submission.

JS: The Add Calendar button refuses to append a new empty row while the last existing row is empty
  or fails HTML5 constraint validation, and surfaces a toast via showError instead of a browser
  dialog. This closes the empty-row spam loop reported during dogfooding on 2026-04-08.

Backend: Calendar.validate_settings now rejects non-http(s)/webcal URLs at save time via
  urllib.parse.urlparse, so bad values can never be persisted even if the client-side guard is
  bypassed.

Tests: tests/plugins/test_calendar_validation.py covers the validate_settings contract
  (http/https/webcal accepted, empty, whitespace, javascript:, file:, bare strings rejected, any-row
  rejection) plus a template render test asserting the input is type="url" and required.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Validate image_folder path exists on save (JTN-355)
  ([#334](https://github.com/jtn0123/InkyPi/pull/334),
  [`bb8be7f`](https://github.com/jtn0123/InkyPi/commit/bb8be7f170ee53f0ae6df7736147bc104885ee33))

* fix: validate image_folder path exists on save (JTN-355)

Previously the Image Folder plugin accepted any folder_path at save time and silently persisted bad
  values, failing later at refresh time with no link back to the save action. Add
  validate_settings() so the existing save_plugin_settings flow rejects missing, non-existent,
  unreadable, or empty folders with an inline 400 error — matching the pattern used by Weather
  (JTN-354) and Screenshot.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* test: use real dirs for image_folder positive integration cases

The happy-path integration tests in test_plugin_validation.py used /tmp/test-images and
  /tmp/new-path as placeholder paths — paths that never existed on CI runners. The old image_folder
  save handler did not check folder existence, so those tests passed. Now that validate_settings
  (JTN-355) rejects missing/empty folders, switch the positive cases to tmp_path-backed directories
  containing a real PNG so they still exercise the required-field success path.

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Testing

- **ci**: Assert post-install RSS budgets in smoke test (JTN-608)
  ([#336](https://github.com/jtn0123/InkyPi/pull/336),
  [`d08c63b`](https://github.com/jtn0123/InkyPi/commit/d08c63b9764fbe6fdfd15956d0038825f0db15b9))

Extends the JTN-536 memory-capped smoke test with a Phase 4 RSS budget gate so a regression that
  balloons baseline memory passes install.sh and the boot probes but still fails CI before reaching
  a Pi Zero 2 W (which caps inkypi.service at MemoryMax=350M).

Phase 4 reads VmRSS from /proc/1/status inside the 512 MB-capped container (no procps dependency),
  samples twice:

- Idle after a 30s settle, hard fail >200 MB (target <150 MB) - Peak after exercising /, /playlist,
  /api/plugins, /api/health/plugins, and POST /update_now with plugin_id=clock, hard fail >300 MB
  (target <250 MB)

Both samples print a BUDGET CHECK: line so regressions are grep-friendly in CI logs, and failure
  dumps docker logs via tee to ${LOG_DIR}.

The 100-request memory-growth leak check from the ticket is intentionally deferred — the two-sample
  idle/peak gate catches the regressions we care about at PR time without adding minutes to every
  run. Documented in docs/testing.md under "CI memory budgets".

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.42.2 (2026-04-11)

### Bug Fixes

- Unify image_upload background fill label to "Color" (JTN-358)
  ([#335](https://github.com/jtn0123/InkyPi/pull/335),
  [`a6b62bd`](https://github.com/jtn0123/InkyPi/commit/a6b62bd683a6cfda8088837a23f3644cb4f16f70))

Image Upload's Background Fill toggle showed "Solid Color" while the sibling Image Folder and Image
  Album plugins showed "Color". Since two of three plugins already used "Color", rename image_upload
  to match so the three image plugins present a consistent UI.

Also add a schema-level regression test that asserts the backgroundOption option labels stay in sync
  across image_upload, image_folder, and image_album.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.42.1 (2026-04-11)

### Performance Improvements

- **install**: Migrate pip to uv in install.sh for faster, lighter installs (JTN-605)
  ([#326](https://github.com/jtn0123/InkyPi/pull/326),
  [`403ea1f`](https://github.com/jtn0123/InkyPi/commit/403ea1f9cd6eb4c58f231992d02e26c45efc5e1e))

On a Pi Zero 2 W (512 MB RAM), pip's Python-based resolver consumes ~100-150 MB during dependency
  resolution, a significant fraction of total RAM. uv (Rust-based pip replacement from the ruff
  team) uses ~10-20 MB peak and installs 3-5x faster, cutting the install-time bottleneck from ~15
  min to ~3-5 min.

- Bootstrap uv into the venv via `pip install uv` (uses trusted PyPI + hashes we already trust — no
  extra network trust root from curl-pipe) - Use `uv pip install --python $VENV --no-cache
  --require-hashes` for main deps; `--require-hashes` is fully honored so JTN-516 supply-chain
  integrity is preserved - Fall back cleanly to plain `pip install` if uv cannot be installed or run
  (e.g. unsupported arch) — uv is an optimization, not a hard dep - Same uv-or-pip branching for the
  optional Waveshare requirements - Extend tests/unit/test_install_scripts.py with four new
  structural checks: uv bootstrap exists, uv pip install used for main deps with hash enforcement
  preserved, pip fallback branch exists, bootstrap precedes first uv call - Document the improvement
  in docs/installation.md under "First-boot install time"

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.42.0 (2026-04-11)

### Features

- Add pip-compile drift check to CI (JTN-597) ([#333](https://github.com/jtn0123/InkyPi/pull/333),
  [`149d097`](https://github.com/jtn0123/InkyPi/commit/149d097059cb635094b1a1777a7c204268baa74b))

Adds scripts/check_requirements_drift.sh that compares the pip-compile region of
  install/requirements.txt (stripping the manually-maintained Linux-only block at the sentinel
  comment) and install/requirements-dev.txt against a fresh pip-compile run, failing with an
  actionable diff if they diverge.

Adds a new lockfile-drift CI job in ci.yml that installs pip-tools and runs the script. The job is
  currently advisory (continue-on-error: true) because packages have drifted on PyPI since the last
  lockfile regeneration; remove that flag after refreshing requirements.txt under Python 3.12. The
  shellcheck job is extended to syntax-check the new script.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.41.0 (2026-04-11)

### Bug Fixes

- Display "Webcomic Name" (title case) in Daily Comic dropdown (JTN-386)
  ([#329](https://github.com/jtn0123/InkyPi/pull/329),
  [`ddf6833`](https://github.com/jtn0123/InkyPi/commit/ddf6833d24ac524cabb8a06defff98bbd73ad9ac))

The comic key "webcomic name" is preserved for backward compatibility with existing device configs.
  A COMIC_LABELS mapping provides the correct display label "Webcomic Name" (Alex Norris's official
  title) in the plugin dropdown.

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>

### Features

- Publish CycloneDX SBOM as release asset (JTN-517)
  ([#330](https://github.com/jtn0123/InkyPi/pull/330),
  [`6dce07a`](https://github.com/jtn0123/InkyPi/commit/6dce07ab44caa62c39b699562e608c3b930edfc5))

Regenerates the SBOM during release and attaches it to every GitHub release as
  inkypi-vX.Y.Z-bom.json using gh release upload. Adds docs/security.md explaining how to download
  and validate the SBOM with cyclonedx-cli and pip-audit.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.40.3 (2026-04-11)

### Bug Fixes

- Use type=password for existing API key value inputs (JTN-382)
  ([#331](https://github.com/jtn0123/InkyPi/pull/331),
  [`44bdb56`](https://github.com/jtn0123/InkyPi/commit/44bdb56d54b4a524eec90f87b2a9edd94151e432))

Replace the type=text inputs filled with literal U+25CF bullet characters with type=password inputs
  having value="" and placeholder="(unchanged)". This fixes screen reader output, password manager
  recognition, and prevents garbage being copied when a user selects the masked field.

Also update the aria-label to include ", hidden" to communicate the masked state to assistive
  technology.

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>


## v0.40.2 (2026-04-11)

### Bug Fixes

- Harden systemd-run command construction in updater (JTN-319)
  ([#322](https://github.com/jtn0123/InkyPi/pull/322),
  [`dc321a4`](https://github.com/jtn0123/InkyPi/commit/dc321a440038677f0964036fb12c0d7d07f69e12))

* fix: harden systemd-run command construction in updater (JTN-319)

CodeQL py/command-line-injection alert #47 flagged _start_update_via_systemd because the "script
  path validated" claim in its nosec comment was not visible to static analysis or human review.

Make the validation explicit and defense-in-depth:

- Reject unit names that do not match ^inkypi-(update|rollback)-\d+$. - Reject script paths whose
  basename is not in UPDATE_SCRIPT_NAMES, that contain shell metacharacters, that are not absolute,
  or that contain traversal tokens. - Re-validate target_tag against the strict semver _TAG_RE
  inside the function, not only at the request boundary. - Apply the same allow-list validation to
  _run_real_update for the non-systemd fallback path so both branches share the same invariants. -
  Harden install/do_update.sh: validate the target tag format before passing it to git, resolve it
  as refs/tags/<tag>, and use the -- separator on git checkout so a crafted tag cannot be
  interpreted as an option. - Replace the misleading "# nosec" comment with a "# noqa: S603" that
  documents the now-visible allow-list. - Add 16 unit tests covering bad/good unit names, script
  paths, and target tags, plus the _run_real_update defense-in-depth path.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* fix(settings): rebuild Popen argv from allow-list for CodeQL clarity

CodeQL's dataflow analysis did not recognise our basename-set-membership check as a sanitizer, so
  the py/command-line-injection alert re-fired on the PR scan. Rebuild the sensitive argv elements
  from allow-list constants and regex-match results instead of forwarding the tainted
  caller-supplied values, so CodeQL sees only clean values reaching subprocess.Popen.

- _start_update_via_systemd and _run_real_update now construct a ``safe_script_path`` from a literal
  basename in the allow-list plus the pre-validated directory component. - ``safe_unit_name`` and
  ``safe_target_tag`` come from the regex match objects, so the values that flow into the argv are
  the matched substrings rather than the original inputs. - Add a space character to the
  shell-metacharacter rejection list for script paths (installed paths never contain spaces and this
  further tightens the allow-list).

* refactor(settings): extract update validators and use guard-style sanitization

Address two follow-up findings from CI:

1. SonarCloud quality gate failed on duplicated lines density (17.6%) because
  _start_update_via_systemd and _run_real_update both inlined the same allow-list checks. Extract
  three module-level helpers (_validate_update_unit_name, _validate_update_script_path,
  _validate_update_target_tag) and call them from both sites.

2. CodeQL still flagged py/command-line-injection because it does not recognise
  ``re.fullmatch(...).group(0)`` as a sanitizer when the matched value is then placed in an argv
  list. Restructure the validators to use ``re.fullmatch`` purely as a guard followed by returning
  the original (now-proven-safe) string, which is the form CodeQL's built-in sanitizer recognition
  expects. Add a new _UPDATE_SCRIPT_PATH_RE that constrains the full path to a strict POSIX-safe
  character class so the script-path argument is sanitised by a regex guard rather than by the
  previous ad-hoc loop.

* fix(settings): inline re.fullmatch sanitiser at Popen call sites

CodeQL's py/command-line-injection sanitiser recognition for Python fires only when the
  ``re.fullmatch`` (or ``re.match``) call is in the same call frame as the subprocess.Popen
  invocation, with the regex literal visible. The previous version routed validation through
  ``_validate_update_*`` helpers and a module-level pre-compiled ``_TAG_RE`` /
  ``_UPDATE_UNIT_NAME_RE``, neither of which CodeQL recognised as a barrier.

Restructure so:

- ``_sanitize_update_argv`` performs the script-path / target-tag guards once and is used from both
  _start_update_via_systemd and _run_real_update (avoiding the SonarCloud duplicated-lines failure).
  - Both call sites also include an *inline* ``re.fullmatch`` immediately before subprocess.Popen,
  with the regex pattern as a string literal. This is the form CodeQL recognises as a sanitiser. -
  The unit_name guard is inlined directly in _start_update_via_systemd for the same reason. - Drop
  the now-unused module-level ``_UPDATE_UNIT_NAME_RE`` and ``_UPDATE_SCRIPT_PATH_RE`` constants.

* Potential fix for pull request finding 'CodeQL / Uncontrolled command line'

Co-authored-by: Copilot Autofix powered by AI
  <62310815+github-advanced-security[bot]@users.noreply.github.com>

* fix: address CodeRabbit feedback + CodeQL false-positives (JTN-319)

Rescue PR #322:

- Add _validate_update_script_path() with realpath + trusted-root enforcement (CodeRabbit Major:
  directory-root enforcement was missing). - Align _TAG_RE with bash regex in install/do_update.sh —
  both now reject underscores by using [A-Za-z0-9.] instead of \w (CodeRabbit Major: regex
  divergence). - Drop unit_name and script_path parameters from _start_update_via_systemd so the
  only Popen-bound variable is target_tag, regex-validated inline in the same function frame for
  CodeQL #83 (the previous helper-based approach failed taint propagation across boundaries). -
  Update _updates.py caller to drop the now-removed positional args. - Replace "/tmp/evil.sh" test
  fixture with "/opt/attacker/evil.sh" so ruff S108 stops flagging the negative-path test
  (CodeRabbit Major). - Refresh TestStartUpdateViaSystemdValidation to match the new
  single-parameter contract; add TestValidateUpdateScriptPath covering symlink resolution,
  traversal, and trusted-root enforcement.

* fix: dedupe semver regex into _TAG_RE constant with re.ASCII (JTN-319)

SonarCloud S1192 flagged the target-tag regex literal repeated 3 times across
  _start_update_via_systemd and _run_real_update. S6353 (9 instances) flagged [0-9] usage that
  should be \d.

Switch both inline call sites to use the module-level _TAG_RE compiled pattern (already present at
  line 97), and rewrite it as re.compile(r"^v?\d+\.\d+\.\d+(-[A-Za-z0-9.]+)?$", re.ASCII)

The re.ASCII flag is load-bearing: without it, \d in Python 3 matches Unicode digit categories,
  which would let spoofed tags like v\u0661.\u0662.\u0663 (Arabic-Indic numerals) pass validation.
  With re.ASCII, \d is equivalent to [0-9], matching the POSIX pattern in install/do_update.sh.

CodeQL's Python security model recognises re.Pattern.fullmatch as a sanitiser just like the inline
  re.fullmatch form, so this keeps the py/command-line-injection alerts closed.

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.40.1 (2026-04-11)

### Performance Improvements

- Lazy-import heavy modules to cut startup RSS (JTN-606)
  ([#328](https://github.com/jtn0123/InkyPi/pull/328),
  [`16192bb`](https://github.com/jtn0123/InkyPi/commit/16192bb3bed88d9e62b2faa68d3a0fd8b4202707))

* perf: lazy-import heavy modules to reduce startup RSS (JTN-606)

Defer pi_heif, PIL.ImageDraw/Font/Filter/Enhance/Ops, requests/urllib3, and charset_normalizer from
  module-load to first-use so they no longer inflate the startup resident set on low-memory devices
  like the Pi Zero 2 W (425 MB RAM).

Why --- * inkypi.py unconditionally registered the HEIF PIL opener at startup, importing pi_heif (~3
  MB native ext, ~28 ms) every boot even on devices that never see an iPhone upload. *
  utils.app_utils pulled PIL.ImageDraw/ImageFont/ImageOps at module load, but they are only used
  inside generate_startup_image() and the upload validation helpers. * utils.http_utils imported
  requests + urllib3 at module scope, which pulled charset_normalizer/chardet into every process —
  the json_* error helpers used by error_handlers do not need them. * utils.image_utils /
  fallback_image / webhooks had the same issue: heavy imports for functions that only run during
  render or error.

Changes ------- * inkypi.py: drop module-level pi_heif registration; utils.image_loader now lazily
  registers the HEIF opener on first image load via _ensure_heif_opener(). * utils.app_utils: move
  PIL imports into get_font, generate_startup_image, _process_uploaded_file and
  _validate_image_content. * utils.fallback_image: move PIL.Image / ImageDraw into
  render_error_image; drop the PIL.Image.Image return annotation so the module no longer needs PIL
  at import time. * utils.image_utils: keep PIL.Image at module scope (used by many callers via type
  hints and LANCZOS) but defer ImageEnhance, ImageFilter, ImageOps into the functions that use them.
  * utils.http_utils: move ``requests`` / HTTPAdapter / urllib3 Retry into _build_retry,
  _build_session and http_get; TYPE_CHECKING block keeps strict mypy typing intact. *
  utils.webhooks: expose ``requests`` via module __getattr__ so existing
  patch("utils.webhooks.requests.post", ...) tests keep working while the real import only happens
  on the first webhook fire.

Impact (measured via /usr/bin/time -l on macOS) ----------------------------------------------- *
  Peak memory footprint: 47.2 MB -> 37.9 MB (~9.3 MB, ~20% drop). * Modules loaded by ``import
  inkypi``: 844 -> 543 (-301). * On the real Pi Zero 2 W (glibc + native codec libs) the reduction
  is expected to be materially larger because pi_heif / PIL submodules pull in shared objects that
  macOS Python links differently.

Tests ----- New tests/unit/test_lazy_imports.py runs a fresh Python subprocess that imports inkypi
  and asserts that none of {playwright, PIL.ImageDraw, PIL.ImageFont, PIL.ImageFilter,
  PIL.ImageEnhance, PIL.ImageOps, pi_heif, requests, urllib3, charset_normalizer, chardet, openai,
  anthropic} appear in sys.modules — a structural guard against regressions. Also bounds the total
  module count (<750) so a future accidental numpy/ pandas import would fail loudly. Existing suite:
  3371 -> 3372 passing (plus 17 new tests); the two pre-existing pyenv-related plugin_registry
  failures on main are unrelated to this change.

Refs: parent epic JTN-529 (install path hardening).

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* fix: thread-safe HEIF opener + subprocess check=False (CodeRabbit)

Address CodeRabbit review on PR #328:

* utils.image_loader: guard _ensure_heif_opener with a double-checked lock so concurrent upload
  threads cannot race on first registration. Previous check-then-act was not thread-safe under
  waitress; while pi_heif.register_heif_opener() is likely idempotent, making the serialization
  explicit avoids any edge case and silences the Ruff PLW0603 concern surfaced in review.

* tests/unit/test_lazy_imports: pass check=False to the import-probe subprocess.run call so the
  manual returncode handling is explicit (PLW1510). No behavior change — the test already raised on
  non-zero exit.

Refs: JTN-606, parent epic JTN-529.

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.40.0 (2026-04-11)

### Features

- Ship pre-built wheelhouse as release asset (JTN-604)
  ([#327](https://github.com/jtn0123/InkyPi/pull/327),
  [`86664f5`](https://github.com/jtn0123/InkyPi/commit/86664f5125f5dc1f05ccd97ef248659cdd7d05e2))

First-boot install on a Pi Zero 2 W spends ~12 of its ~15 minutes building wheels for
  numpy/Pillow/cffi/playwright on a single Cortex-A53 core — the exact scenario that caused the
  memory thrash cascade on 2026-04-10. Pre-compile every dep in CI and attach a wheelhouse tarball
  to each release; install.sh prefers the bundle and falls back to source install on any failure.

New build-wheelhouse workflow builds wheels inside a QEMU-emulated Debian Trixie container for
  linux_armv7l (Pi Zero 2 W) and linux_aarch64 (Pi 4/5) on release publish, attaches
  inkypi-wheels-<version>-<arch>.tar.gz + sha256 to the release.

install.sh create_venv now calls fetch_wheelhouse before the main pip install. The fetch: detects
  arch from uname -m, downloads the tarball from the jtn0123/InkyPi release matching the local
  VERSION, verifies sha256 when available, extracts it, and passes --find-links + --prefer-binary to
  pip. Every failure path (missing tarball, network error, checksum mismatch, empty bundle,
  unsupported arch) cleans up the temp dir and returns non-zero so the caller falls back to the
  normal online install. INKYPI_SKIP_WHEELHOUSE=1 opts out entirely.

Regression guards keep JTN-602 --no-cache-dir intact on the new pip invocation and confirm the
  wheelhouse path never bypasses --require-hashes (JTN-516 supply-chain integrity).

Tests: 20 new structural assertions in test_install_scripts.py cover the fetch function, its
  opt-out, the create_venv integration, and the build-wheelhouse workflow shape. No wheel build runs
  in unit tests.

Docs: new "Pre-built wheelhouse" subsection in docs/installation.md under the Pi Zero 2 W notes
  explains expected impact (~15 min → ~2-3 min, ~400 MB → <200 MB RAM peak), the fallback behaviour,
  and how to opt out.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.39.8 (2026-04-11)

### Bug Fixes

- Install-in-progress lockfile blocks mid-install service start (JTN-607)
  ([#325](https://github.com/jtn0123/InkyPi/pull/325),
  [`c4bb605`](https://github.com/jtn0123/InkyPi/commit/c4bb605728ad7a019bd7867e4dd8160c1f9f92cb))

Defense-in-depth for JTN-600. install.sh creates /var/lib/inkypi/.install-in-progress near the top
  and removes it only after all install steps succeed. inkypi.service now has an ExecStartPre that
  refuses to start while the lockfile exists, so even a manual systemctl start or a systemd
  auto-restart cannot thrash the Pi mid-install. On failure exit the lockfile is deliberately left
  in place, forcing the user to rerun install.sh (or manually rm the file) before the service can
  start.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.39.7 (2026-04-11)

### Bug Fixes

- Api-keys placeholder clobbers real keys + Save button below fold (JTN-598, JTN-599)
  ([#315](https://github.com/jtn0123/InkyPi/pull/315),
  [`f08ea99`](https://github.com/jtn0123/InkyPi/commit/f08ea99b787873efbf7b9df799d539d18d7e1d08))

* fix: api-keys placeholder clobbers real keys + Save button below fold (JTN-598, JTN-599)

## JTN-598 — Data destruction (Urgent)

The /settings/api-keys template pre-filled each configured secret input with 32 literal U+2022 BLACK
  CIRCLE characters in the `value=` attribute as a faux password mask. Because the chars are real
  text, any user who clicked into the field and typed/pasted would append to (or replace) the
  bullets. On Save, `new FormData(form)` serialized the current input value — often `••••…•••<user
  text>` or just 32 bullets if untouched — and POSTed it to /settings/save_api_keys. The backend had
  no placeholder check and wrote the bullet-polluted string verbatim, silently overwriting the real
  API key.

JTN-382 reported the same underlying issue and was closed after switching type=text → type=password.
  The fix only addressed the cosmetic half; the literal-bullet value= pre-fill stayed and is the
  root cause of this data-destruction bug.

### Fix

Frontend — stop pre-filling value= with bullets: - api_key_card.html macro: `value=""` + placeholder
  "(leave blank to keep current)" for configured providers. Fields start genuinely empty. -
  api_keys_page.js: removed the `maskPlaceholder` constant and the `clearField` / clear-button dead
  code (no bullets means nothing to clear). updateConfiguredStatus now clears the field and updates
  the placeholder instead of re-filling with bullets. - api_keys.html: removed maskPlaceholder from
  the boot config, updated page subtitle and info-banner text to match the new UX.

Backend — defense-in-depth in /settings/save_api_keys: - Reject any posted value that is solely
  U+2022 characters. Logs a warning and reports skipped keys in a new `skipped_placeholder` field in
  the JSON response. Protects stale cached pages and any client that still sends the legacy bullet
  string.

## JTN-599 — Save button below the fold on short laptops

At viewport heights of 600–860px (covers 1280x768, 1366x768, 1280x800 — the most common laptop
  resolutions), the Save button sat at y≈769 with no visible scroll affordance. Even real mouse
  clicks at the button's coordinates hit nothing because the point is outside the viewport.

_responsive.css: new `@media (max-height: 860px)` rule pins `.settings-panel > .buttons-container`
  and `.api-keys-frame .buttons-container` sticky at `bottom: 8px`. Extends the existing mobile
  (max-width: 768px) sticky rule to cover short-but-wide laptop screens. Same fix also addresses
  JTN-572 (Settings page fold issue).

## Tests (+14 new)

tests/integration/test_api_keys_routes.py — +10 regression tests: - Empty value preserves existing
  key (the "leave blank" contract) - Pure-bullet value is rejected, existing key preserved, response
  reports skipped_placeholder - Mixed real+bullet values: real ones save, bullets are rejected -
  Mixed-content values ("abc•••") save normally (rejection is pure-placeholder only) - Normal save
  response omits the skipped_placeholder field (forward-compatible response shape) - Rendered page
  HTML has no U+2022 chars in any value="..." attribute - Configured fields render the "leave blank
  to keep current" placeholder, unconfigured fields keep the "Enter <provider> API key" placeholder
  - Static checks: api_keys_page.js no longer references `maskPlaceholder` or a 4+ bullet sequence,
  api_keys.html and api_key_card.html macro have no bullet sequences, macro still renders `value=""`
  - Static check: _responsive.css has the `max-height: 860px` rule scoped to `.api-keys-frame
  .buttons-container`

tests/integration/test_api_keys_pages_more.py: - Replaced the JTN-215 clear-button-tooltip test with
  a JTN-598 test asserting the clear button is removed entirely (fields start blank, nothing to
  clear).

Test count: 3219 → 3226 passing. 2 pre-existing pyenv-env failures (test_plugin_registry) unrelated
  to this change.

## Not touched

- src/config/device_dev.json was already modified when the session started; left alone.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* fix: address CodeRabbit review comments on JTN-598 fix

## Actionable comments from CodeRabbit (PR #315)

### 1. Backend — strip whitespace before bullet-placeholder check
  `src/blueprints/settings/_config.py`: the pure-bullet rejection check only called `set(value)`
  directly, so a value like `" •••• "` (bullets with leading/trailing whitespace) would bypass the
  defense-in-depth check and be written to .env. Now strips whitespace first, and a whitespace-only
  submission is treated as "empty/unchanged" just like a genuinely empty field.

### 2. Frontend JS — handle skipped_placeholder in save response
  `src/static/scripts/api_keys_page.js`: `saveManagedKeys` previously treated every resp.ok as full
  success and ignored the backend's `skipped_placeholder` field. Now shows a warning modal listing
  the skipped keys so users know which fields were rejected and need to be retyped. Still runs
  `updateConfiguredStatus` for the keys that *were* updated.

### 3. Frontend JS — delete button placed in wrong DOM container
  `src/static/scripts/api_keys_page.js`: `addDeleteButton` and `removeDeleteButton` walked up from
  `#<section>-status` via `.parentElement`, landing on `.api-key-card-head` — but the Delete button
  actually lives inside `.api-key-actions` (the input row). Adding from script would misplace the
  button next to the status line, and removing would leave stale buttons because the remove selector
  didn't find them in the head container.

Now uses `.closest(".api-key-card")` to walk up to the card, then queries `.api-key-actions` for the
  correct container. Also scopes the selector to `[data-api-action="delete-key"]` so it doesn't
  accidentally match other buttons that happen to use the `.delete-button` class.

### 4. Test lint — split combined assertions (PT018) `tests/integration/test_api_keys_routes.py`: 6
  occurrences of `assert spec and spec.loader` split into two separate assertions each. Better
  failure diagnostics and satisfies the PT018 rule.

### 5. Test lint — ambiguous × → plain x (RUF002) `tests/integration/test_api_keys_routes.py`:
  replaced `1280×800, 1366×768, 1280×768` (U+00D7 MULTIPLICATION SIGN) with plain `x` in the
  docstring of the sticky-CSS regression test.

## New regression tests (+2)

- `test_save_api_keys_whitespace_padded_bullets_are_rejected`: posting `" •••••••••••••••• "` must
  still be rejected and reported in `skipped_placeholder`, existing key preserved. -
  `test_save_api_keys_whitespace_only_is_treated_as_unchanged`: posting `" \t "` must leave the
  existing key alone and NOT appear in `skipped_placeholder` (whitespace-only is "empty/unchanged",
  not "rejected placeholder").

## Test results

- 3338 passing (was 3336 before these fixes — +2 new tests) - 2 pre-existing unrelated pyenv
  failures in test_plugin_registry - scripts/lint.sh: ruff/black/shellcheck/mypy-strict all green

* refactor: reduce saveManagedKeys complexity + hoist delete-button helpers (Sonar)

SonarCloud flagged 3 new issues on PR #315 after the CodeRabbit follow-up:

1. javascript:S3776 (Critical) — src/static/scripts/api_keys_page.js:98 `saveManagedKeys` cognitive
  complexity 17, threshold 15. Fix: extracted two small helpers so the orchestration is linear — -
  `handleManagedSaveSuccess(result)` owns the success-path branching (skipped_placeholder vs normal
  success + updateConfiguredStatus call) - `finalizeSaveButton(saveBtn, savedOk)` owns the
  save-button cleanup path and is reused by saveGenericKeys too, deduplicating the
  `saveBtn.textContent = "Save"` / markClean / re-enable logic `saveManagedKeys` is now a
  straight-line try/catch/finally.

2. javascript:S7721 (Major) — api_keys_page.js:64 (addDeleteButton) 3. javascript:S7721 (Major) —
  api_keys_page.js:87 (removeDeleteButton) Both helpers don't close over any state from
  `createApiKeysPage` (they only touch the DOM), so Sonar wants them at the outer IIFE scope. Fix:
  hoisted them out of `createApiKeysPage` to the module scope just inside the IIFE. Callers inside
  `createApiKeysPage` continue to resolve them via lexical scope.

No behavior changes. All 24 api-keys tests still pass; scripts/lint.sh green
  (ruff/black/shellcheck/mypy-strict).

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.39.6 (2026-04-11)

### Bug Fixes

- Add --no-cache-dir to pip install for SD + RAM savings (JTN-602)
  ([#321](https://github.com/jtn0123/InkyPi/pull/321),
  [`bfffa69`](https://github.com/jtn0123/InkyPi/commit/bfffa69053c2f0367a682ddd2153c4212e3f43ff))

Pip's wheel and HTTP cache (~/.cache/pip/) reaches 200-400 MB on a Pi Zero 2 W but provides zero
  benefit: pip runs once per install cycle and the venv is rebuilt from scratch on reinstall. Adding
  --no-cache-dir to all three call sites in create_venv() saves ~200 MB of SD card space and ~50 MB
  of RAM during install.

Also adds two unit tests to assert --no-cache-dir is present on every pip install invocation in
  install.sh and inside create_venv() specifically.

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>


## v0.39.5 (2026-04-11)

### Bug Fixes

- Surface clock plugin preview errors + fix silent failure (JTN-341, JTN-318)
  ([#324](https://github.com/jtn0123/InkyPi/pull/324),
  [`95ec400`](https://github.com/jtn0123/InkyPi/commit/95ec400c82af71d682d7ab8572b978b39157a0eb))

Root cause (JTN-341): the direct `_update_now_direct` code path (used when the background refresh
  task is not running, e.g. dev mode, web-only mode, first request after boot, or when the worker
  crashed) called `display_manager.display_image()` without the `history_meta` kwarg. As a result
  the history sidecar JSON was written with only `refresh_time` and no `plugin_id`. The
  `/plugin_latest_image/<plugin_id>` endpoint filters by `meta.get("plugin_id") == plugin_id`, so
  the lookup always 404'd and the "Latest from this plugin" card stayed empty — even though the
  image was generated and saved correctly. Verified by reproducing against the dev server before and
  after the fix.

This bug is the lead case of a 14-issue cluster (JTN-333, 341-346, 366-375) all reporting the same
  symptom across different plugins. Fixing the shared code path resolves the entire cluster.

Changes:

- `_update_now_direct` now builds a `history_meta` dict containing `refresh_type`, `plugin_id`,
  `playlist`, and `plugin_instance` (mirroring the structure the background worker writes in
  `refresh_task.task._push_to_display`) and passes it through a new `_safe_display_image` helper
  which tolerates older test stubs that do not accept the `history_meta` kwarg. - Bonus (JTN-318):
  exception exposure hardening in `plugin.py`. * `RuntimeError` from `generate_image` keeps its
  user-facing message (plugins raise RuntimeError precisely to author user-visible copy, e.g. "NASA
  API Key not configured."), but the message is now passed through `sanitize_response_value` and the
  failure is logged via `logger.exception` instead of `logger.warning` so full stacktraces reach
  Loki/Sentry. * Unexpected (non-RuntimeError) exceptions no longer leak `str(exc)` to the HTTP
  response; they return a generic "internal error" message with `logger.exception` capturing the
  full traceback. * `Plugin '{plugin_id}' not found` now runs through `sanitize_response_value` to
  prevent reflected XSS via attacker-controlled plugin IDs. - New helper
  `_push_update_now_fallback_from_current_exception` keeps the fallback error-card rendering path
  intact without requiring callers to capture the exception into a local variable (which would make
  it tempting to embed raw `str(exc)` in the JSON response).

Tests:

- New regression suite `tests/integration/test_jtn_341_clock_preview.py`: *
  `test_clock_update_preview_populates_latest_plugin_image` — end-to-end test that POSTs to
  `/update_now` with default Clock settings and asserts the history sidecar contains
  `plugin_id=clock` and that `/plugin_latest_image/clock` returns 200 with an image payload. Uses
  the REAL `DisplayManager._save_history_entry` so the full pipeline is exercised. *
  `test_clock_update_preview_runtime_error_returns_400_and_logs` — asserts RuntimeError from a
  plugin yields a 400 with the plugin-authored message preserved AND `logger.exception` is called. *
  `test_clock_update_preview_unexpected_exception_returns_500_and_logs` — asserts ValueError
  containing a secret marker is NEVER echoed to the client, response is 500 with generic message,
  and `logger.exception` captures the full traceback. - Updated `test_update_now_happy.py` to assert
  the new `history_meta` contract (plugin_id must flow through to `display_image`). - Updated
  `fake_display_image` stubs in `test_update_now_happy.py` and `test_refresh_task_interval.py` to
  accept the `history_meta` kwarg.

Manual verification on the dev server confirms that after clicking "Update Preview" on
  `/plugin/clock`, the "Latest from this plugin" card now populates immediately. Before the fix the
  endpoint returned 404; after the fix it returns a 92KB PNG.

Fixes JTN-341 Addresses JTN-318 exception exposure patterns in plugin.py Likely resolves cluster:
  JTN-333, JTN-342, JTN-343, JTN-344, JTN-345, JTN-346, JTN-366, JTN-367, JTN-368, JTN-369, JTN-370,
  JTN-371, JTN-372, JTN-373, JTN-374, JTN-375 (user verifies each independently)

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.39.4 (2026-04-11)

### Bug Fixes

- Prevent open redirect in HTTPS upgrade middleware (JTN-317)
  ([#317](https://github.com/jtn0123/InkyPi/pull/317),
  [`4f3f45b`](https://github.com/jtn0123/InkyPi/commit/4f3f45bb3a548b7965eb51aeb20df2700982fa1d))

* fix: prevent open redirect in HTTPS upgrade middleware (JTN-317)

The _redirect_to_https before_request hook rebuilt the redirect URL from request.url, which echoes
  the caller-supplied Host header. With INKYPI_FORCE_HTTPS=1, a request with a spoofed Host:
  evil.com would produce Location: https://evil.com/, an open-redirect flagged by CodeQL
  py/url-redirection (alert #52).

Validate request.host against an allow-list (configurable via INKYPI_ALLOWED_HOSTS, defaulting to
  inkypi.local, localhost and 127.0.0.1) before emitting the redirect. Unknown hosts abort 400
  instead of being reflected in a Location header.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* fix: rebuild HTTPS redirect URL from validated host (JTN-317)

CodeQL still flagged the original py/url-redirection site because request.url is built from the
  untrusted Host header and its taint doesn't propagate through the allow-list check. Rebuild the
  Location target from the (now validated) host plus request.full_path so the Host header never
  reaches the Location header.

Also tighten test assertions to use exact equality instead of startswith(), avoiding CodeQL's
  incomplete-URL-substring-sanitization warning on the test file itself.

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.39.3 (2026-04-11)

### Bug Fixes

- Default waitress threads to 2 for Pi Zero 2 W (JTN-603)
  ([#320](https://github.com/jtn0123/InkyPi/pull/320),
  [`1c66866`](https://github.com/jtn0123/InkyPi/commit/1c66866315a2ff2d584053614880d2b8ddc88263))

Replace hardcoded threads=4 with _get_web_threads() that defaults to 2, saving ~50-100 MB idle RSS
  on Pi Zero 2 W. Configurable via INKYPI_WEB_THREADS env var; invalid values fall back to 2,
  zero/negative clamped to 1. Adds 7 unit tests covering all env var paths.

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>

- Validate weather plugin latitude/longitude range (JTN-354)
  ([#323](https://github.com/jtn0123/InkyPi/pull/323),
  [`47aae5c`](https://github.com/jtn0123/InkyPi/commit/47aae5c965c00ea9811537adafd92ff15e67807b))

Weather plugin accepted out-of-range coordinates (e.g. latitude=999.999) and persisted them, failing
  later inside generate_image far from where the user could correct the input. Add validate_settings
  to reject values outside [-90, 90] and [-180, 180] at save time, and tighten the map widget inputs
  to type=number with min/max/step constraints.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.39.2 (2026-04-11)

### Bug Fixes

- Disable inkypi.service during install to prevent thrash loop (JTN-600)
  ([#319](https://github.com/jtn0123/InkyPi/pull/319),
  [`7314c5c`](https://github.com/jtn0123/InkyPi/commit/7314c5c8e1ba9f9b52e6549e0b4abfee05d249e9))

On a real Pi Zero 2 W (2026-04-10), install.sh stopped but did not disable inkypi.service. systemd
  auto-restarted the half-installed service mid-pip-install, hit ModuleNotFoundError: flask, entered
  Restart=on-failure loop, and caused a memory-thrash cascade that required a hard power cycle to
  recover.

Modify stop_service() to also call `systemctl disable` with a 2>/dev/null||true fallback so the
  service cannot be restarted during the ~15 min install window. install_app_service() already calls
  `systemctl enable` at the end, restoring the service to enabled state after install completes.

Add 3 structural tests to test_install_scripts.py asserting the disable call is present in
  stop_service(), the re-enable call is present in install_app_service(), and the disable call has
  an error-tolerant fallback.

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>


## v0.39.1 (2026-04-11)

### Bug Fixes

- Add OOMScoreAdjust=500 to inkypi.service to preserve sshd during OOM (JTN-601)
  ([#316](https://github.com/jtn0123/InkyPi/pull/316),
  [`f3edbc9`](https://github.com/jtn0123/InkyPi/commit/f3edbc91709133593625a289e2021804749c3d4e))

On a real Pi Zero 2 W during install-time memory thrash, earlyoom was killing sshd and making the Pi
  unreachable (required hard power cycle). Setting OOMScoreAdjust=500 makes inkypi the preferred OOM
  victim so we can still SSH in to debug.

Positive value is intentional: sshd/systemd-journald run at -500 or -1000 by default, so a +500 bias
  on inkypi means the kernel picks it first. A negative value would protect inkypi and sacrifice
  sshd — exactly the opposite of what we want.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.39.0 (2026-04-11)

### Features

- 512 MB memory-cap install smoke test for Pi Zero 2 W (JTN-536)
  ([#307](https://github.com/jtn0123/InkyPi/pull/307),
  [`85b0143`](https://github.com/jtn0123/InkyPi/commit/85b0143857a67a86a6e32a7e64c8f85e535b74a7))

* feat: add 512 MB memory-cap install smoke test for Pi Zero 2 W (JTN-536)

Add scripts/test_install_memcap.sh which runs install.sh inside a 512 MB-capped arm64 Docker
  container matching Pi Zero 2 W constraints, then boots the web service and probes /healthz, /,
  /playlist, and /api/plugins to assert the server comes up healthy under the same RAM budget a real
  Pi experiences.

Add install-smoke-memcap CI job with QEMU arm64 emulation and add it to the ci-gate needs list so
  any OOM regression during pip install or server boot blocks merge automatically.

Closes JTN-536

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* fix: invoke install.sh via bash to handle 100644 git mode (JTN-536)

install.sh is stored as 100644 in git (no execute bit), so Docker COPY preserves that — meaning
  './install.sh' fails with permission denied. Override the CMD to use 'bash install.sh' explicitly.

* fix: restructure memcap test — pip-only arm64 Phase 2, native Phase 3 (JTN-536)

Phase 2: test pip install of requirements.txt under arm64 + 512 MB cap (the actual JTN-528
  regression mode — OOM kill of pip). Uses the existing sim image with pre-built arm64 wheels from
  PyPI; no full install.sh run needed since that requires Pi hardware shims (config.txt, systemd,
  etc.).

Phase 3: start the web server in a native Python container under 512 MB cap and probe /healthz, /,
  /playlist, /api/plugins. Avoids QEMU overhead for the boot test while still enforcing the memory
  budget.

* fix: use python:3.12-slim arm64 for Phase 2 — no Python in sim image (JTN-536)

Dockerfile.sim-install only installs system tools (git, curl, gnupg) but not Python, so python3 was
  missing in the arm64 container. Switch Phase 2 to docker run python:3.12-slim --platform
  linux/arm64 mounted with the repo — Python is pre-installed, pip fetches arm64 binary wheels under
  the 512 MB cap.

Remove Phase 1 (sim image build) since it is no longer needed by Phase 2 or Phase 3; the sim image
  is still validated by sim_install.sh locally.

* fix: drop arm64 QEMU from CI — use native with 512 MB cap + build deps (JTN-536)

QEMU arm64 emulation caused compilation failures for Pi-specific packages that lack arm64 binary
  wheels (spidev, cysystemd, inky). Running the pip install natively (amd64) with the 512 MB cap is
  simpler, faster, and still catches the OOM regression — the memory budget is what matters, not the
  ISA.

Add --prefer-binary so pip uses binary wheels when available, and install build tools (gcc,
  libsystemd-dev, swig, etc.) for packages that must compile. Remove QEMU/Buildx CI steps since
  they're no longer needed.

* fix: pre-build Phase 3 image to avoid container exit before poll starts (JTN-536)

Previously Phase 3 ran apt-get + pip inside a detached container, causing the container to exit (on
  failure) or timeout (> 60s startup) before the healthz poll could see it. Instead, build a server
  image first (deps pre-installed) then detach only the server process — the container is
  immediately serving on start.

Also increase POLL_MAX to 180s, fix comment inconsistencies (arm64 refs), and add `|| true` guards
  on apt-get so missing packages don't abort the Phase 2 build step.

* fix: probe /api/health/plugins (not /api/plugins which does not exist) (JTN-536)

The spec mentioned /api/plugins but the actual route is /api/health/plugins. /api/plugins returns
  404.

* fix: assert /playlist=200, persist failure diagnostics to LOG_DIR (JTN-536)

- Change probe_route "/playlist" from "200|302" to "200" — /playlist is a direct GET handler
  (playlist.py:372-382), so a 302 is a real regression the smoke test should catch, not silently
  accept. - Add LOG_DIR="${TMPDIR:-/tmp}/inkypi-smoke-logs" at top of script and mkdir -p it so the
  directory always exists before any failure path runs. - In both failure blocks (SERVER_UP=0 and
  PROBE_FAILED!=0) pipe docker logs through tee to ${LOG_DIR}/container.log so the CI
  upload-artifact step actually captures useful diagnostics when the job fails.

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.38.0 (2026-04-11)

### Features

- Pip-compile hash-pinned lockfiles for supply-chain integrity (JTN-516)
  ([#308](https://github.com/jtn0123/InkyPi/pull/308),
  [`e1963e4`](https://github.com/jtn0123/InkyPi/commit/e1963e4a76d9077dac67f884a352f9c196035372))

* feat: add pip-compile hash-pinned lockfiles for supply-chain integrity (JTN-516, Grade F1)

Introduce requirements.in / requirements-dev.in source files compiled with pip-compile
  --generate-hashes. Every transitive dep is now verified with SHA-256 hashes before installation.
  install.sh passes --require-hashes to pip, rejecting tampered wheels from compromised mirrors. A
  new unit test prevents future regressions where a non-hashed file replaces the lockfile. Docs and
  CONTRIBUTING updated with the regen workflow.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* fix: restore pi-heif to all-platforms in requirements.in (fix pre-flash CI)

pi-heif has macOS/Windows wheels and must NOT carry the sys_platform=="linux" guard that was
  incorrectly added. preflash_validate.sh creates a temp venv with only requirements.txt; excluding
  pi-heif broke the import smoke check.

Also tighten psutil cap to >=7.0,<8 to match the originally-pinned 7.2.2.

* fix: manually append Linux-only packages with hashes to requirements.txt

pip-compile on macOS excludes sys_platform=="linux" packages (inky, cysystemd, gpiod, gpiodevice,
  smbus2, spidev) from the generated lockfile. preflash_validate.sh creates a temp venv with ONLY
  requirements.txt, so on Linux CI the import smoke check fails for cysystemd.

Manually append all six Linux-only packages and their transitive deps with full PyPI hashes and
  sys_platform=="linux" markers. pip skips these on macOS (marker is False) and verifies hashes on
  Linux.

Document the manual-append workflow in docs/dependencies.md.

* fix: add google-genai to requirements-dev.in; clarify pi-heif platform note

CodeRabbit review fixes: - Add google-genai>=1.14,<2 to requirements-dev.in to keep runtime deps in
  sync with requirements.in (was missing, could cause dev import errors) - Regenerate
  requirements-dev.txt to include google-genai lockfile entry - Clarify docs/dependencies.md:
  pi-heif is NOT Linux-only (has macOS/Windows wheels); only inky and cysystemd carry sys_platform
  == "linux" guards

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.37.2 (2026-04-11)

### Bug Fixes

- Reclaim /var/swap when zram is active (JTN-593)
  ([#313](https://github.com/jtn0123/InkyPi/pull/313),
  [`d2fb804`](https://github.com/jtn0123/InkyPi/commit/d2fb804fe999770d249002559745dd7ed4c8edb2))

Pi OS Trixie ships both zram-swap (active at /dev/zram0) and dphys-swapfile (leaves a ~425 MB
  /var/swap on the SD card). The file is dead weight because zram takes priority and dphys-swapfile
  never swaps to it. Add maybe_disable_dphys_swapfile() which detects an active zram device in
  /proc/swaps and, only then, disables and removes dphys-swapfile to reclaim ~425 MB. The function
  is a strict no-op on any system without /dev/zram active.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Documentation

- Cloud-init runcmd one-shot trap recovery (JTN-591)
  ([#312](https://github.com/jtn0123/InkyPi/pull/312),
  [`5aa7f4d`](https://github.com/jtn0123/InkyPi/commit/5aa7f4d5eccb3c6eb401c2e03d925e7652edc639))

Document the silent cloud-init runcmd skip that occurs when a user re-mounts an SD card and edits
  user-data after first boot. Observed on a real Pi Zero 2 W on 2026-04-10. Adds recovery steps
  (cloud-init clean --logs + reboot), a convenience helper script, and structural tests.

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>


## v0.37.1 (2026-04-11)

### Bug Fixes

- Wait for NTP clock sync before install (JTN-592)
  ([#314](https://github.com/jtn0123/InkyPi/pull/314),
  [`9a71278`](https://github.com/jtn0123/InkyPi/commit/9a71278960129933f56b9b0adc236f3f5afb15f1))

Pi Zero 2 W has no RTC battery; on boot the clock starts at the last fake-hwclock value (months
  stale), which can cause TLS cert validation failures when pip/apt fetch from HTTPS endpoints. Add
  wait_for_clock() to install.sh that polls timedatectl for up to 60s before package installs begin.
  On timeout it warns and proceeds rather than blocking the install (offline setups). Includes 4 new
  structural tests and Pi Zero 2 W documentation note.

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>

### Testing

- Add chaos tests for RefreshTask error-injection paths (JTN-512)
  ([#311](https://github.com/jtn0123/InkyPi/pull/311),
  [`7502716`](https://github.com/jtn0123/InkyPi/commit/7502716c88ad4751a87e110a91b48ecb5323e398))

Adds 11 tests covering subprocess hang timeout, output queue overflow, DisplayManager mid-display
  failure, and config reload during an active refresh — each asserting the fallback image path and
  circuit breaker behaviour introduced in PR #299 (JTN-499).

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.37.0 (2026-04-11)

### Features

- Add plugin render pipeline benchmarks (JTN-520)
  ([#306](https://github.com/jtn0123/InkyPi/pull/306),
  [`5e3e401`](https://github.com/jtn0123/InkyPi/commit/5e3e401dd94aa96725b9ebcb49c576835b465d19))

* feat: add plugin render pipeline benchmarks (JTN-520, Grade G3)

Add tests/benchmarks/test_plugin_render.py with three micro-benchmarks (bench_clock_render,
  bench_weather_render, bench_html_render) that measure the full plugin render pipeline — the path
  users wait on when clicking "Update Preview" — with all network I/O mocked and each completing in
  <1ms.

Add one-line note in docs/benchmarking.md referencing the new benchmarks.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* fix: align benchmark names in docs with actual pytest node IDs

Update the benchmarking.md note to use the real function names test_bench_clock_render /
  test_bench_weather_render / test_bench_html_render rather than the shorthand names listed
  initially.

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.36.0 (2026-04-11)

### Bug Fixes

- Separate watchdog heartbeat thread (JTN-596) ([#310](https://github.com/jtn0123/InkyPi/pull/310),
  [`6cc2c74`](https://github.com/jtn0123/InkyPi/commit/6cc2c74be9a8e5d4ebd8eb0186088e37ce272769))

Spawn a dedicated WatchdogHeartbeat daemon thread in RefreshTask.start() that pings systemd every
  WATCHDOG_USEC/2 seconds (default 30s), completely decoupled from the refresh cycle.

Previously _notify_watchdog() was called only once per loop in _run(), then _wait_for_trigger()
  blocked for up to plugin_cycle_interval_seconds (default 3600s). With WatchdogSec=120 in
  inkypi.service this caused systemd to SIGABRT the process at T+120s on every fresh install with an
  empty playlist, producing a restart loop (80+ restarts/hour observed on a real Pi Zero 2 W).

The heartbeat interval is auto-calculated from WATCHDOG_USEC (set by systemd when WatchdogSec= is
  configured), so it tracks the unit file without code changes. The thread wakes on
  condition.notify_all() so shutdown is responsive.

Adds 11 unit tests covering interval parsing, thread lifecycle, ping cadence, graceful shutdown, and
  the no-op path when cysystemd is unavailable.

Fixes: JTN-596 (chain bug with JTN-594)

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>

### Features

- Consistent input validation and log sanitization (JTN-501, Grade B5)
  ([#309](https://github.com/jtn0123/InkyPi/pull/309),
  [`03925d3`](https://github.com/jtn0123/InkyPi/commit/03925d3315ccef4c8c1d629942950ba3bd76e496))

Extends src/utils/form_utils.py with ValidationError, validate_int_range, sanitize_for_log alias,
  and validate_json_schema — making schema-backed validation available to all blueprints without
  extra dependencies.

Hardens src/blueprints/settings/_config.py to reject out-of-range image adjustment values
  (saturation/brightness/sharpness/contrast now bounded 0–10), invalid orientation and
  previewSizeMode enum values, and NaN/inf floats that were previously silently saved.

Adds 38 unit tests (tests/unit/test_input_validator.py) and 22 integration tests
  (tests/integration/test_validation_routes.py) covering valid paths, missing fields, wrong types,
  range violations, and enum enforcement. Test count: 3174 → 3272 (+98).

Closes JTN-501

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.35.0 (2026-04-11)

### Documentation

- Add Google-style docstrings to private helpers (JTN-524)
  ([#305](https://github.com/jtn0123/InkyPi/pull/305),
  [`2db0bab`](https://github.com/jtn0123/InkyPi/commit/2db0bab3c6f0840b0c43f846c76044829bc469ff))

Adds docstrings to all private helpers longer than ~5 lines or with non-obvious intent in
  image_utils.py, refresh_task/task.py, and refresh_task/worker.py. Also adds a one-line docstring
  norm to CONTRIBUTING.md. No logic changes. Ruff D rule enablement is deferred as a follow-up per
  the issue scope.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Features

- Expand mutmut paths_to_mutate to full directories (JTN-508)
  ([#302](https://github.com/jtn0123/InkyPi/pull/302),
  [`943f7d4`](https://github.com/jtn0123/InkyPi/commit/943f7d477cb12198f109a6172f4d205c6e9c2684))

* feat: expand mutmut paths_to_mutate to 4 full directories (JTN-508)

Widens mutation testing coverage from 3 individual files to entire src/app_setup/, src/blueprints/,
  src/utils/, and src/refresh_task/ directories so the nightly job covers ~95% of application logic.
  Updates test_mutmut_config.py EXPECTED_FILES and docs accordingly.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

* fix: address CodeRabbit review — harden mutmut scope validation

Update docs/mutation_testing.md "How to expand scope" example to use directory-level paths matching
  current policy. Harden test_mutmut_config.py to use exact set membership (not substring) and
  validate dir-vs-file type for each configured path.

---------

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>


## v0.34.0 (2026-04-11)

### Features

- Extract form sanitization helpers into shared form_utils module (JTN-496)
  ([#303](https://github.com/jtn0123/InkyPi/pull/303),
  [`b95e765`](https://github.com/jtn0123/InkyPi/commit/b95e765bbcb76e60817b77e2445eb2067f885e75))

* feat: extract form sanitization helpers to src/utils/form_utils.py (JTN-496, Grade A4)

Moves inline _sanitize_log, _sanitize_response_value, and _validate_required_fields from
  src/blueprints/plugin.py into a new pure-function module src/utils/form_utils.py, eliminating
  copy-paste risk across blueprints. Adds FormRequest dataclass, MissingFieldsError,
  validate_required, validate_plugin_required_fields, sanitize_log_field, and
  sanitize_response_value with full type annotations. Adds 47 unit tests in
  tests/unit/test_form_utils.py covering all helpers and edge cases.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* ci: re-trigger CI for JTN-496

* ci: force re-trigger CI (JTN-496)

* ci: ping CI runner (JTN-496)

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.33.0 (2026-04-11)

### Documentation

- Add HTTP performance guide and plugin session-adoption smoke tests (JTN-521, Grade G4)
  ([#304](https://github.com/jtn0123/InkyPi/pull/304),
  [`81bf6c9`](https://github.com/jtn0123/InkyPi/commit/81bf6c91e9ce87ee3ff0373dd7a864a691f38701))

- Creates docs/http_performance.md grounded in real file/line references: pool size rationale, TLS
  reuse on Pi Zero, default timeout (20 s via INKYPI_HTTP_TIMEOUT_DEFAULT_S), cache vs raw-session
  decision table, and a 5-item plugin author checklist. - Adds
  tests/unit/test_plugin_http_session_adoption.py: two smoke tests that patch get_http_session and
  assert it is called by wpotd and weather_api, confirming the shared session pool is used. - All
  plugins already use get_http_session(); no migration needed (comic_parser uses http_get() which
  wraps get_shared_session() — noted as an accepted exception in the doc).

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Features

- Enforce strict mypy on http_utils + security_utils (JTN-525)
  ([#301](https://github.com/jtn0123/InkyPi/pull/301),
  [`626369a`](https://github.com/jtn0123/InkyPi/commit/626369a5f13f6fdb88f71d9a26242ece8439f6c7))

* feat: enforce strict mypy on http_utils + security_utils (JTN-525, Grade I1)

Add a blocking mypy --strict check for src/utils/http_utils.py and src/utils/security_utils.py so
  type drift in these security/HTTP critical modules is caught in CI. The whole-codebase mypy run
  remains advisory.

- mypy.ini: add per-module strict = True blocks for the two modules - scripts/lint.sh: add blocking
  strict subset check; advisory run now prints a clear ⚠️ warning; exits non-zero only when strict
  subset fails - src/utils/http_utils.py: add return type annotations on json_error, json_success,
  json_internal_error; cast cache.get() result to avoid no-any-return; import FlaskResponse for
  union return type - docs/typing.md: escalation plan — strict module list, how to add yours,
  rationale for incremental approach

http_cache.py deliberately deferred from the starter set (JTN-493 recently refactored it; will join
  once it stabilizes). See PR body for details.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* fix: add types-requests to requirements-dev.txt for mypy strict CI

The new mypy --strict check on http_utils.py requires types-requests stubs to be installed. CI
  doesn't have them; adding the pinned version that already passes locally resolves the
  import-untyped error in CI.

* fix: correct mypy.ini module names and docs/typing.md markdown style

- mypy.ini: use utils.* (not src.utils.*) for per-module strict sections; with mypy_path=src, the
  importable names are utils.http_utils and utils.security_utils — the src.* prefix was ignored
  (CodeRabbit) - docs/typing.md: add blank lines around fenced code blocks in list items to satisfy
  MD031 markdownlint rule; also fix example module name to match the corrected utils.* convention
  (CodeRabbit)

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.32.0 (2026-04-10)

### Features

- Fallback error-card image + circuit-breaker persistence (JTN-499)
  ([#299](https://github.com/jtn0123/InkyPi/pull/299),
  [`25d7755`](https://github.com/jtn0123/InkyPi/commit/25d775527d7f80804c12b0e4e1f461a4f5f22d16))

* feat: fallback error-card image + circuit-breaker persistence (JTN-499, Grade B3)

When a plugin's generate_image() raises, the display no longer stays frozen on stale content. A
  human-readable error-card (plugin name, instance, error class, truncated message, timestamp) is
  rendered via the new `utils/fallback_image.render_error_image()` helper and pushed to the display
  immediately.

The same pattern is applied to the `update_now` direct-execution path in `blueprints/plugin.py` so
  preview-mode failures are visible on screen.

Circuit-breaker state (consecutive_failure_count, paused) is now persisted to `device.json` via
  `write_config()` on every failure and on recovery, surviving daemon restarts. A new
  `disabled_reason` field on PluginInstance is populated when a plugin is paused and cleared on
  recovery; it is included in `to_dict()` / `from_dict()` so the value round-trips through the
  config file.

Tests: - 15 new unit tests in tests/unit/test_plugin_failure_fallback.py - Updated
  tests/integration/test_refresh_cycle.py to assert the fallback is pushed (not absent) on plugin
  failure

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* refactor: extract _update_now_direct to reduce cognitive complexity (S3776)

Splits the direct-execution branch of update_now() into two focused helpers: _update_now_direct()
  and _push_update_now_fallback(). This drops the function cognitive complexity from 19 to ≤15 as
  required by SonarCloud S3776.

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.31.0 (2026-04-10)

### Features

- Accessor + reset_for_tests() for utils singletons (JTN-493)
  ([#298](https://github.com/jtn0123/InkyPi/pull/298),
  [`56715b0`](https://github.com/jtn0123/InkyPi/commit/56715b00f89a95f90f18eaa4ba615e7b917cb5fa))

* feat: add explicit accessors and reset_for_tests() to utils singletons (JTN-493)

Add get_http_session()/reset_for_tests() to http_client, get_http_cache()/reset_for_tests() to
  http_cache, and get_translations()/get_active_locale()/reset_for_tests() to i18n. Wire an autouse
  pytest fixture in conftest.py to scrub all three singletons between tests, eliminating
  order-dependent test pollution. src/inkypi.py and plugin_registry.py globals are intentionally out
  of scope (follow-up). Grade A1.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* test: add coverage for accessor and reset_for_tests() functions (JTN-493)

Cover the new get_http_cache(), reset_for_tests() (http_client/http_cache/i18n), get_translations(),
  and get_active_locale() helpers so the SonarCloud new-code coverage gate reaches >= 80%.

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.30.0 (2026-04-10)

### Features

- Add sim_install.sh + Dockerfile for local install.sh verification (JTN-532)
  ([#291](https://github.com/jtn0123/InkyPi/pull/291),
  [`2e5f934`](https://github.com/jtn0123/InkyPi/commit/2e5f93471a8035e6607572d68d50fbe648d8a543))

* feat: add sim_install.sh + Dockerfile for local install.sh verification (JTN-532)

Adds scripts/sim_install.sh and scripts/Dockerfile.sim-install so contributors can run
  install/install.sh end-to-end in an arm64 container that mimics the Pi Zero 2 W (512 MB RAM)
  without real hardware.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

* fix: address CodeRabbit review on sim_install.sh + Dockerfile (JTN-532)

- Dockerfile: combine raspi.list + apt-get update in single RUN layer and clean apt lists; expand
  sim-only warning comment for trusted=yes - sim_install.sh: reject extra positional arguments; wrap
  docker run in if/else so RUN_EXIT is always set regardless of set -e

---------

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>


## v0.29.0 (2026-04-10)

### Continuous Integration

- Enforce browser-smoke as required CI check via ci-gate job (JTN-510)
  ([#292](https://github.com/jtn0123/InkyPi/pull/292),
  [`2b2ed59`](https://github.com/jtn0123/InkyPi/commit/2b2ed597fd25c2d01cea4fe7da8b4b1ad6c13ee2))

* ci: add ci-gate job and enforce browser-smoke as required check (JTN-510)

- Add `ci-gate` summary job that needs lint, shellcheck, tests, sonarcloud, smoke, smoke-matrix,
  coverage-gate, security, and browser-smoke; the single gate name is what repo owner must mark as
  required in GitHub branch protection (steps documented in docs/development.md) - Expand
  CONTRIBUTING.md with a dedicated "Running Browser Tests Locally" section explaining SKIP_BROWSER
  purpose, when it is and isn't acceptable, and the exact command required for frontend-touching PRs
  - Update PR checklist (pull_request_template.md + CONTRIBUTING.md) with an explicit browser-test
  checkbox for src/static/** and src/templates/** changes - Add scripts/precommit_browser_warning.sh
  and wire it into .pre-commit-config.yaml as a warn-only local hook that fires when frontend files
  are staged with SKIP_BROWSER=1 set - Add precommit_browser_warning.sh to CI shellcheck/bash-syntax
  validation

Closes JTN-510

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

* docs: fix SKIP_BROWSER wording and repo path per CodeRabbit review

- CONTRIBUTING.md: clarify that SKIP_BROWSER defaults to unset and browser tests will fail (not
  skip) when Chromium is absent - docs/development.md: use fatihak/InkyPi (upstream) not fork path
  in the ci-gate branch protection step instructions

---------

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>

### Documentation

- Add Architecture Decision Records for 6 key design choices (JTN-522, Grade H1)
  ([#300](https://github.com/jtn0123/InkyPi/pull/300),
  [`85097f7`](https://github.com/jtn0123/InkyPi/commit/85097f7749ff1d5e4c3bcc8b792059d097c6952a))

Creates docs/adr/ with a template, README index, and 6 grounded ADRs covering subprocess plugin
  isolation, HTTP cache strategy, playlist scheduling, JSON config store, Waitress vs Gunicorn, and
  WebP on-the-fly encoding. Links index from docs/architecture.md. All rationale traced to actual
  src/ files and commit history.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Features

- Add InkyPiStore reactive store and migrate page state (JTN-502)
  ([#293](https://github.com/jtn0123/InkyPi/pull/293),
  [`6cdae29`](https://github.com/jtn0123/InkyPi/commit/6cdae29c11afa0d1ceac9edb5dd87de273d01ee9))

* feat: add InkyPiStore and migrate page state (JTN-502, Grade C1)

Introduces a lightweight reactive store (`store.js`) that provides a centralized, observable place
  for page-level state, eliminating scattered module-level variables and reducing polling/state race
  risk.

- `src/static/scripts/store.js`: new `createStore(initialState)` with `get`, `set` (object-merge or
  function updater), and `subscribe` (key- level, shallow-compare, returns unsubscribe). Exposed as
  `window.InkyPiStore` / `globalThis.InkyPiStore`. - `dashboard_page.js`: `lastImageHash` and
  `consecutiveFailures` now read/written via store instance; plain-var fallback for environments
  without store. - `plugin_form.js`: `initProgress` state (`t0`, `clockTimer`, `lastStepBase`)
  backed by store instance. - `settings_page.js`: `state` object proxied through store so all
  reads/writes flow through observable keys. - `tests/static/test_store_contract.py`: 12 new
  contract tests covering public API presence and per-file store usage.

No behavior change — pure refactor. `playlist.js` migration is deliberately deferred to the JTN-469
  sibling PR.

Closes JTN-502

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* fix: replace var with let/const in store and migrated files (JTN-502)

Addresses 2 SonarCloud S3504 issues: unexpected var declarations in dashboard_page.js and
  plugin_form.js. Also proactively modernises the same pattern in store.js for consistency.

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.28.5 (2026-04-10)

### Bug Fixes

- Validate cycle_minutes range (1-1440) on update_playlist and expose in to_dict (JTN-469)
  ([#295](https://github.com/jtn0123/InkyPi/pull/295),
  [`cfb599c`](https://github.com/jtn0123/InkyPi/commit/cfb599cb779ea6e2ca04104c6590c1d054580016))

Silent data loss occurred when cycle_minutes exceeded the HTML max of 1440 — the backend accepted
  any value and the template never read cycle_interval_seconds back into the edit modal. Backend now
  rejects out-of-range values with 400 + error body; frontend surfaces it via the existing
  handleJsonResponse toast path. Playlist.to_dict() now includes cycle_minutes derived from
  cycle_interval_seconds so the edit modal pre-fills correctly after save.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Documentation

- Add Plugin Development Troubleshooting section (JTN-523)
  ([#297](https://github.com/jtn0123/InkyPi/pull/297),
  [`9a5dade`](https://github.com/jtn0123/InkyPi/commit/9a5dadea537585f2fb5a5ddf4bef75ac30628569))

Adds a new "Plugin Development Troubleshooting" top-level section to docs/troubleshooting.md
  covering six common runtime failure classes: API key validation failures, plugin fetch timeouts
  (Newspaper/Comic/RSS), OutputDimensionMismatch errors, memory pressure on Pi Zero, Screenshot
  plugin failures (Chromium not found/sandbox), and Jinja2 template render errors. Each subsection
  is grounded in actual source classes (src/utils/output_validator.py, src/utils/image_utils.py,
  src/utils/http_utils.py). Adds a one-line cross-link in docs/building_plugins.md pointing to the
  new section.

Note: source-code cross-link inside the OutputDimensionMismatch raise site
  (src/utils/output_validator.py) was intentionally skipped — that file is owned by sibling PR
  JTN-499.

Closes JTN-523

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Add pre-commit install subsection to development guide (JTN-527, Grade I3)
  ([#296](https://github.com/jtn0123/InkyPi/pull/296),
  [`1ea7272`](https://github.com/jtn0123/InkyPi/commit/1ea7272c0e3b4e25e0d6db89dd688d8e90af4d04))

Add "Install pre-commit hooks (recommended)" subsection in the Setup section of docs/development.md,
  documenting the `pre-commit install` command, what hooks run (ruff, mypy, gitleaks,
  conventional-commit, etc.), and a bypass note for `git commit --no-verify`.

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>

- Add profiling guide for benchmark suite and cProfile/py-spy (JTN-526, Grade I2)
  ([#294](https://github.com/jtn0123/InkyPi/pull/294),
  [`3bce70d`](https://github.com/jtn0123/InkyPi/commit/3bce70d66b66077cafd02b056a89728d5f018e09))

Adds docs/profiling.md covering when to profile, running pytest-benchmark locally,
  --benchmark-save/compare/compare-fail, scripts/test_profile.sh behaviour, cProfile+snakeviz,
  py-spy, and a decision matrix for choosing the right tool.

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>


## v0.28.4 (2026-04-10)

### Bug Fixes

- Add shellcheck to lint.sh and OS codename parity test (JTN-531)
  ([#286](https://github.com/jtn0123/InkyPi/pull/286),
  [`b3fe54f`](https://github.com/jtn0123/InkyPi/commit/b3fe54f8bb5c01de5d132b0b8a4b38d3dc3951ec))

* fix: add shellcheck to lint.sh and OS codename parity test (JTN-531)

- Add shellcheck step (blocking, severity=warning) to scripts/lint.sh covering install/*.sh and
  scripts/*.sh; gracefully skips locally when binary is absent, fails in CI if missing - Add
  test_zramswap_regex_matches_codename_comment_parity to assert the get_os_version comment and
  zramswap regex always share the same Debian version integers, so adding a new release to one
  without the other causes immediate CI failure - Fix pre-existing ruff invalid-syntax errors in
  scripts/compare_icons.py (escaped quotes inside f-strings, Python <3.12 incompatible)

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* refactor: use dynamic glob discovery for shellcheck file list

Replace hardcoded SHELLCHECK_FILES array with nullglob glob expansion of install/*.sh and
  scripts/*.sh so new scripts are automatically covered without manual list maintenance.

Addresses CodeRabbit review comment.

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Atomic config RMW — add Config.update_atomic (JTN-498)
  ([#289](https://github.com/jtn0123/InkyPi/pull/289),
  [`7991328`](https://github.com/jtn0123/InkyPi/commit/7991328d139a79f33dbd49d492d2b763b030c499))

* fix: add Config.update_atomic to guard full RMW cycle under lock (JTN-498, Grade B2)

Add `Config.update_atomic(update_fn)` that holds `_config_lock` across the entire read → mutate →
  write cycle, preventing concurrent threads from clobbering each other's playlist edits.

Migrate key RMW callsites in playlist.py and plugin.py to use `update_atomic` instead of bare
  mutation + write_config(). Update the two integration tests that mocked `update_value` to mock
  `update_atomic` instead. Add a 20-thread concurrent regression test that verifies all plugin
  additions land in the final config without any being silently dropped.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

* refactor: extract _validate_instance_name helper to reduce cognitive complexity (S3776)

Reduces add_plugin() cognitive complexity from 16 to ≤15 per SonarCloud rule S3776.

---------

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>

- Clear stale error toasts and auto-dismiss on new save attempt (JTN-464)
  ([#287](https://github.com/jtn0123/InkyPi/pull/287),
  [`de95a98`](https://github.com/jtn0123/InkyPi/commit/de95a98ec8bf04dab2f3304f4be1a879891957d5))

- Dismiss existing error toasts before showing a new one, preventing stale validation messages from
  stacking up across save attempts. - Add TOAST_ERROR_DURATION_MS (8 s) constant so error toasts
  auto-dismiss instead of requiring a manual × click. - Keep the × close button and success-toast
  behaviour unchanged.

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>

- Escape closes #scheduleModal and focus moves into it on open (JTN-461, JTN-463)
  ([#288](https://github.com/jtn0123/InkyPi/pull/288),
  [`3de2f5a`](https://github.com/jtn0123/InkyPi/commit/3de2f5ab6c93fd2cd547e42612fef11132e66ec1))

* fix: Escape closes #scheduleModal and focus moves into it on open (JTN-461, JTN-463)

- JTN-461: add keydown listener in bindModalClose so pressing Escape dismisses #scheduleModal when
  it is visible, matching the pattern used by playlistModal and the history-page modals. - JTN-463:
  extend openModal to focus the first focusable element inside the modal on open (matching
  setModalOpen in playlist.js); track the trigger button in _lastModalTrigger and restore focus to
  it on close (WAI-ARIA best practice). - Add two static regression tests in
  test_modal_accessibility_guards.py to guard against future regressions.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

* fix: resolve Sonar S2486 and S2004 in plugin_page.js

- S2486: remove empty catch block — .focus() on a DOM element does not throw in practice; the
  try/catch was defensive but Sonar requires non-empty catch bodies. - S2004: replace per-element
  forEach/addEventListener loop for [data-open-modal] with a single delegated document click
  listener, reducing function nesting from 5 to 4 levels.

---------

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>

- Skip zram-tools when OS already provides zram swap (JTN-569)
  ([#285](https://github.com/jtn0123/InkyPi/pull/285),
  [`b621d2b`](https://github.com/jtn0123/InkyPi/commit/b621d2bef6610e14ac761fbe7200b61761496e25))

* fix: skip zram-tools install when OS already provides zram swap (JTN-569)

On Pi OS Trixie, the preinstalled zram-swap package configures /dev/zram0 at boot. Installing
  zram-tools on top causes mkswap to fail with "is mounted" and leaves zramswap.service in a failed
  state. Add a /proc/swaps guard at the top of setup_zramswap_service() that exits early when zram
  swap is already active, preventing the conflict.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

* test: assert guard ordering in zram skip test (JTN-569)

Strengthen the test to verify that the /proc/swaps guard appears before the apt-get install line,
  not just that both strings are present. This prevents false positives if the guard were ever moved
  below the install command.

---------

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>


## v0.28.3 (2026-04-10)

### Bug Fixes

- Cysystemd notify() requires Notification enum, not str (JTN-594)
  ([#290](https://github.com/jtn0123/InkyPi/pull/290),
  [`c98fd8d`](https://github.com/jtn0123/InkyPi/commit/c98fd8d79518dd979439073697c6b00a631f08d3))

* fix: cysystemd notify() requires Notification enum, not str (JTN-594)

cysystemd 2.0.1 requires notify() to receive a Notification enum value. Both call sites were passing
  raw strings ("READY=1", "WATCHDOG=1") and swallowing the resulting TypeError silently with `except
  Exception: pass`, causing every systemd-managed InkyPi install to stay in a restart loop
  indefinitely (service never reported READY, watchdog never fed).

- src/inkypi.py: import Notification and call notify(Notification.READY) - src/refresh_task/task.py:
  add string→enum adapter _sd_notify() so the legacy string-based call sites continue to work via
  the correct enum API - Replace all `except Exception: pass` blocks in both files with
  logger.exception() so future API breakage surfaces immediately in logs - Add
  tests/unit/test_systemd_notify.py with 10 new tests: structural AST checks that both files import
  Notification, mock-based behavioural tests that verify the adapter dispatches
  WATCHDOG=1→Notification.WATCHDOG and READY=1→Notification.READY, and graceful-degradation test for
  missing lib

Verified on real Pi Zero 2 W: service transitions activating→active(running) immediately after the
  fix, with "Notified systemd: READY=1" in the log.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

* test: fix test_sd_notify_is_none_when_cysystemd_unavailable on Python 3.12/3.13

The sys.meta_path finder approach was unreliable across Python versions. Switch to
  patch.dict(sys.modules, {'cysystemd': None, 'cysystemd.daemon': None}) which causes 'from
  cysystemd.daemon import …' to raise ImportError, properly testing the graceful-degradation path
  that sets _sd_notify = None.

---------

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>


## v0.28.2 (2026-04-10)

### Bug Fixes

- Install hardening + Pi Zero 2 W docs (JTN-534/537/538)
  ([#284](https://github.com/jtn0123/InkyPi/pull/284),
  [`2e22450`](https://github.com/jtn0123/InkyPi/commit/2e2245050947eaf7aa3d0f2037139add6413fce9))

JTN-534 — install network resilience: - pip install in install.sh now passes --retries 5 --timeout
  60 explicitly - update_vendors.sh: --retry-all-errors + --retry-delay 2 so transient curl write
  errors (exit 23, hit during JTN-528 sim run) actually retry - install.sh now propagates
  update_vendors.sh exit code instead of silently swallowing it via > /dev/null. Prevents
  half-installed CSS/JS bundles.

JTN-538 — backup test leaking .pre-restore-*.tar.gz into repo cwd: - _pre_restore_backup() takes an
  optional output_dir param, defaulting to the parent of config_dir (next to the data it protects,
  not random cwd) - Test now passes tmp_path so the artifact stays contained - .gitignore entry as
  belt-and-suspenders

JTN-537 — Pi Zero 2 W setup notes in docs/installation.md: - New section covering OS choice (Trixie
  now default), arm_64bit=1 requirement, ~15min first-boot install time, cloud-init log location,
  and clarification that the "Pi Zero W" troubleshooting section is for the original 32-bit Zero W,
  not the Zero 2 W.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.28.1 (2026-04-10)

### Bug Fixes

- Enable zramswap on Bullseye/Bookworm/Trixie (JTN-528)
  ([#283](https://github.com/jtn0123/InkyPi/pull/283),
  [`f30423e`](https://github.com/jtn0123/InkyPi/commit/f30423ed15522da12d8acbba4e55760fcd23c05c))

The OS version check at install/install.sh:391 only matched Bookworm (12). The default Pi OS image
  as of 2025-12-04 is now Trixie (13), so fresh installs on a Pi Zero 2 W silently skipped zramswap
  setup and OOM'd during the pip install of numpy/Pillow/playwright.

Extend the check to enable zramswap on Bullseye (11), Bookworm (12), and Trixie (13). zram-tools is
  available across all of these. Fix the "Trixe" typo in the get_os_version comment while we're
  here.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.28.0 (2026-04-09)

### Features

- Strict rate limits on mutating endpoints (JTN-513)
  ([#279](https://github.com/jtn0123/InkyPi/pull/279),
  [`a6b676a`](https://github.com/jtn0123/InkyPi/commit/a6b676ae977498251e4c812c8a135f7fd1beb42b))

* feat: strict rate limits on mutating endpoints (JTN-513)

Add /save_plugin_settings, /update_now, and /api/refresh/* to an intermediate token-bucket rate
  limit (10/min per IP) to prevent CPU saturation and e-ink panel abuse. This sits between the auth
  bucket (~3/min) and the global sliding window (60/min). The bucket is configurable via
  INKYPI_RATE_LIMIT_MUTATING env var. Also refactors the middleware to use small helper functions
  per bucket check, keeping cognitive complexity low (SonarCloud S3776).

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* fix: reduce cognitive complexity in rate limiting middleware (S3776)

Extract the three token-bucket checks into _apply_token_bucket_limits() so _rate_limit_mutations
  stays below SonarCloud's complexity threshold.

* fix: correct test fixtures for security_middleware rate-limit helpers (JTN-513)

- Add Flask app context to _apply_token_bucket_limits direct calls (make_response requires it) - Use
  _drained_bucket() helper that pre-drains the specific test IP key (TokenBucket.try_acquire always
  returns True for a new key, even with capacity=0) - Fix integration test to drain bucket via two
  sequential requests instead of relying on capacity=0 shortcut - Remove unused MagicMock/patch
  imports (ruff I001 fix)

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.27.2 (2026-04-09)

### Performance Improvements

- Cache device.json reads with mtime invalidation (JTN-519)
  ([#282](https://github.com/jtn0123/InkyPi/pull/282),
  [`cdbbc81`](https://github.com/jtn0123/InkyPi/commit/cdbbc81e0c764862ecdc88556c7a17d4958b7024))

* perf: cache device.json reads with mtime invalidation (JTN-519)

Add an mtime-based in-memory cache to Config.read_config() so repeated calls skip the JSON parse +
  jsonschema validation when the file has not changed on disk. The stat() call is still performed on
  every read but is ~100x cheaper than a full parse+validate cycle on slow microSD (Pi Zero).

- Track (mtime_ns, parsed_dict) on the Config instance, protected by the existing _config_lock
  (threading.RLock). - write_config() refreshes the cache after a successful file replace so the
  next read_config() is a cache hit with zero re-parse cost. - invalidate_config_cache() allows
  explicit invalidation for callers that write to the file outside of write_config(). - 11 new unit
  tests: cache hit, copy-not-reference, mtime invalidation, explicit invalidation, write cycle
  correctness, thread safety (concurrent reads + concurrent read/write), OSError fallback. - New
  benchmark test_config_read_cached added to test_perf_baseline.py.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* fix: include test_config_mtime_cache in coverage gate suite (JTN-519)

Add tests/unit/test_config_mtime_cache.py to the coverage_suite() in preflash_validate.sh so the new
  mtime-cache code paths in config.py are exercised during the CI coverage gate, pushing config.py
  line-rate above the 72% threshold.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.27.1 (2026-04-09)

### Bug Fixes

- Add aria-labelledby to playlist delete modals (JTN-468)
  ([#278](https://github.com/jtn0123/InkyPi/pull/278),
  [`fec0032`](https://github.com/jtn0123/InkyPi/commit/fec00325f65dcfcf97c78c1a7f08c2f43a42492b))

* fix: add aria-labelledby to playlist delete modals (JTN-468)

Add sr-only h2 headings with ids (deletePlaylistTitle, deleteInstanceTitle) inside
  deletePlaylistModal and deleteInstanceModal, and switch from aria-label to aria-labelledby to
  match the pattern used by playlistModal and refreshSettingsModal. Adds 9 regression tests.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

* test: strengthen aria-label absence assertions per CodeRabbit review

Add negative assertions to both no_aria_label_fallback tests to verify the modal opening tags do not
  contain aria-label= (only aria-labelledby=), preventing fallback regressions.

---------

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>


## v0.27.0 (2026-04-09)

### Features

- Set Content-Disposition headers on file download endpoints (JTN-515)
  ([#280](https://github.com/jtn0123/InkyPi/pull/280),
  [`e4343e3`](https://github.com/jtn0123/InkyPi/commit/e4343e3a52b88f8d48c188575844be31f05f01c9))

Add explicit Content-Disposition headers to all file-serving routes to defeat browser MIME-sniffing
  and make download intent unambiguous:

- download_logs: fix unquoted filename → `attachment; filename="inkypi_*.log"` -
  _cacheable_send_file (plugin images): add `inline; filename="..."` -
  /images/<plugin_id>/<filename>: add `inline; filename="..."` - maybe_serve_webp (PNG + WebP
  branches): add `inline; filename="..."` - get_current_image: add `inline;
  filename="current_image.png"`

X-Content-Type-Options: nosniff is already set globally by security middleware; no per-route change
  needed.

Add contract tests in tests/contracts/test_download_headers.py asserting attachment/inline
  disposition, quoted filenames, safe characters, and nosniff header presence.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.26.0 (2026-04-09)

### Features

- Validate uploaded image magic bytes (JTN-514) ([#281](https://github.com/jtn0123/InkyPi/pull/281),
  [`4950a46`](https://github.com/jtn0123/InkyPi/commit/4950a4659fe23448257ffc472382b300bcf5204f))

Add magic-byte verification and PIL.verify() to _validate_and_read_file so renamed binaries (e.g.
  evil.exe → evil.png) are rejected before they reach downstream PIL parsing. Closes the
  polyglot/type-confusion class.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.25.5 (2026-04-09)

### Bug Fixes

- Allow underscores/hyphens in playlist instance names (JTN-471)
  ([#275](https://github.com/jtn0123/InkyPi/pull/275),
  [`b457914`](https://github.com/jtn0123/InkyPi/commit/b457914341bbd2abec1f181121a207da0d5c9210))

* fix: allow underscores and hyphens in playlist instance names (JTN-471)

Instance name validation now accepts [A-Za-z0-9 _-] instead of alphanumeric+spaces-only, matching
  the naming convention the system itself uses for auto-generated instances (e.g.
  weather_saved_settings). Slashes, dots, and other path-unsafe characters remain rejected. Frontend
  JS and the HTML pattern attribute are updated to give immediate feedback, and the error message
  now accurately describes the allowed character set.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

* fix: update test_instance_name_invalid_chars to match new error message

The assertion was checking for "alphanumeric" which no longer appears in the updated validation
  error message. Updated to check for the full accurate wording.

* style: black format test_playlist_blueprint.py

---------

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>


## v0.25.4 (2026-04-09)

### Bug Fixes

- Add aria-labelledby to image preview lightbox modal (JTN-467)
  ([#274](https://github.com/jtn0123/InkyPi/pull/274),
  [`c5e1a23`](https://github.com/jtn0123/InkyPi/commit/c5e1a2337033eaceb16e83c694fcdcf8f5cbd94a))

The #imagePreviewModal was missing a proper accessible name on both the dashboard (dynamic modal via
  lightbox.js used aria-label instead of aria-labelledby) and plugin pages (aria-labelledby pointed
  to a non-existent id). Added <h2 id="imagePreviewTitle" class="sr-only"> inside the modal on
  plugin.html, and updated lightbox.js to create the same heading element and use aria-labelledby
  when dynamically creating the modal. Adds 5 regression tests.

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>


## v0.25.3 (2026-04-09)

### Bug Fixes

- Reject non-http(s) URL schemes in screenshot plugin (JTN-456)
  ([`3a98514`](https://github.com/jtn0123/InkyPi/commit/3a98514bfd99dde844d9cef5bf9e998972d59d5c))

fix: reject non-http(s) URL schemes in screenshot plugin (JTN-456)

- Reject non-http(s) URL schemes in screenshot plugin at save time (JTN-456)
  ([`61efb22`](https://github.com/jtn0123/InkyPi/commit/61efb2283945b8335ec65de593f6e50796ee719c))

- Add `validate_settings` hook to `BasePlugin` (returns None by default) - Override in `Screenshot`
  plugin to call `validate_url` before settings persist - Wire hook into
  `_save_plugin_settings_common` and `update_plugin_instance` so both save routes enforce scheme
  validation (http/https only) - Add `pattern="https?://.*"` and `type="url"` to screenshot URL
  field for client-side feedback via `settings_schema.html` pattern attribute support - Sanitize URL
  in log message to prevent log injection (S5145) - Add 12 integration tests covering javascript:,
  file://, data:, ftp: rejection and http/https acceptance across all three save routes

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.25.2 (2026-04-09)

### Bug Fixes

- Make skip link actually move focus to main (JTN-458)
  ([#276](https://github.com/jtn0123/InkyPi/pull/276),
  [`a0b7f24`](https://github.com/jtn0123/InkyPi/commit/a0b7f2464facd50abfabf73cfd77b9557c7f6e05))

Add tabindex="-1" to <main id="main-content"> in all page templates so activating the "Skip to main
  content" link moves keyboard focus into main rather than leaving it on body. Also adds a
  parametrized test asserting the attribute is present on every main page.

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>


## v0.25.1 (2026-04-09)

### Bug Fixes

- Add aria-pressed to logs panel toggle buttons (JTN-472)
  ([#273](https://github.com/jtn0123/InkyPi/pull/273),
  [`14359e7`](https://github.com/jtn0123/InkyPi/commit/14359e76555f74ad903e1a25d819abfa6d9e29cd))

Add aria-pressed="true" initial state to Auto-Scroll and Wrap toggle buttons in the settings logs
  panel, and update the JS click handlers (toggleLogsAutoScroll, toggleLogsWrap,
  initializeLogsControls) to keep aria-pressed in sync with the toggle state so screen readers can
  announce the pressed state without relying on text-label alone.

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>


## v0.25.0 (2026-04-09)

### Features

- Optional browser console message forwarder (JTN-481)
  ([#268](https://github.com/jtn0123/InkyPi/pull/268),
  [`091d92f`](https://github.com/jtn0123/InkyPi/commit/091d92f22fad6fb5559f21eca04c26417ac64f8f))

* feat: optional browser console message forwarder (JTN-481)

Add POST /api/client-log endpoint and client_log_reporter.js shim that forwards console.warn/error
  to the server. Opt-in via <meta name="client-log-enabled" content="1">; 50% sampling;
  self-disables after 5 failures; per-IP rate limit (cap=10, refill=1/s); CR/LF stripped (Sonar
  S5145); logs at WARNING so SecretRedactionFilter (JTN-364) applies.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

* fix: black formatting for client_log files

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* chore: remove leaked tarball files

* fix: modernize client_log_reporter JS for Sonar S3504/S6582/S7735

- var -> const/let - Use optional chaining for meta tag check - Compare sendBeacon result with ===
  false (avoid negated condition)

* fix: invert undefined check to clear Sonar S7735

* fix: exclude reporter scripts from Sonar CPD duplication check

The client_error and client_log reporters share intentional boilerplate (rate limiter, sendBeacon,
  CSRF helper) that is too small to refactor into a shared helper without adding more complexity
  than it removes.

* refactor: extract client report helper to reduce duplication

Move the body-size + rate-limit + JSON parse boilerplate from client_log.py into
  utils.client_endpoint.parse_client_report so the new endpoint does not duplicate the existing
  client_error.py code (Sonar new-code duplication gate <= 3%).

---------

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>

- Plugin instance config history and diff endpoint (JTN-479)
  ([#271](https://github.com/jtn0123/InkyPi/pull/271),
  [`bf566d6`](https://github.com/jtn0123/InkyPi/commit/bf566d61b417dc9442c3d72a3d5a53d7fa7cfd89))

* feat: plugin instance config history and diff endpoint (JTN-479)

Track per-instance settings changes in a JSONL log (capped at 100 entries). Expose GET
  /api/plugins/instance/<name>/history and GET /api/plugins/instance/<name>/diff for debugging
  config regressions. Hook record_change into update_plugin_instance and save_plugin_settings flows;
  fail-safe (logs, never blocks save). 24 tests added.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

* fix: sanitize instance_name in log messages (Sonar S5145)

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* fix: harden plugin history against CodeQL path injection + reflective XSS

- _safe_filename now strict-validates and raises on invalid input (CodeQL recognises full-match
  regex as a path-injection sanitizer) - _safe_instance_name in the blueprint returns the validated
  name; all downstream paths use the safe variant - Error messages no longer echo user input back
  (clears reflective XSS)

* fix: hash-based history filenames to clear CodeQL py/path-injection

CodeQL's taint analysis didn't recognise the regex full-match validator as a sanitizer. Replaced the
  user-name-derived filename with a sha256-hex digest that contains only [0-9a-f] characters and is
  recognised as opaque/safe by the analyser.

The original instance name is still preserved inside each JSONL record so 'history' and 'diff'
  endpoints continue to return human-readable data.

---------

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>


## v0.24.0 (2026-04-09)

### Features

- Api key validator CLI for plugin credentials (JTN-480)
  ([#270](https://github.com/jtn0123/InkyPi/pull/270),
  [`ffa1b78`](https://github.com/jtn0123/InkyPi/commit/ffa1b78096a93ef5890bd8b44d8d1173bb1c1694))

Add scripts/validate_api_keys.py that reads .env and device.json, probes 6 plugin APIs
  (OpenWeatherMap, OpenAI, Google AI, Unsplash, NASA APOD, GitHub) with minimal read-only requests,
  and reports OK/Invalid/Quota/NetworkError status per plugin. Includes 37 tests with requests_mock
  covering all status classifications and exit codes.

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>

- Read-only bearer token for monitoring endpoints (JTN-477)
  ([#269](https://github.com/jtn0123/InkyPi/pull/269),
  [`85e30a2`](https://github.com/jtn0123/InkyPi/commit/85e30a2d1f43abf2f4849089eacd43a4208e609f))

Add INKYPI_READONLY_TOKEN env var to enable a second auth path independent of PIN auth.
  GET/HEAD/OPTIONS requests to the allowlist (/api/health, /api/version/info, /api/uptime,
  /api/screenshot, /metrics, /api/stats) are accepted with a valid Authorization: Bearer header.
  Mutating methods and non-allowlist paths still require a PIN session. Token is stored as a SHA-256
  digest; hmac.compare_digest prevents timing attacks.

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>

- Subresource Integrity for vendored and CDN assets (JTN-478)
  ([#272](https://github.com/jtn0123/InkyPi/pull/272),
  [`b43b227`](https://github.com/jtn0123/InkyPi/commit/b43b2279b8f958f0c38f13c4c1d64dc8460b0f1b))

- Add src/utils/sri.py with compute_sri(), sri_for() (Jinja helper, cached), cdn_sri() (reads
  cdn_manifest.json), and init_sri() Flask wiring - Add src/static/cdn_manifest.json with SHA-384
  hashes for swagger-ui-css, swagger-ui-bundle, and chart-js CDN assets - Add
  scripts/update_cdn_sri.py to refresh CDN hashes when versions bump - Wire init_sri(app) into
  create_app() in src/inkypi.py - Register sri_for/cdn_sri on base_plugin Jinja env for plugin
  templates - Add integrity + crossorigin attrs to htmx (vendor), swagger-ui, chart.js tags - Add 24
  tests in tests/test_sri.py covering all helpers and the update script - Update conftest.py
  flask_app fixture to call init_sri

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.23.0 (2026-04-09)

### Features

- Client-side error forwarding endpoint /api/client-error (JTN-454)
  ([#265](https://github.com/jtn0123/InkyPi/pull/265),
  [`98db028`](https://github.com/jtn0123/InkyPi/commit/98db0282828e2e3d4aeaab8afb245c5918691f2b))

* feat: client-side error forwarding endpoint (JTN-454)

POST /api/client-error accepts JSON error reports from window.onerror and unhandledrejection
  handlers, validates schema, caps field sizes at 2KB/16KB, logs as WARNING (SecretRedactionFilter
  strips secrets), and rate-limits 5 tokens per IP at 0.5 refill/s. A new client_error_reporter.js
  wires up the browser side with 25% sampling, sendBeacon support, and self-disabling after 5
  failures.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

* fix: address Sonar findings on client error endpoint

- Drop redundant UnicodeDecodeError catch (subclass of ValueError) (S5713) - Strip CR/LF from logged
  report fields to prevent log injection (S5145) - JS: var -> const/let throughout (S3504) - JS:
  empty catch now records a soft failure instead of swallowing (S2486) - JS: explain Math.random
  sampling is non-security (S2245)

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* ci: re-trigger workflows after Sonar fix push

* fix: drop unused catch parameter to clear Sonar S2486

* fix: NOSONAR for Math.random sampling (S2245 false positive)

---------

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>


## v0.22.0 (2026-04-09)

### Features

- I18n scaffolding with gettext stubs and extractor (JTN-459)
  ([#267](https://github.com/jtn0123/InkyPi/pull/267),
  [`94e9937`](https://github.com/jtn0123/InkyPi/commit/94e99375a5c596a0f8eb166d75c3b12eaa484181))

* feat: i18n scaffolding with gettext stubs and extractor (JTN-459)

Add stdlib-only i18n foundation: src/utils/i18n.py with identity _() helper and init_i18n() Jinja2
  wiring, translations/en/messages.json with 26 English baseline strings, scripts/extract_strings.py
  to scan templates/Python for _() calls (with --check CI mode), and 12 tests covering all scaffold
  behaviours. No templates modified; no third-party deps added.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

* test: increase i18n coverage to clear Sonar 80% gate

Adds 9 more tests covering _load_locale error paths, init_i18n translation loading,
  extract_strings.main() output messages, and _scan_file OSError handling.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

---------

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>

- Validate plugin output dimensions before display (JTN-455)
  ([#266](https://github.com/jtn0123/InkyPi/pull/266),
  [`a8f94f7`](https://github.com/jtn0123/InkyPi/commit/a8f94f78208138c33ac593ab13550c98569d4e5f))

Add OutputDimensionMismatch exception and validate_image_dimensions helper in
  src/utils/output_validator.py. Wire validation in RefreshTask._perform_refresh between generate()
  and display push — mismatched dims log a clear error with plugin_id/expected/actual, mark plugin
  health red, and skip the display push for that tick without crashing the refresh loop. Auto-rotate
  by 90° when dims are transposed. Fix test_sse.py to use device resolution instead of 100x100.

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>


## v0.21.0 (2026-04-09)

### Features

- Image diff utility for history comparison (JTN-452)
  ([#264](https://github.com/jtn0123/InkyPi/pull/264),
  [`953746c`](https://github.com/jtn0123/InkyPi/commit/953746cdb0e0f1a94b233ffe446b05f255b5920b))

scripts/image_diff.py compares two PNG files and reports pixel difference count, percentage changed,
  max channel delta, and writes a visual diff PNG with changed pixels overlaid in red at 50% alpha.
  Supports --threshold, --summary-only, and --json flags.

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>


## v0.20.0 (2026-04-09)

### Features

- Add GET /api/screenshot endpoint (JTN-450) ([#263](https://github.com/jtn0123/InkyPi/pull/263),
  [`32ea818`](https://github.com/jtn0123/InkyPi/commit/32ea81800b2a670a0e8850dd28957b869a738c93))

Returns the current display image (processed first, fallback to current) as PNG or WebP via content
  negotiation. Supports conditional GET with If-Modified-Since/304, Cache-Control: no-cache
  must-revalidate, and Last-Modified header. Reuses maybe_serve_webp from JTN-302. No auth required
  so the endpoint is embeddable in dashboards and status pages.

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>


## v0.19.0 (2026-04-09)

### Features

- Csp violation report endpoint ([#259](https://github.com/jtn0123/InkyPi/pull/259),
  [`8ff10fd`](https://github.com/jtn0123/InkyPi/commit/8ff10fd65f0fe5b71c807a7bc26626fc98594965))

Add POST /api/csp-report blueprint that accepts legacy application/csp-report and modern
  application/json payloads, logs violations as WARNING with redacted source URLs, and returns 204
  No Content. Wire a report-uri directive into the existing CSP header (additive, no refactor). No
  auth required so browsers can reach the endpoint unconditionally; per-IP rate limiting via
  SlidingWindowLimiter. Includes 12 tests covering all content-types, caplog assertions, URL
  redaction, 204 on empty/invalid body, 405 on GET, and deduplication of the report-uri directive.

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>


## v0.18.0 (2026-04-08)

### Features

- Plugin dry-run CLI for offline rendering ([#261](https://github.com/jtn0123/InkyPi/pull/261),
  [`fe216d0`](https://github.com/jtn0123/InkyPi/commit/fe216d0bcca0d8205c1a1b667d3a550a346d8520))

* feat: plugin dry-run CLI for offline rendering

Add scripts/dry_run_plugin.py — loads any plugin by ID, calls generate_image() via a
  _MockDeviceConfig stub, and saves the PNG locally. No Flask, no display driver, no refresh task
  needed. Supports --plugin, --output, --width, --height, --orientation, --timezone, and --config
  (JSON settings override).

Add tests/test_dry_run_plugin.py with 17 tests covering unit helpers (_MockDeviceConfig,
  _discover_plugin_config, _load_settings) and end-to-end integration against year_progress
  including dimension verification and --config override.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* fix: remove unused mypy type-ignore comment in dry_run test

* style: reformat test_plugin_routes.py with black (merge artifact)

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.17.0 (2026-04-08)

### Features

- Add display calibration patterns CLI ([#260](https://github.com/jtn0123/InkyPi/pull/260),
  [`cdb5b38`](https://github.com/jtn0123/InkyPi/commit/cdb5b38bc8b286e3b93981f1e4e6cf962b2b6753))

scripts/calibration_pattern.py generates 6 PNG test images (pure colors, grayscale ramp, dithering
  grid, font resolution, edge sharpness, full-refresh ghosting) for tuning e-ink display rendering
  pipelines and color profiles. Supports --profile color/grayscale/mono; tests cover all patterns
  and profiles.

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>

- Aggregated refresh stats endpoint ([#258](https://github.com/jtn0123/InkyPi/pull/258),
  [`ba31444`](https://github.com/jtn0123/InkyPi/commit/ba3144412ab1396d22341f388f6fd8c943728c02))

Add GET /api/stats returning rolling refresh aggregates (total, success_rate, P50/P95 duration, top
  failing plugins) for 1h, 24h, and 7d windows, computed from history sidecar files with a 60s
  in-process cache.

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>

- Seed test data CLI for dev environments ([#262](https://github.com/jtn0123/InkyPi/pull/262),
  [`dfdabed`](https://github.com/jtn0123/InkyPi/commit/dfdabedea90649aaebbdb8fd5f54008a95de4312))

Adds scripts/seed_test_data.py which populates a dev target directory with 3 sample plugin instances
  (year_progress, weather, calendar), a sample playlist, and N synthetic history PNG+sidecar pairs.
  Idempotent by default; --reset wipes and reseeds. Refuses to run against src/config or any
  directory whose device.json has display_type != mock.

Adds 22 tests in tests/test_seed_test_data.py covering basic seeding, sidecar JSON validity, safety
  guards, idempotency, and --reset behaviour.

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>


## v0.16.0 (2026-04-08)

### Features

- Per-ip rate limiting for login and refresh (JTN-447)
  ([#257](https://github.com/jtn0123/InkyPi/pull/257),
  [`d43f676`](https://github.com/jtn0123/InkyPi/commit/d43f676887e46cea442893052ec2e658ca684688))

Adds a stdlib-only TokenBucket rate limiter keyed on client IP address to defend /login and
  /display-next (/refresh alias) against brute-force and refresh-storming attacks. Complements the
  session-level PIN lockout introduced in JTN-286. Limits are configurable via
  INKYPI_RATE_LIMIT_AUTH and INKYPI_RATE_LIMIT_REFRESH env vars (format: N/Sseconds).

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Sse stream for live dashboard updates ([#256](https://github.com/jtn0123/InkyPi/pull/256),
  [`65a02d8`](https://github.com/jtn0123/InkyPi/commit/65a02d8edabb2f5c30fdac024f39a4a8c0fd1a65))

Add /api/events SSE endpoint backed by a new thread-safe EventBus (src/utils/event_bus.py) with
  per-subscriber queues, 50-subscriber cap, 15 s heartbeat, and clean disconnect handling. Hook
  publish() into RefreshTask._perform_refresh for refresh_started, refresh_complete, and
  plugin_failed events. Wire pushUrl in the dashboard template so the existing EventSource fallback
  logic activates automatically. Add 18 tests covering bus unit behaviour, stream formatting,
  endpoint contract, and refresh-task hook integration.

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>


## v0.15.0 (2026-04-08)

### Features

- Csv export of refresh history ([#254](https://github.com/jtn0123/InkyPi/pull/254),
  [`2cc123f`](https://github.com/jtn0123/InkyPi/commit/2cc123f9bbbb08878fe1f764e148ca1d56792078))

Add GET /history/export.csv route that streams all history entries as a downloadable CSV (timestamp,
  plugin_id, instance_name, status, duration_ms, error_message) using stdlib csv + io.StringIO. Adds
  an Export CSV button to the history page header. Includes 13 tests covering headers, empty state,
  row values, escaping (commas, quotes, newlines), missing sidecar fallback, and page link presence.

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>

- Plugin instance export/import via JSON (JTN-448)
  ([#255](https://github.com/jtn0123/InkyPi/pull/255),
  [`3a6c12e`](https://github.com/jtn0123/InkyPi/commit/3a6c12e8725cfd2eafbcd3e6b27768f8b5da5180))

Add GET /api/plugins/export (single or all instances) and POST /api/plugins/import endpoints. Import
  validates shape, rejects unknown plugin_ids, handles name collisions, and does not auto-add to
  playlist.

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>

- Webhook notifications on plugin failures (JTN-449)
  ([#253](https://github.com/jtn0123/InkyPi/pull/253),
  [`7a63469`](https://github.com/jtn0123/InkyPi/commit/7a6346989ae055116dd98addf87a59892155da20))

POST to configured webhook_urls on plugin failure or circuit-breaker open. Best-effort: 1 s timeout,
  no retries, exceptions swallowed. Adds send_failure_webhook helper, hooks into _cb_on_failure, and
  documents the feature in docs/webhooks.md.

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>


## v0.14.0 (2026-04-08)

### Features

- Add optional PIN authentication (JTN-286) ([#241](https://github.com/jtn0123/InkyPi/pull/241),
  [`ced305d`](https://github.com/jtn0123/InkyPi/commit/ced305da90ec7de72636c230bb819e4026893460))

* feat: add optional PIN authentication (JTN-286)

Adds opt-in PIN auth via INKYPI_AUTH_PIN env var or device_config auth.pin. When unset (default)
  behaviour is unchanged. When set, all routes except /login, /logout, /sw.js, /static/*,
  /api/health, /healthz, /readyz redirect unauthenticated requests to a login form. PIN is
  scrypt-hashed in memory, never persisted. Rate-limits 5 failures then 60s lockout. 16 new tests,
  all 2445 passing.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

* fix: validate next URL and extract login template constant (Sonar S5146/S1192)

- _safe_next_url() rejects absolute and protocol-relative URLs to prevent open-redirect via the
  ?next= parameter - _LOGIN_TEMPLATE constant deduplicates the 'login.html' literal

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

---------

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>


## v0.13.0 (2026-04-08)

### Features

- Add /api/version/info and /api/uptime JSON endpoints (JTN-360)
  ([#249](https://github.com/jtn0123/InkyPi/pull/249),
  [`9f2c876`](https://github.com/jtn0123/InkyPi/commit/9f2c8764472e47d5fc0f76a2108299e917d68076))

* feat: add /api/version/info and /api/uptime endpoints (JTN-360)

Adds a new version_info blueprint with two unauthenticated JSON endpoints: - GET /api/version/info —
  version, git_sha, git_branch, build_time, python_version (all cached at module import, never
  per-request) - GET /api/uptime — process_uptime_seconds, system_uptime_seconds (/proc/uptime on
  Linux, null elsewhere), process_started_at ISO timestamp

Registers blueprint in blueprints_registry.py and conftest.py; adds 13 tests covering both routes.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

* test: add unit tests for version_info helper functions to meet coverage gate (JTN-360)

SonarCloud Quality Gate requires ≥80% coverage on new code; previous commit was at 78.9%. Added
  targeted unit tests for exception fallback paths in _read_app_version, _run_git, _read_build_time,
  and the Linux /proc/uptime path in _system_uptime_seconds. Coverage is now at 98%.

---------

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>

- Add diagnostic snapshot CLI for support workflows (JTN-363)
  ([#252](https://github.com/jtn0123/InkyPi/pull/252),
  [`6e5d568`](https://github.com/jtn0123/InkyPi/commit/6e5d568fc5afc3f750e4fad8819e45a89005602a))

scripts/diagnostic_snapshot.py collects system info, redacted device.json (API
  keys/tokens/passwords/secrets/pins masked), log tail, and best-effort journal entries into a
  support tarball. 17 tests cover redaction, log handling, manifest structure, and graceful
  fallbacks.

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>

- Add HTTP request timing histogram to /metrics (JTN-362)
  ([#251](https://github.com/jtn0123/InkyPi/pull/251),
  [`fab9033`](https://github.com/jtn0123/InkyPi/commit/fab90338099354805db705eb772f9c3b1cd33b3b))

* feat: add HTTP request timing histogram to metrics (JTN-362)

Extends the Prometheus /metrics endpoint with per-endpoint latency histograms
  (inkypi_http_request_duration_seconds) and request counters (inkypi_http_requests_total), labelled
  by method, url_rule endpoint, and status code. Excludes /metrics scrapes and /static/* to avoid
  noise.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

* fix: black formatting for JTN-361

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* Revert "fix: black formatting for JTN-361"

This reverts commit c3c04d3e124138fcfb24d886225b09cb2bf2cee6.

---------

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>

- Add log filter to redact secret-like patterns (JTN-364)
  ([#250](https://github.com/jtn0123/InkyPi/pull/250),
  [`acf9880`](https://github.com/jtn0123/InkyPi/commit/acf98801fc21f701ffeb0795a1b206a7e89043da))

* feat: add log filter to redact secret-like patterns (JTN-364)

Introduces SecretRedactionFilter — a logging.Filter that masks API keys, Bearer tokens, passwords,
  PINs, and 32+ hex strings in every log record before it reaches any handler. Applied globally via
  the root logger in setup_logging() so both plain-text and JSON log formats are covered.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

* fix: add gitleaks:allow annotations to test secrets (JTN-364)

Gitleaks CI was flagging intentional fake secrets used in the redaction filter tests. Added inline #
  gitleaks:allow comments so the scanner recognises these as test fixtures, not real credentials.

* fix: add gitleaks config to allowlist test-fixture secrets (JTN-364)

Tests for the secret-redaction filter intentionally contain fake api_key= strings to verify the
  filter pattern works. Add a .gitleaks.toml that allowlists tests/test_log_redaction.py so the
  scanner does not flag these well-known test fixtures as real credentials.

* fix: switch to top-level [allowlist] syntax in .gitleaks.toml (JTN-364)

Gitleaks v8 path allowlisting requires the top-level [allowlist] table rather than the
  [[allowlists]] array form when no condition is specified.

---------

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>

- Auto-cleanup of old history images (JTN-361) ([#248](https://github.com/jtn0123/InkyPi/pull/248),
  [`0993412`](https://github.com/jtn0123/InkyPi/commit/0993412cefcddb4f8fb8e45af196d7c82c2aa5a8))

* feat: auto-cleanup of old history images (JTN-361)

Add history_cleanup.py with retention policy (max_age_days, max_count, min_free_bytes). Wire into
  RefreshTask to run every 10 ticks. Read policy from device_config history_cleanup section with
  safe defaults.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

* fix: black formatting on history_cleanup files (JTN-361)

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* chore: remove leaked pre-restore tarball from JTN-361 branch

---------

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>


## v0.12.0 (2026-04-08)

### Bug Fixes

- Add accessible labels to form controls (JTN-315)
  ([#242](https://github.com/jtn0123/InkyPi/pull/242),
  [`12543ef`](https://github.com/jtn0123/InkyPi/commit/12543efda0f90178a4148ab56b6884920fe92073))

All form controls on /playlist and /plugin/calendar already have proper labels in the current
  templates (aria-label on interval/unit/ time inputs in refresh_settings_form.html, for=
  associations on selects in playlist modal). This commit adds a regression test that asserts every
  named input/select/textarea has an accessible label, and removes label/select-name from the axe
  known-violations allowlists in test_playlist_a11y.py and test_more_a11y.py since those rules now
  pass.

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>

- Lazy-load history images to fix Playwright timeout (JTN-316)
  ([#238](https://github.com/jtn0123/InkyPi/pull/238),
  [`776f777`](https://github.com/jtn0123/InkyPi/commit/776f7779cd4a7f62c9c29ef3501d3c6fb67ddc0b))

Add decoding="async" to history grid images and defer lightbox.js / history_page.js so they no
  longer block HTML parsing, preventing the networkidle / load-event timeout Playwright recorded on
  /history.

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>

### Features

- Add backup/restore CLI for device config (JTN-336)
  ([#246](https://github.com/jtn0123/InkyPi/pull/246),
  [`f3c9b0f`](https://github.com/jtn0123/InkyPi/commit/f3c9b0ff058607e28b505b163693f8313e1c4407))

scripts/backup_config.py creates a timestamped tar.gz of device.json + plugin instance images with a
  manifest including SHA-256 checksum. scripts/restore_config.py reverses the operation: shows what
  will be restored, requires confirmation (or --yes), creates a .pre-restore-<timestamp>.tar.gz
  safety backup first, then verifies checksum. Both scripts are stdlib-only and independent of the
  Flask app. 12 tests in tests/test_backup_restore.py cover all key scenarios.

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>

- Add HTMX MVP for history pagination (JTN-288) ([#243](https://github.com/jtn0123/InkyPi/pull/243),
  [`9c5f26b`](https://github.com/jtn0123/InkyPi/commit/9c5f26bd8030c4011941f9f142aa70b4b673ec63))

Vendor htmx.min.js 2.0.4 (~50 KB) and include it in base.html with defer. Convert the history page
  grid/pagination to use hx-get / hx-target / hx-swap so page navigation swaps only the
  history-grid-container partial in place. The /history route serves the partial template when the
  HX-Request header is present and the full page otherwise (progressive enhancement — no-JS users
  follow normal <a href> links unchanged). Five tests in tests/test_htmx.py cover partial vs full
  response, htmx script presence, hx-* attribute presence, and the no-JS fallback.

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>

- Add JS/CSS asset bundling for production (JTN-287)
  ([#240](https://github.com/jtn0123/InkyPi/pull/240),
  [`c2eec87`](https://github.com/jtn0123/InkyPi/commit/c2eec87d19678436df4319b9be2499f4977c3eb0))

Bundle and minify 7 common JS files and the built CSS into versioned dist files with SHA-256
  cache-busting hashes via scripts/build_assets.py. Adds Jinja2 bundled_asset() helper with graceful
  degradation when manifest is absent, and a {% if bundled_assets_enabled %} guard in base.html so
  dev mode continues using individual script tags.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Add mutmut config and nightly mutation testing job (JTN-290)
  ([#239](https://github.com/jtn0123/InkyPi/pull/239),
  [`3fb4eb3`](https://github.com/jtn0123/InkyPi/commit/3fb4eb30ebd9635f981416a94fab56b90bfb61e7))

Adds mutmut 2.5.1 to dev deps, configures [tool.mutmut] in pyproject.toml scoped to 3 high-value
  files, wires the existing mutation-nightly CI job to run mutmut on Sunday 03:00 UTC schedule only,
  adds a config guard test, and adds docs/mutation_testing.md with local-run and expansion
  instructions.

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>

- Add Prometheus /metrics endpoint (JTN-334) ([#245](https://github.com/jtn0123/InkyPi/pull/245),
  [`5b4f73b`](https://github.com/jtn0123/InkyPi/commit/5b4f73be07ce72f35fec1ff7dca24afbf92eb569))

Expose GET /metrics with five Prometheus gauges/counters: refresh totals (success/failure),
  last-successful-refresh timestamp, per-plugin failure counts, circuit-breaker open state, and
  process uptime. Uses a custom CollectorRegistry for test isolation; endpoint requires no
  authentication.

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>

- Optional JSON structured logging via INKYPI_LOG_FORMAT (JTN-337)
  ([#244](https://github.com/jtn0123/InkyPi/pull/244),
  [`6be6683`](https://github.com/jtn0123/InkyPi/commit/6be668387a807d7554c243c4c5b1d53d7610246d))

Add JsonFormatter emitting one JSON object per line with ts, level, logger, msg, module, func, line,
  pid fields. Exception records include exc_type, exc_message, exc_traceback. Extras nested under
  extra key. Non-serialisable values stringified safely. Enabled via INKYPI_LOG_FORMAT=json; default
  plain-text format unchanged. Adds 17 tests (100% pass) and docs/logging.md.

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>

- Validate device.json schema on startup (JTN-335)
  ([#247](https://github.com/jtn0123/InkyPi/pull/247),
  [`86f9cfc`](https://github.com/jtn0123/InkyPi/commit/86f9cfced637d8938ea0b85702b6a713fe368df9))

Extract schema validation into src/utils/config_schema.py with a dedicated ConfigValidationError
  class. Wire validate_device_config() into Config.read_config() and add clean exit(1) handling in
  create_app(). Adds 13 new tests covering valid, invalid, fallback (no jsonschema), permissive
  unknown keys, and regression against the real device_dev.json.

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>


## v0.11.0 (2026-04-08)

### Features

- Serve WebP-encoded images for accepting clients (JTN-302)
  ([#235](https://github.com/jtn0123/InkyPi/pull/235),
  [`7923b91`](https://github.com/jtn0123/InkyPi/commit/7923b91675988fc1b6ed5c718da9c144e0a9f932))

* feat: serve WebP-encoded images when client accepts (JTN-302)

Add utils/image_serving.py with maybe_serve_webp() helper that returns a WebP-encoded response
  (quality=85, method=4) via lru_cache when the client's Accept header includes image/webp, and
  falls back to the original PNG otherwise. Wire into /preview and /history/image routes with ETag
  support. Add 6 tests covering all branches.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

* fix: use sha256 for ETag fingerprint to satisfy Sonar S4790

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* fix: validate image_path containment in maybe_serve_webp (Sonar S2083/S6549)

Adds a required safe_root parameter and re-validates that the resolved image path lives under it.
  Pre-existing caller-side validation in history.py is now backed by an explicit sanitization
  boundary that satisfies SonarCloud's path-traversal taint analysis.

* fix: rewrite maybe_serve_webp to use send_from_directory (Sonar S2083)

Sonar's pythonsecurity taint analyzer doesn't recognize manual commonpath checks as a sanitizer.
  Switch the helper signature to (safe_root, filename, accept_header) and delegate the PNG branch to
  flask.send_from_directory which IS a recognized sink. The WebP branch uses a private _safe_join
  helper that mirrors send_from_directory's validation semantics.

* fix: use werkzeug.utils.safe_join for Sonar-recognized sanitization

S6549 still flagged the manual realpath/commonpath check. werkzeug's safe_join is the canonical path
  sanitizer that Sonar's taint analyzer recognizes, so use it directly.

---------

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>


## v0.10.0 (2026-04-08)

### Features

- Add service worker for offline shell caching (JTN-303)
  ([#233](https://github.com/jtn0123/InkyPi/pull/233),
  [`66eb6da`](https://github.com/jtn0123/InkyPi/commit/66eb6dad95bb0bd2726ea4a053d5e882cb51e116))

* feat: add service worker for offline shell caching (JTN-303)

Adds sw.js with cache-first strategy for /static/* assets, a /sw.js route at origin root with
  Service-Worker-Allowed header, and SW registration in the base template (https/localhost only).

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

* fix: exclude sw.js from SonarCloud coverage gate

sw.js is a browser service worker — it cannot be instrumented by Python's pytest/coverage. Exclude
  it from SonarCloud's coverage requirement the same way existing static JS files under scripts/ are
  already excluded.

---------

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>


## v0.9.0 (2026-04-08)

### Bug Fixes

- Scope wizard nav ids per step to remove duplicates (JTN-314)
  ([#237](https://github.com/jtn0123/InkyPi/pull/237),
  [`32c6716`](https://github.com/jtn0123/InkyPi/commit/32c671639181200478f758095dc8c01e7cec2ffa))

Replace id="wizardPrev"/id="wizardNext" with data-wizard-prev/data-wizard-next attributes in
  initializeWizard() so multiple wizard containers on the same page never produce duplicate DOM ids.
  Also adds an early-return guard that prevents navigation from being injected into an empty
  .setup-wizard placeholder (the root cause of 136 duplicate-id findings in the 2026-04-06 dogfood
  audit). Updates querySelector calls to use the new attribute selectors. Adds 5 regression tests
  covering both the JS source and rendered plugin page HTML.

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>

### Features

- Add OpenAPI spec and Swagger UI docs (JTN-285)
  ([#236](https://github.com/jtn0123/InkyPi/pull/236),
  [`698d24d`](https://github.com/jtn0123/InkyPi/commit/698d24d612973d4c81b917fda246895f93f68f4a))

Adds hand-written OpenAPI 3.0 spec at src/static/openapi.json covering 12 documented paths across
  Health, System, Display, Playlist, History, and Docs tag groups. Exposes GET /api/docs (Swagger UI
  via CDN) and GET /api/openapi.json via a new api_docs blueprint. Includes a drift guard test that
  asserts every spec path exists in the Flask url_map.

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>

### Refactoring

- Hoist nested JS functions and reduce deep nesting (JTN-281)
  ([#232](https://github.com/jtn0123/InkyPi/pull/232),
  [`951d27f`](https://github.com/jtn0123/InkyPi/commit/951d27f309cc572d7a4b08c9800d81bd06ba1276))

Addresses a subset of the SonarCloud S2004 (deep nesting) and S7721 (inner functions could be at
  module scope) findings across the frontend JavaScript modules.

Files modified:

- history_page.js: hoists setHidden, setModalOpen, showStoredMessage, and hideHistoryImageSkeleton
  out of createHistoryPage to module scope (4 hoists). - dashboard_page.js: hoists setHidden and
  hidePreviewSkeletonNode out of createDashboardPage to module scope (2 hoists). - settings_page.js:
  replaces inline anonymous function expressions in copyLogsToClipboard with named arrow callbacks;
  tightens showCopyFeedback's setTimeout callback (2 cleanups). - plugin_page.js: extracts
  showInstanceFallback helper to flatten a triple-nested onerror handler in refreshInstancePreview,
  and extracts collapseApiIndicator from initApiIndicator (2 fixes). - plugin_schema.js: extracts
  initLeafletMap from openModal in initWeatherMap to flatten a deeply nested setTimeout callback (1
  fix).

Pure refactor — behavior is unchanged. No global API surface (window.X = X assignments) was renamed.
  All event handler wiring preserved. Static and integration test suites still pass.

The remaining S2004/S7721 findings are either in tightly-coupled closures (api_keys_page) or
  describe code structures whose line numbers no longer match the live source after recent unrelated
  refactors. Those will be addressed in a follow-up if SonarCloud re-flags them after this lands.

Refs JTN-281

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Split inkypi.py into middleware/error modules (JTN-289)
  ([#230](https://github.com/jtn0123/InkyPi/pull/230),
  [`cc301ac`](https://github.com/jtn0123/InkyPi/commit/cc301acedeb7c1f765dce4f6b743188ce8658330))

* refactor: split inkypi.py into focused middleware/error/logging modules (JTN-289)

Reduces inkypi.py from 687 lines to ~340 by extracting middleware, error handlers, health endpoints,
  blueprint registration, signal handling, and logging setup into a new src/app_setup/ package:

- app_setup/logging_setup.py — 67 lines (logging config + dev handler) - app_setup/error_handlers.py
  — 54 lines (Flask error handlers) - app_setup/security_middleware.py — 261 lines (CSRF, rate
  limit, headers, secrets) - app_setup/health.py — 26 lines (/healthz, /readyz) -
  app_setup/blueprints_registry.py — 22 lines (blueprint registration) - app_setup/signals.py — 34
  lines (SIGTERM/SIGINT handlers)

Behavior is unchanged. The public API of inkypi.py is preserved via re-exports — every symbol that
  tests/unit/test_inkypi.py monkey-patches is still available as a module attribute
  (pop_hot_reload_info, the _setup_* helpers, _generate_csrf_token,
  _extract_csrf_token_from_request, etc.).

The two security middleware functions that emit log lines or call pop_hot_reload_info now resolve
  those targets through sys.modules['inkypi'] so existing monkey-patches in test_inkypi.py keep
  working without modification.

Closes JTN-289

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* fix: extract security-header helper functions to reduce complexity (S3776)

SonarCloud flagged setup_security_headers as having cognitive complexity 40 (max 15) — the entire
  after_request handler lived inside one function with multiple nested try/except blocks.

Splits the handler into focused helpers per concern: - _emit_request_timing_log -
  _apply_static_cache_headers - _apply_baseline_security_headers - _apply_hsts_header -
  _apply_csp_header - _apply_hot_reload_header

The handler now just iterates over them with shared exception isolation. Behavior is unchanged.

* fix: mark http:// literal in HTTPS redirect as NOSONAR (S5332)

The http:// string in setup_https_redirect is the SOURCE of the http→https upgrade, not a hardcoded
  insecure URL. Adds a NOSONAR comment to suppress the false-positive S5332 hotspot.

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Testing

- Add API contract tests for APOD, GitHub, and Open-Meteo (JTN-292)
  ([#231](https://github.com/jtn0123/InkyPi/pull/231),
  [`f562dee`](https://github.com/jtn0123/InkyPi/commit/f562dee0d6e5dcb515d682095a0c07c40ff63c42))

Adds tests/contracts/ with 4 hand-constructed JSON fixtures and 11 contract tests covering the top
  external API integrations:

- NASA APOD (image and video media types) - GitHub repos endpoint (used by the github_stars plugin)
  - Open-Meteo forecast API (used by the weather plugin)

Each test loads a fixture, validates a minimal schema, and exercises the plugin parsing code via
  requests-mock — no live API calls happen in CI. If an upstream API changes its response shape, the
  relevant test will break loudly here instead of silently in production.

Coverage in this PR is intentionally narrow (3 plugins). Follow-ups will extend to OpenWeatherMap,
  Unsplash, RSS, and Google Calendar.

Refs JTN-292

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Add integration tests for full refresh cycle (JTN-291)
  ([#234](https://github.com/jtn0123/InkyPi/pull/234),
  [`21b078f`](https://github.com/jtn0123/InkyPi/commit/21b078f1c1b915b433faf136f9dd0cbc5f44d4ac))

Adds three deterministic, fast (<1s total) integration tests that exercise the path from playlist
  resolution through plugin image generation to the mock display without using sleep() or thread
  timing:

- test_refresh_cycle_runs_plugin_to_display: year_progress plugin renders to MockDisplay; asserts
  image dimensions, plugin_health green, metrics set - test_refresh_cycle_handles_plugin_failure:
  stubbed crashing plugin leaves display uncalled and plugin_health red with error recorded -
  test_refresh_cycle_advances_playlist: two plugins in playlist each render once and receive a
  refresh timestamp after their respective ticks

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.8.0 (2026-04-08)

### Documentation

- Add architecture diagram and plugin hello-world tutorial (JTN-295)
  ([#228](https://github.com/jtn0123/InkyPi/pull/228),
  [`240ea97`](https://github.com/jtn0123/InkyPi/commit/240ea970d7343a5c3e9f7cdc3a8f5823fd8c32e0))

Adds docs/architecture.md with a Mermaid flowchart of the request and refresh paths, plus a 7-step
  hello-world walkthrough at the bottom of the plugin building guide. Both linked from the README's
  Documentation section so new contributors can orient quickly.

Closes JTN-295

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Features

- Add pytest-benchmark perf baseline tests and CI step (JTN-293)
  ([#229](https://github.com/jtn0123/InkyPi/pull/229),
  [`9806aa6`](https://github.com/jtn0123/InkyPi/commit/9806aa621d06616eca3be1490690a9b845a81080))

Adds 5 deterministic benchmarks for the InkyPi hot paths:

- HTTP cache hit lookup - PIL image resize + convert (e-ink prep) - PIL image PNG encode (/preview
  hot path) - Config read (JSON parse + validate) - Plugin registry list scan (startup walk of
  src/plugins/)

A new CI step in the lint job runs them on every PR via `pytest tests/benchmarks/ --benchmark-only`.
  For now CI only prints the timings — auto-comparison against a stored baseline (and a regression
  gate) is a follow-up PR.

Refs JTN-293

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.7.1 (2026-04-08)

### Bug Fixes

- Plugin edit routes support ?instance= param (JTN-221)
  ([#226](https://github.com/jtn0123/InkyPi/pull/226),
  [`acd92c0`](https://github.com/jtn0123/InkyPi/commit/acd92c06385c0056e8294777312e79a4bde42f9c))

* fix: support ?instance= query param on plugin edit routes (JTN-221)

Plugin edit routes returned 404 when given an instance query parameter, breaking saved-instance
  editing flows from the playlist page. Now looks up the instance via playlist manager (with URL
  decoding) and renders the editor with its settings prefilled. Returns a friendly 404 if the
  instance name doesn't exist.

Adds tests for: existing instance returns 200, URL-encoded '+' spaces decode correctly, nonexistent
  instance returns descriptive 404, and the baseline no-instance route continues to work.

Closes JTN-221

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* style: apply black formatting to JTN-221 test file

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.7.0 (2026-04-08)

### Features

- Add ARIA landmarks and skip-to-content link (JTN-296 partial)
  ([#227](https://github.com/jtn0123/InkyPi/pull/227),
  [`edc3b9d`](https://github.com/jtn0123/InkyPi/commit/edc3b9dba8936117eba99a09bbe49ef977be10ad))

Adds role=main/nav/banner/contentinfo to the base layout and a visually-hidden skip-to-content link
  that becomes visible on focus. This is the first slice of the broader accessibility audit; the
  full audit (focus management, aria-live regions, contrast checks) will follow in additional PRs.

- Convert app-header div to <header role="banner"> on all shared layout pages - Add <nav
  role="navigation"> for site-level nav links on the dashboard - Fix api_keys.html missing
  id="main-content" on its <main> element - Skip-to-content link and .skip-link CSS were already
  present in base.html/_layout.css - Add 20 unit tests verifying landmark presence and skip-link CSS
  off-screen positioning

Refs JTN-296

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Add Dockerfile and docker-compose for dev/test (JTN-297)
  ([#223](https://github.com/jtn0123/InkyPi/pull/223),
  [`9fc200b`](https://github.com/jtn0123/InkyPi/commit/9fc200bf20481e9cb086991cd0bb6a99119287ba))

Lets contributors run the full InkyPi web UI in a container with mocked display, no Pi hardware
  required. Live reload via src/ volume mount. Documented as alternative dev setup.

Closes JTN-297

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.6.4 (2026-04-08)

### Bug Fixes

- Enforce 36px minimum touch targets on mobile (JTN-223)
  ([#224](https://github.com/jtn0123/InkyPi/pull/224),
  [`3f3bdff`](https://github.com/jtn0123/InkyPi/commit/3f3bdff9d56bab55a7d7d0e31aff03872120f310))

Adds mobile media query rules ensuring all interactive controls meet the 36px tap target threshold.
  Affects buttons, checkboxes, radios, selects, and chip controls on /settings, /settings/api-keys,
  and all plugin config pages. Desktop styles unchanged.

Closes JTN-223

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Chores

- Remove orphan GPL-3 dependency rfc3987 (JTN-313 partial)
  ([#225](https://github.com/jtn0123/InkyPi/pull/225),
  [`57a71cf`](https://github.com/jtn0123/InkyPi/commit/57a71cf43c43e7bda75e083eeb11d422b359a6ab))

rfc3987 is GPL-3.0-or-later licensed. Investigation showed it is a true orphan: pip show rfc3987
  reports Required-by: (empty), nothing in src/, tests/, or scripts/ imports it, and it is absent
  from install/requirements*.txt. Removed from the --ignore-packages exemption list in both
  scripts/check_licenses.sh and .github/workflows/ci.yml. The recurring-ical-events replacement (the
  harder half of JTN-313) will be handled in a separate PR.

Refs JTN-313

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.6.3 (2026-04-08)

### Bug Fixes

- Wire up history page Display/Delete/Clear All actions and pagination (JTN-305, JTN-306, JTN-307,
  JTN-308) ([#220](https://github.com/jtn0123/InkyPi/pull/220),
  [`cfc10b6`](https://github.com/jtn0123/InkyPi/commit/cfc10b65830b24aa363685b36af645d43101c1c5))

The history page had four no-op interactive elements: - Display button now POSTs to the display
  endpoint - Delete button now confirms and DELETEs the entry - Clear All button now confirms and
  clears history - Next pagination link now navigates to the next page

Add 26 static and integration tests covering all four fixes: JS source analysis verifying event
  delegation, endpoint wiring, and config URL injection; template assertions for data attributes,
  modal markup, and boot config; and endpoint smoke tests for redisplay, delete, and clear actions.

Closes JTN-305 Closes JTN-306 Closes JTN-307 Closes JTN-308

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.6.2 (2026-04-08)

### Bug Fixes

- Filter internal secrets and fix Add Key button on API Keys page (JTN-309, JTN-310)
  ([#222](https://github.com/jtn0123/InkyPi/pull/222),
  [`97352d3`](https://github.com/jtn0123/InkyPi/commit/97352d38c98161ba428785e968fa0b5e2c0ddc26))

- JTN-309: skip SECRET_KEY/TEST_KEY/WTF_CSRF_SECRET_KEY in the API Keys blueprint so internal
  secrets are not exposed in the UI. Added _INTERNAL_KEYS frozenset constant; filtered in
  apikeys_page(). - JTN-310: guard addRow() against missing #apikeys-list element and guard
  addPreset() against buttons with no data-key attribute so the Add API Key button and preset chips
  fail gracefully instead of throwing a silent TypeError.

Closes JTN-309 Closes JTN-310

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.6.1 (2026-04-08)

### Bug Fixes

- Wire up Calendar plugin Remove and Last progress buttons (JTN-311, JTN-312)
  ([#221](https://github.com/jtn0123/InkyPi/pull/221),
  [`8d8f010`](https://github.com/jtn0123/InkyPi/commit/8d8f01069aa56836188e3279ebda2eb39671c203))

- JTN-311: Remove calendar button now disables when only one row remains, with a tooltip explaining
  why. Added syncRemoveButtonStates() called on init, add, and remove. Removed the silent shake-only
  UX. - JTN-312: Last progress button now correctly reveals the progress panel by calling
  setHidden(progress, false) instead of progress.style.display which was overridden by the HTML
  hidden attribute (a silent no-op).

Closes JTN-311 Closes JTN-312

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Chores

- Add dependency license audit CI step (JTN-298)
  ([#219](https://github.com/jtn0123/InkyPi/pull/219),
  [`573cd69`](https://github.com/jtn0123/InkyPi/commit/573cd69c288a089d263f7c2276e3fe8611ffa373))

* chore: add dependency license audit to CI (JTN-298)

Adds a pip-licenses check that fails CI if a GPL/AGPL license is detected in the dependency tree.
  Also adds scripts/check_licenses.sh for local pre-PR runs. NOTE: the current dependency tree FAILS
  the audit — recurring-ical-events 3.8.0 carries GPL-3.0-or-later and rfc3987 1.3.8 carries GPLv3+;
  these require follow-up remediation.

Closes JTN-298

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* chore: tighten license check to GPL-3/AGPL-3 only with exemptions

The initial broad GPL/AGPL partial-match also caught LGPL packages (like astroid, CairoSVG,
  zeroconf) which are fine for libraries used by an MIT project. Switch to exact-match against GPL-3
  / AGPL-3 strings only and exempt the two known runtime offenders (recurring-ical-events, rfc3987)
  for separate replacement work.

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.6.0 (2026-04-08)

### Documentation

- Document systemd journal rotation for long-running Pi deployments (JTN-304)
  ([#218](https://github.com/jtn0123/InkyPi/pull/218),
  [`f8c9827`](https://github.com/jtn0123/InkyPi/commit/f8c982749a99f1175a219f34a3b5c16c9be5cc91))

Adds a log rotation section to the troubleshooting docs explaining how to check journal disk usage,
  set size limits in journald.conf, and vacuum old logs. Helps prevent disk-full issues on SD cards
  over weeks/months of 24/7 uptime.

Closes JTN-304

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Features

- Auto-pause failing plugins after threshold (JTN-301)
  ([#217](https://github.com/jtn0123/InkyPi/pull/217),
  [`e4f65db`](https://github.com/jtn0123/InkyPi/commit/e4f65db457430989b9d7c26a070b8470a97f21bf))

* feat: auto-pause plugins after consecutive failures (JTN-301)

Adds a circuit-breaker counter to the refresh path. After N consecutive failures (default 5, env:
  PLUGIN_FAILURE_THRESHOLD), the plugin is marked paused and skipped by the scheduler until a
  successful refresh resets it. Backend-only — UI surfacing comes in a follow-up.

Closes JTN-301

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* fix: address SonarCloud findings on circuit breaker (JTN-301)

- Extract _cb_on_success and _cb_on_failure helpers from _update_plugin_health to reduce cognitive
  complexity (S3776, was 24). - Use %r in reset_circuit_breaker log to escape user-controlled
  plugin_id/instance values (S5145).

* fix: explicit sanitization of user-controlled log values (S5145)

SonarCloud's analyzer didn't recognize %r-formatted log values as sanitized. Switch to explicit
  replace+truncate so the dataflow is visible to the analyzer.

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.5.0 (2026-04-08)

### Bug Fixes

- Make Refresh Settings modal a true modal (JTN-228)
  ([#213](https://github.com/jtn0123/InkyPi/pull/213),
  [`47dcc0e`](https://github.com/jtn0123/InkyPi/commit/47dcc0ed217cfa9bc13116eebbce5bbbcec4b017))

* fix: make playlist Refresh Settings modal block background (JTN-228)

The Refresh Settings dialog left the underlying playlist page interactive. Adds a
  #playlist-page-content wrapper div in playlist.html and toggles the inert attribute on it whenever
  any modal opens, blocking all pointer, keyboard, and touch events from reaching background
  controls. Focus is moved into the modal on open and restored to the trigger element on close. All
  playlist modals (Refresh Settings, Schedule, Delete playlist/instance) use the same centralised
  syncModalOpenState path.

Closes JTN-228

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* test: update openCreateModal regex for triggerEl parameter

The JTN-228 modal backdrop fix added a triggerEl parameter to openCreateModal for focus restoration.
  Loosens the test regex to accept any signature so the assertion still validates the body.

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Prefill default time when switching to Daily-at scheduling (JTN-227)
  ([#214](https://github.com/jtn0123/InkyPi/pull/214),
  [`8f96d8e`](https://github.com/jtn0123/InkyPi/commit/8f96d8e187adeb14a3c43a278f3635e9b5d59ae1))

The Daily-at refresh option used to start with an empty time input, leaving users to discover the
  requirement via an error toast on save. Now defaults to 09:00 on switch and shows inline guidance
  text.

Closes JTN-227

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Features

- Add plugin api_version and version metadata (JTN-300)
  ([#216](https://github.com/jtn0123/InkyPi/pull/216),
  [`0fb809f`](https://github.com/jtn0123/InkyPi/commit/0fb809fe30b82af7fb2198f3537f5fc49cc00a4a))

Adds PLUGIN_API_VERSION constant in base_plugin and api_version/version fields to all built-in
  plugin metadata. Plugin loader logs a warning on major version mismatch but still loads (backward
  compatible). Lays the groundwork for safe plugin API evolution.

Closes JTN-300

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.4.42 (2026-04-08)

### Bug Fixes

- Disable API Keys Save until form is dirty (JTN-225)
  ([#215](https://github.com/jtn0123/InkyPi/pull/215),
  [`e1624d3`](https://github.com/jtn0123/InkyPi/commit/e1624d3963424cdc9c30c12ae5942050bed8bdab))

The Save button on /settings/api-keys was enabled by default and produced no feedback when clicked
  with no edits. Now Save starts disabled, enables on input changes, and disables again after a
  successful save. A no-op click (keyboard shortcut) shows a "No changes to save" toast.

Closes JTN-225

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.4.41 (2026-04-08)

### Bug Fixes

- Add LRU eviction to HTTP cache to prevent memory growth (JTN-299)
  ([#208](https://github.com/jtn0123/InkyPi/pull/208),
  [`6bc5ce7`](https://github.com/jtn0123/InkyPi/commit/6bc5ce76cb8257ad0daad4e804c57bfe9026c146))

Adds a configurable max_entries cap (default 256, env: HTTP_CACHE_MAX_ENTRIES) with LRU eviction via
  OrderedDict. Tracks hit/miss/eviction counters for benchmark visibility. Existing TTL behavior
  unchanged.

Closes JTN-299

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Eliminate duplicate wizardPrev/wizardNext DOM IDs (JTN-220)
  ([#212](https://github.com/jtn0123/InkyPi/pull/212),
  [`38db1fb`](https://github.com/jtn0123/InkyPi/commit/38db1fbf215deee5c4f7d7cb084f7b893fca9575))

Plugin settings pages were rendering the wizard navigation twice — once statically in plugin.html
  (wizardPrev/wizardNext buttons inside .wizard-navigation) and once injected at runtime by
  progressive_disclosure.js's initializeWizard() which appends a second .wizard-navigation to the
  same .setup-wizard container.

Removes the static wizard nav from the template so IDs are unique and DOM selectors are
  deterministic. The .setup-wizard container remains for JS to populate. Updates tests to reflect
  that navigation is JS-injected, not static.

Closes JTN-220

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Restrict history_delete to .png and .json files (JTN-266)
  ([#211](https://github.com/jtn0123/InkyPi/pull/211),
  [`9a8db5b`](https://github.com/jtn0123/InkyPi/commit/9a8db5b053770cb2d8a281cb73374c0ffcaedc0d))

Aligns history_delete with history_clear by adding the same extension allowlist. Prevents deletion
  of arbitrary non-history files that might exist in the history directory. Returns 400 for
  unsupported extensions.

Closes JTN-266

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Restrict PluginInstance.update() to allowlisted fields (JTN-230)
  ([#209](https://github.com/jtn0123/InkyPi/pull/209),
  [`98cd869`](https://github.com/jtn0123/InkyPi/commit/98cd8691d8139fd7b56b3ae1e3ecf955249a3104))

Replaces blanket setattr loop with an explicit allowlist of updatable fields (settings, refresh,
  latest_refresh_time, etc.). Unknown keys are silently ignored to avoid breaking callers. Prevents
  arbitrary attribute injection if user-controlled data ever reaches this code path.

Closes JTN-230

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Chores

- Cache pip dependencies in CI for faster builds (JTN-294)
  ([#210](https://github.com/jtn0123/InkyPi/pull/210),
  [`01125b2`](https://github.com/jtn0123/InkyPi/commit/01125b206ce8703867fef204d026bb96d0c193c9))

Adds cache: pip to all actions/setup-python steps in ci.yml. Cache key is derived from
  install/requirements*.txt so it invalidates automatically when dependencies change. Should cut
  30-60s per Python job.

Also adds pip cache to the release.yml workflow which was missing it.

Closes JTN-294

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.4.40 (2026-04-08)

### Bug Fixes

- Resolve security hotspots — sha256, constants, HTTPS (JTN-283)
  ([#204](https://github.com/jtn0123/InkyPi/pull/204),
  [`8a14921`](https://github.com/jtn0123/InkyPi/commit/8a14921b2ed5e0bd51f923dcd3e4f969aa54cdcc))

* fix: resolve security hotspots — sha256, constants, HTTPS (JTN-283)

- Replace hashlib.md5 with hashlib.sha256 in config write deduplication (S4790) - Extract hardcoded
  "8.8.8.8" to _DNS_CHECK_HOST constant with explanatory comment (S1313) - Upgrade SMBC and
  Questionable Content RSS feed URLs from HTTP to HTTPS (S5332)

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

* fix: add NOSONAR to DNS check host constant

The hardcoded IP is Google's public DNS used for connectivity checks, not a security-sensitive
  endpoint.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* fix: update DNS check host comment to reflect both UDP and TCP usage

---------

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>


## v0.4.39 (2026-04-08)

### Bug Fixes

- Add cancellation event and tracking for timed-out plugin threads (JTN-237)
  ([#205](https://github.com/jtn0123/InkyPi/pull/205),
  [`d19b8ad`](https://github.com/jtn0123/InkyPi/commit/d19b8adc81d7a8f46f5768b39fb82323d988b468))

On timeout in _execute_inprocess, set a threading.Event (cancel_event) so cooperative plugins can
  detect cancellation. Track zombie daemon threads with a class-level counter (_zombie_thread_count)
  that increments on timeout and decrements when the thread eventually finishes. Log clear warnings
  about zombie threads for monitoring.

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>

- Html accessibility — labels, aria attributes, and alt text (JTN-278)
  ([#207](https://github.com/jtn0123/InkyPi/pull/207),
  [`6010237`](https://github.com/jtn0123/InkyPi/commit/6010237a5167ddf2748187c4a906f0d3d2f65503))

Address 42 SonarCloud accessibility issues across 12 templates:

- S7927: Remove redundant title attributes where aria-label is present (home links, action buttons
  in playlist/inky/history/settings/api_keys) - S7927: Align aria-label with visible button text or
  remove when redundant (plugin.html progress button, display instance button) - S6853: Replace
  unassociated <label> with <span> for toggle containers that wrap checkboxes implicitly (settings,
  settings_schema) - S6853: Add aria-label to inputs lacking label association (todo_repeater
  inputs, calendar color picker) - S6853: Replace unassociated section labels with <span> +
  aria-label on target div for non-labelable elements (settings diagnostics panels) - S6853: Convert
  Frame/Background/Clock-Face labels to span + role=group with aria-labelledby for image-grid button
  groups - S6853: Replace bare <label>Refresh</label> with <span> in refresh_settings_form.html and
  plugin.html schedule modal - S6851: Remove redundant "image" from alt text in plugin.html,
  inky.html (Current display), and rss.html (Related)

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>

### Refactoring

- Extract duplicated string literals into constants (JTN-282)
  ([#203](https://github.com/jtn0123/InkyPi/pull/203),
  [`59323e7`](https://github.com/jtn0123/InkyPi/commit/59323e713d3351e42d8ec1408e52e9fe0ed36371))

Extract repeated string literals into named module-level constants across six files to address
  SonarCloud S1192 warnings: _STATE_NEW_YORK/_STATE_NEW_JERSEY in newspaper/constants.py,
  DEFAULT_IMAGE_MODEL reuse in ai_image.py, _MSG_DISPLAY_UPDATED/_ERR_PLUGIN_ID_REQUIRED in
  blueprints/plugin.py, _LABEL_UV_INDEX in weather_data.py, _DEVICE_JSON in config.py, and
  DEFAULT_CLOCK_FACE reuse in clock.py.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Merge duplicate CSS selectors (JTN-284) ([#200](https://github.com/jtn0123/InkyPi/pull/200),
  [`a69e05a`](https://github.com/jtn0123/InkyPi/commit/a69e05a6380794628f5e8747d6df99adb4e2d853))

Merged 9 duplicate CSS selectors flagged by SonarCloud S4666 across _dashboard.css, _layout.css,
  weather_ny.css, and weather.css. Cascade order and specificity preserved; later-defined override
  values kept.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Modernize JS with globalThis, optional chaining, Number.parseInt (JTN-280)
  ([#202](https://github.com/jtn0123/InkyPi/pull/202),
  [`f042c15`](https://github.com/jtn0123/InkyPi/commit/f042c15411ab69ba82f2fef8b285aedeae1bde60))

Address ~62 SonarCloud modernization flags (S7764, S6582, S7773): - Replace window with globalThis
  in dashboard_page, history_page, plugin_schema, client_errors, api_keys_page, ui_helpers,
  plugin_page (skipping csrf.js monkey-patch) - Replace a && a.b patterns with a?.b optional
  chaining across dashboard_page, history_page, plugin_page, ui_helpers - Replace
  parseInt/parseFloat with Number.parseInt/Number.parseFloat in settings_page and plugin_schema

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Reduce cognitive complexity in top 5 worst functions (JTN-276)
  ([#206](https://github.com/jtn0123/InkyPi/pull/206),
  [`b5f260f`](https://github.com/jtn0123/InkyPi/commit/b5f260f7c0e8506f812828a03b3e5aeb8459ce66))

Extract helper functions and apply early returns to bring the following SonarCloud S3776 violations
  under control:

- app_utils.handle_request_files (was 39): split into _get_existing_file_location,
  _validate_and_read_file, _rewind_file_stream, _save_uploaded_file, and _collect_existing_locations
  helpers - config._sanitize_config_for_log (was 30): promote inner closures (_looks_sensitive,
  _mask, _sanitize_playlist) to module-level functions _looks_sensitive, _mask_config_value, and
  _summarize_playlist - base_plugin.render_image (was 29): extract _build_css_files,
  _build_inline_css, _render_template, _capture_screenshot, _get_screenshot_timeout, and
  _screenshot_fallback methods - inkypi.main (was 29): extract _resolve_port, _apply_dev_env, and
  _install_dev_log_handler helpers - task._execute_with_policy (was 25): extract
  _run_subprocess_attempt method

Behavior is unchanged; all 2217 tests pass.

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>


## v0.4.38 (2026-04-08)

### Bug Fixes

- Add labels to unlabeled form controls in playlist and calendar (JTN-222)
  ([#201](https://github.com/jtn0123/InkyPi/pull/201),
  [`488ff38`](https://github.com/jtn0123/InkyPi/commit/488ff3856fc50a3ac9d20a116eaca7156294622d))

Add aria-label attributes to the interval, unit, and refreshTime inputs in
  refresh_settings_form.html, and to the calendarURLs[] input in calendar_repeater.html, so all form
  controls have accessible labels. Adds four regression tests verifying each control has an
  aria-label.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Clear image hash after preprocessed display to prevent skip (JTN-236)
  ([#199](https://github.com/jtn0123/InkyPi/pull/199),
  [`25f8551`](https://github.com/jtn0123/InkyPi/commit/25f85517cec3e2b0b9b9fed4b372a03f623a2641))

display_preprocessed_image (used by history redisplay) now clears _last_image_hash after a
  successful display so the next regular refresh always renders rather than being silently skipped
  due to a stale hash match.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.4.37 (2026-04-08)

### Bug Fixes

- Add keyboard accessibility to plugin.html clickable element (JTN-279)
  ([#195](https://github.com/jtn0123/InkyPi/pull/195),
  [`76a6b8f`](https://github.com/jtn0123/InkyPi/commit/76a6b8fe0b06d2e0aca85f8a3db62ca55b9d927c))

* fix: add keyboard accessibility to plugin.html clickable element (JTN-279)

Convert the frame-option <div> to a semantic <button> element for native keyboard support
  (Enter/Space), add aria-label, and reset button background in CSS so it renders identically to the
  previous div.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

* ci: retrigger workflow

---------

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>


## v0.4.36 (2026-04-08)

### Bug Fixes

- Add explicit HTTP methods to all Flask routes (JTN-275)
  ([#198](https://github.com/jtn0123/InkyPi/pull/198),
  [`ccab65a`](https://github.com/jtn0123/InkyPi/commit/ccab65a682a290983c19edce4a74cbd69bb3f985))

* fix: add explicit HTTP methods to all Flask routes (JTN-275)

Resolves SonarCloud S6965 by adding explicit methods= to every @*.route() decorator across all
  blueprints and the main app, replacing implicit method acceptance with correct GET-only or
  appropriate method lists.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

* ci: retrigger workflow

---------

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>


## v0.4.35 (2026-04-08)

### Bug Fixes

- Add error handling to empty JS catch blocks (JTN-277)
  ([#194](https://github.com/jtn0123/InkyPi/pull/194),
  [`25dbd90`](https://github.com/jtn0123/InkyPi/commit/25dbd90015bceac415257468840ca32a2305a1c2))

* fix: add error handling to empty JS catch blocks (JTN-277)

Resolves SonarCloud S2486 — replace empty catch blocks with either console.warn/error calls or
  explanatory intent comments, so errors are never silently swallowed without a documented reason.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

* ci: retrigger workflow

---------

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>

- Handle DST transitions in scheduled refresh (JTN-268)
  ([#196](https://github.com/jtn0123/InkyPi/pull/196),
  [`12f4874`](https://github.com/jtn0123/InkyPi/commit/12f4874c1e4f6eced20a7b689a81dbfd32f57c68))

* fix: handle DST transitions in scheduled refresh (JTN-268)

Replace current_time.replace(hour=h, minute=m) with a timedelta-from-midnight approach to avoid
  ValueError on spring-forward non-existent times and incorrect fold selection on fall-back
  ambiguous times. Add DST-specific tests covering spring-forward and fall-back scenarios.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

* ci: retrigger workflow

---------

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>

- Handle sub-minute intervals in settings display (JTN-245)
  ([#197](https://github.com/jtn0123/InkyPi/pull/197),
  [`c9055b3`](https://github.com/jtn0123/InkyPi/commit/c9055b35a127a90381c46fdccfea3c17ac721b13))

* fix: handle sub-minute intervals in settings display (JTN-245)

Math.max(1, intervalInMinutes) prevents sub-minute cycle intervals from displaying as "0 minutes",
  which failed the min="1" validation on the interval input field. Also fixes a pre-existing black
  formatting violation in scripts/export_benchmarks_report.py.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

* ci: retrigger workflow

---------

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>

### Code Style

- Auto-format all Python files with Black
  ([`e707553`](https://github.com/jtn0123/InkyPi/commit/e707553b7c2b352f625fd4f500669e707045f11a))

34 files had pre-existing formatting issues that caused CI lint failures on every PR branch.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.4.34 (2026-04-08)

### Bug Fixes

- Repair broken YAML in ci.yml — literal newline in curl -w format string
  ([`36d06a8`](https://github.com/jtn0123/InkyPi/commit/36d06a896fedccaa65beac8deafc343fa0c8d972))

The `-w "%{http_code}\n"` had an actual newline instead of `\n`, causing GitHub Actions to fail with
  "workflow file issue" on all PRs.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.4.33 (2026-04-08)

### Bug Fixes

- Catch expected network error in shutdown fetch (JTN-247)
  ([#189](https://github.com/jtn0123/InkyPi/pull/189),
  [`b7d7a6a`](https://github.com/jtn0123/InkyPi/commit/b7d7a6a38b037a648aee1a09357541cc0f785d52))

* fix: catch expected network error in shutdown fetch (JTN-247)

Wrap the shutdown/reboot fetch call in a try/catch so that the inevitable connection-severed
  TypeError is silenced rather than surfacing a confusing error modal after the success message.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* ci: retrigger workflow

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Remove global progress fallback to prevent cross-plugin data (JTN-246)
  ([#193](https://github.com/jtn0123/InkyPi/pull/193),
  [`522feea`](https://github.com/jtn0123/InkyPi/commit/522feea12cb06ff045040b99037a0fc1b50f0e25))

* fix: remove global progress fallback to prevent cross-plugin data (JTN-246)

showLastProgress fell back to a bare global localStorage key shared across all plugins, which could
  surface progress data from an unrelated plugin. Removed the global fallback, keeping only
  plugin+instance-specific and plugin-only scoped keys. Added test verifying the global key is
  absent from the fallback chain.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* ci: retrigger workflow

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Remove unused playlist_name from instance image URL (JTN-265)
  ([#192](https://github.com/jtn0123/InkyPi/pull/192),
  [`848ae50`](https://github.com/jtn0123/InkyPi/commit/848ae500d6bc51d1005d612db239afb8d656a64b))

* fix: remove unused playlist_name from instance image URL (JTN-265)

playlist.html was passing playlist_name=playlist.name to url_for for the plugin_instance_image
  route, which Flask silently appended as a query string. The route only accepts plugin_id and
  instance_name, so the extra param was ignored — causing wrong images for duplicate instances.
  Removed the unused argument and added a regression test.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* ci: retrigger workflow

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Return shallow copy from get_config() to prevent mutation (JTN-241)
  ([#190](https://github.com/jtn0123/InkyPi/pull/190),
  [`7984ae4`](https://github.com/jtn0123/InkyPi/commit/7984ae453469aaa2dd511bd296eba1e467a73435))

* fix: return shallow copy from get_config() to prevent mutation (JTN-241)

get_config() without a key returned a direct reference to the internal config dict, allowing callers
  to mutate shared state outside the lock. Now returns self.config.copy() to prevent accidental
  mutation.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* ci: retrigger workflow

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Use get_timezone() for safe timezone handling in plugins (JTN-238)
  ([#191](https://github.com/jtn0123/InkyPi/pull/191),
  [`74c8e57`](https://github.com/jtn0123/InkyPi/commit/74c8e57ed3bc86be85cdcb18c029b4da40cd5054))

* fix: use get_timezone() to handle invalid timezones in countdown and weather (JTN-238)

Replace raw ZoneInfo() calls in countdown and weather plugins with the shared get_timezone() utility
  that catches ZoneInfoNotFoundError and falls back to UTC. Remove now-unused ZoneInfo imports. Add
  tests verifying invalid timezone strings do not crash either plugin.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* ci: retrigger workflow

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Continuous Integration

- Add CodeQL code scanning workflow
  ([`3d70264`](https://github.com/jtn0123/InkyPi/commit/3d70264dbf1e5786e7db14c439758d9d6420b1c3))


## v0.4.32 (2026-04-08)

### Bug Fixes

- Prevent cross-playlist drag-and-drop corruption (JTN-235)
  ([#184](https://github.com/jtn0123/InkyPi/pull/184),
  [`05df62e`](https://github.com/jtn0123/InkyPi/commit/05df62e3be640a0f39d5b6b1e9bcab7b9fd21620))

* fix: prevent cross-playlist drag-and-drop corruption (JTN-235)

Added a same-playlist guard in handleDrop that compares the source element's .playlist-item ancestor
  with the drop target's ancestor. When they differ the handler returns early, preventing DOM
  mutation, a stale reorder API call, and silent item loss from the source playlist.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* ci: retrigger workflow

* test: scope drag guard assertions to handleDrop function block

Add _handle_drop_block() helper that extracts only the handleDrop function body (between "function
  handleDrop(e){" and "function handleDragEnd()") so all test assertions are scoped to that function
  and cannot produce false positives from other parts of playlist.js.

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Track title index dynamically in dashboard renderMeta (JTN-248)
  ([#185](https://github.com/jtn0123/InkyPi/pull/185),
  [`cb193d0`](https://github.com/jtn0123/InkyPi/commit/cb193d05a27bd90ec761d8f0aa03c78ae5108fe8))

* fix: track title index dynamically in dashboard renderMeta (JTN-248)

Dashboard renderMeta hardcoded title at index 1, causing the wrong row to be italicised when no
  date/label row was present. Now uses a titleIndex variable set to the row's actual position when
  the title is pushed.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* ci: retrigger workflow

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Treat Open-Meteo dates as local instead of UTC (JTN-251)
  ([#188](https://github.com/jtn0123/InkyPi/pull/188),
  [`f60f044`](https://github.com/jtn0123/InkyPi/commit/f60f044e78f7195a1f395c688ef4bcf04661ee9e))

Open-Meteo returns forecast dates in the coordinate's local timezone as naive datetimes. The
  previous code forced UTC via `.replace(tzinfo=UTC)` then converted to local time, shifting day
  labels back by one for western timezones. Now naive datetimes from Open-Meteo are treated as local
  (matching the API's coordinate-based timezone) with no conversion needed.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Use click timer to enable lightbox double-click native sizing (JTN-262)
  ([#187](https://github.com/jtn0123/InkyPi/pull/187),
  [`268fbb9`](https://github.com/jtn0123/InkyPi/commit/268fbb9da9ddf063c4ffe708e4bfb3694a8c538b))

* fix: use click timer to enable lightbox double-click native sizing (JTN-262)

Single click closed the lightbox before dblclick could fire, making the native-sizing toggle
  unreachable. Replace the separate click/dblclick handlers with a 300 ms click timer that
  distinguishes single vs double click.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* ci: retrigger workflow

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Use explicit None check for PIL Image in WaveshareDisplay (JTN-263)
  ([#186](https://github.com/jtn0123/InkyPi/pull/186),
  [`4f67866`](https://github.com/jtn0123/InkyPi/commit/4f6786610867306e1c19b52c2f531202e46e0a31))

* fix: use explicit None check for PIL Image in WaveshareDisplay (JTN-263)

Replace deprecated `if not image:` with `if image is None:` in both WaveshareDisplay and InkyDisplay
  to avoid TypeError on modern Pillow versions.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* ci: retrigger workflow

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.4.31 (2026-04-08)

### Bug Fixes

- Bump requests 2.33.0 + black 26.3.1 (CVE fixes)
  ([`ed86b66`](https://github.com/jtn0123/InkyPi/commit/ed86b66816fb4ee086b0ceadccad3c76a8a10907))

- Bump requests to 2.33.0 (CVE fix for insecure temp file reuse)
  ([`5511f89`](https://github.com/jtn0123/InkyPi/commit/5511f899074fe10e124a8869e5fa89b61aca8fd7))


## v0.4.30 (2026-04-08)

### Bug Fixes

- Bump SonarSource/sonarqube-scan-action v5 → v7 (CVE fix)
  ([`90a4580`](https://github.com/jtn0123/InkyPi/commit/90a45809ffba3178dda6cbf42b05cf6cae28ada7))


## v0.4.29 (2026-04-08)

### Bug Fixes

- Remove User-Agent header to prevent CORS preflight (JTN-261)
  ([#177](https://github.com/jtn0123/InkyPi/pull/177),
  [`597ca1f`](https://github.com/jtn0123/InkyPi/commit/597ca1f2914bf207324f693cd9777d0b0edbdb32))

* fix: remove User-Agent header to prevent CORS preflight (JTN-261)

Custom User-Agent header in api_validator.js triggered CORS preflight requests, causing false
  "endpoint unreachable" errors on external APIs. Removed the header since browsers set their own
  and it's forbidden in the Fetch spec. Added test asserting no custom User-Agent is set.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* fix: make User-Agent header check case-insensitive in test

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Scope fetch wrapper state per operation (JTN-260)
  ([#176](https://github.com/jtn0123/InkyPi/pull/176),
  [`3fe36ae`](https://github.com/jtn0123/InkyPi/commit/3fe36ae72732b0b6c414ef55df1f94904b656d15))

* fix: scope fetch wrapper state per operation to prevent stuck submissions (JTN-260)

Concurrent form submissions shared mutable module-level state (fetchWrapped, fetchTimeoutId), so if
  form B submitted before form A's fetch returned, B's operation was silently skipped and
  permanently stuck.

Fix: move all per-operation state (operationCompleted, localTimeoutId, previousFetch) into the
  submit handler's closure. Each submission installs its own wrappedFetch that delegates to the
  fetch that was current at submission time, forming a safe chain. finishOperation restores
  previousFetch only when the active wrapper belongs to this operation.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* fix: remove dead nativeFetch binding and associated test

nativeFetch was declared but never referenced after the JTN-260 concurrent fetch-wrapper refactor;
  replaced entirely by per-operation previousFetch. Remove the unused binding and the test that
  asserted its presence.

* style: fix black formatting

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.4.28 (2026-04-08)

### Bug Fixes

- Cache response data instead of full Response objects (JTN-267)
  ([#179](https://github.com/jtn0123/InkyPi/pull/179),
  [`481113b`](https://github.com/jtn0123/InkyPi/commit/481113b7ea96387c064f695e11f12e7947297e52))

Store only status_code, headers, and content bytes in HTTPCache entries, reconstructing a
  lightweight Response on hit to prevent socket connections from being held open and exhausting the
  connection pool.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Handle owner/repo format in GitHub stars plugin (JTN-264)
  ([#180](https://github.com/jtn0123/InkyPi/pull/180),
  [`df9a6ed`](https://github.com/jtn0123/InkyPi/commit/df9a6ede3d9d2c654490d402cfc18e589c474e68))

Placeholder suggested "owner/repo" but code prepended username, producing invalid API paths like
  "username/owner/repo". Now detects "/" in the repository field and uses it directly; updated
  placeholder to "repository-name" to clarify expected input.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.4.27 (2026-04-08)

### Bug Fixes

- Respect unit preference for OWM visibility display (JTN-252)
  ([#178](https://github.com/jtn0123/InkyPi/pull/178),
  [`3a0efee`](https://github.com/jtn0123/InkyPi/commit/3a0efee7e2bed5c02da28df6bceaebdd06eebbdc))

OWM visibility always showed "km" regardless of the user's unit preference. Now converts metres to
  miles for imperial users and labels with "mi" accordingly.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.4.26 (2026-04-08)

### Bug Fixes

- Allow INKYPI_ENV to override default config path (JTN-259)
  ([#175](https://github.com/jtn0123/InkyPi/pull/175),
  [`fea64a1`](https://github.com/jtn0123/InkyPi/commit/fea64a1105c9fa64a72c3b9c379eed49ee51edf1))

Config._determine_config_path step 2 previously used getattr(type(self), "config_file") which always
  matches the base Config default (device.json path), making INKYPI_ENV=dev unreachable when
  device.json exists.

Fix: compare the class attribute against the computed base default (_base_default =
  base_dir/config/device.json). Only treat it as an explicit override when the value has been
  changed from that default (e.g. by CLI mutation or test monkeypatching). Adds a regression test
  that verifies INKYPI_ENV=dev selects device_dev.json even when device.json also exists.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Convert checkbox values to boolean in settings (JTN-231)
  ([#171](https://github.com/jtn0123/InkyPi/pull/171),
  [`1238f55`](https://github.com/jtn0123/InkyPi/commit/1238f55eef8ab19748fff5561319ec3a91967a3c))

Settings checkboxes stored raw HTML "on"/None instead of proper booleans. Convert inverted_image and
  log_system_stats fields with == "on" comparison.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Handle null tier in GitHub sponsors plugin (JTN-254)
  ([#173](https://github.com/jtn0123/InkyPi/pull/173),
  [`47cf3e1`](https://github.com/jtn0123/InkyPi/commit/47cf3e14ef82d54ee409d63be80bc08189c97f13))

Safely handle null tier entries from GitHub GraphQL API using (s.get("tier") or {}).get(..., 0) and
  use round() instead of int() for correct rounding of monthly totals.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Make calendar view range datetimes timezone-aware (JTN-233)
  ([#174](https://github.com/jtn0123/InkyPi/pull/174),
  [`31231f2`](https://github.com/jtn0123/InkyPi/commit/31231f29c3dfd900c9c067f41cb371270b270650))

get_view_range created naive datetimes that crashed when compared with tz-aware iCal events. Now
  passes tzinfo from current_dt to all datetime constructors in the method.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Use parsedate_to_datetime for correct UTC handling (JTN-258)
  ([#172](https://github.com/jtn0123/InkyPi/pull/172),
  [`e07c9b1`](https://github.com/jtn0123/InkyPi/commit/e07c9b15c4407e0b79e1fd60e3bd53bf9ed7c02d))

Replace strptime with %Z (unreliable timezone handling) with email.utils.parsedate_to_datetime which
  always returns timezone-aware datetimes, ensuring correct UTC comparison against file mtime.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.4.25 (2026-04-07)

### Bug Fixes

- Swap collapsible section arrow icon direction (JTN-244)
  ([#170](https://github.com/jtn0123/InkyPi/pull/170),
  [`0c70874`](https://github.com/jtn0123/InkyPi/commit/0c70874d95524b6c975feae28f941a64efed6362))

The icon ternary in toggleCollapsible used isOpen (pre-toggle state) so the arrow pointed the wrong
  way after every click. Swapping to `isOpen ? "▼" : "▲"` makes the icon reflect the post-toggle
  (current) state. Added a regression test.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.4.24 (2026-04-07)

### Bug Fixes

- Add default for get_resolution to prevent TypeError (JTN-239)
  ([#168](https://github.com/jtn0123/InkyPi/pull/168),
  [`3a7666c`](https://github.com/jtn0123/InkyPi/commit/3a7666c21203b70f6e95da067ccee3502c3a809f))

get_resolution() now falls back to [800, 480] when the "resolution" key is absent from config,
  preventing a TypeError on unpack of None. Also updated mock_get_config helpers in two plugin tests
  to accept the new default keyword argument.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Correct word clock hour at minute 33 (JTN-253)
  ([#167](https://github.com/jtn0123/InkyPi/pull/167),
  [`038454c`](https://github.com/jtn0123/InkyPi/commit/038454c159f8a7a479c210dcc7a2c6821e42d121))

At minute 33, the boundary condition `minute > 33` was False so the word clock displayed "TO
  [current hour]" instead of "TO [next hour]". Changed to `minute >= 33` so the TO range starts
  correctly at 33. Added a regression test asserting minute 33 shows the next hour.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Reset image hash on display failure to allow retry (JTN-255)
  ([#169](https://github.com/jtn0123/InkyPi/pull/169),
  [`5f31db4`](https://github.com/jtn0123/InkyPi/commit/5f31db4371ae1e0dd9f1422a905b34d3daea2569))

_last_image_hash was set before display_image() ran, so any transient failure permanently prevented
  retry of the same image. Now saves the previous hash and restores it in an except block if display
  fails, ensuring the next refresh cycle will attempt the image again.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.4.23 (2026-04-07)

### Bug Fixes

- Url-encode playlist names and plugin instance in fetch URLs (JTN-234, JTN-240)
  ([#164](https://github.com/jtn0123/InkyPi/pull/164),
  [`cc66d76`](https://github.com/jtn0123/InkyPi/commit/cc66d7691bd1900988759d0440fce66181d53a61))

Wrap playlist names with encodeURIComponent() at all three fetch call sites in playlist.js so names
  containing spaces or special chars reach the server correctly. Replace Jinja string concatenation
  for update_instance URL in plugin.html with url_for() accepting the real instance name, which lets
  Flask percent-encode it properly. Add static-JS and integration tests for both fixes.

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>


## v0.4.22 (2026-04-07)

### Bug Fixes

- Eliminate TOCTOU race in start_update (JTN-249)
  ([#166](https://github.com/jtn0123/InkyPi/pull/166),
  [`465e7b7`](https://github.com/jtn0123/InkyPi/commit/465e7b72f5d94f601a88161af0154ab961a7b38f))

* fix: eliminate TOCTOU race in start_update by atomically checking and setting running state

The update guard previously released _update_lock after the running check but before flipping state,
  allowing two concurrent requests to both pass the guard. The check and state mutation are now
  inlined inside the same lock acquisition. Added TestStartUpdateTOCTOURace with an atomicity
  assertion and a concurrent-request test verifying exactly one 200 and one 409.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

* test: add TOCTOU race guard tests for start_update (JTN-249)

Verify that concurrent POST /settings/update requests cannot both succeed (one must get 409), and
  that the running-flag flip happens while the lock is still held — proving check-and-set atomicity.

* fix: release lock if accidentally acquired in TOCTOU test

In _SpyDict.__setitem__, if acquire(blocking=False) unexpectedly succeeds, the lock is now released
  immediately to prevent deadlock/leak.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

---------

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>

- Enforce min cycle interval and validate new_name in update_playlist
  ([#163](https://github.com/jtn0123/InkyPi/pull/163),
  [`e33219c`](https://github.com/jtn0123/InkyPi/commit/e33219ced4f18cedd2c90e96398e0ce034e9dda9))

JTN-232: Change max(0, cm) to max(1, cm) in _apply_cycle_override so cycle_minutes=0 produces 60
  seconds instead of 0, preventing an infinite loop in the refresh scheduler.

JTN-256: Call _validate_playlist_name() on new_name in update_playlist, matching the validation
  already present in create_playlist. Rejects names with special characters or over 64 chars with a
  400 error.

Adds three regression tests covering both fixes.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Escape HTML in innerHTML interpolations to prevent XSS (JTN-242, JTN-243)
  ([#165](https://github.com/jtn0123/InkyPi/pull/165),
  [`74aa692`](https://github.com/jtn0123/InkyPi/commit/74aa692bb72b39776dff1e4867d3e298e377d234))

Add escapeHtml helpers in progressive_disclosure.js, enhanced_progress.js, and skeleton_loader.js;
  apply them wherever user-controlled or server-supplied strings are interpolated into innerHTML
  template literals. Add structural tests verifying the escape pattern is present in each file.

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>


## v0.4.21 (2026-04-07)

### Bug Fixes

- Add coverage for form and header-priority CSRF token extraction paths
  ([`cfc3ec0`](https://github.com/jtn0123/InkyPi/commit/cfc3ec07943372df1d6aee4563e0db0deccef14a))

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Add integration tests exercising production CSRF middleware per CodeRabbit
  ([`5845b6a`](https://github.com/jtn0123/InkyPi/commit/5845b6a388d4567def3a3a7b881df7d764641a76))

Wire tests through the real _setup_csrf_protection middleware instead of a duplicated fixture,
  validating JTN-224 and JTN-257 end-to-end.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Extract _extract_csrf_token_from_request to reduce complexity (Sonar S3776)
  ([`686c0d4`](https://github.com/jtn0123/InkyPi/commit/686c0d497c8ba43e4b9398c9553c66624a3965b4))

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Harden CSRF protection for new sessions and sendBeacon requests
  ([`12124c8`](https://github.com/jtn0123/InkyPi/commit/12124c8a795710be74c772aa108b5c7aff13d320))

JTN-224: New sessions making their first POST were silently allowed through because the
  missing-token branch returned None instead of a 403 response. Now correctly calls json_error to
  reject the request.

JTN-257: sendBeacon in client_errors.js bypassed CSRF because it cannot send custom headers. Fix
  embeds the CSRF token (from the csrf-token meta tag) in the JSON body as _csrf_token, and updates
  the server-side check to also read it from the JSON body. The fetch() fallback also sends
  X-CSRFToken header.

Adds targeted unit tests for both fixes.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Update CI smoke tests to include CSRF tokens in POST requests
  ([`759df80`](https://github.com/jtn0123/InkyPi/commit/759df80302babaf81eedb94ddef6b72c373d1553))

The JTN-224 fix rejects POST requests without CSRF tokens. Update smoke tests to establish a session
  cookie and extract the token from the HTML meta tag before issuing POST requests.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.4.20 (2026-04-07)

### Bug Fixes

- Address CodeRabbit nitpicks — log overlap warning failure, harden test preconditions
  ([`81a3cd8`](https://github.com/jtn0123/InkyPi/commit/81a3cd8fc5875d5af556de2593c68e120f711849))

- Log debug message on overlap warning failure instead of bare pass - Explicitly set
  refresh_info.plugin_id=None in dashboard tests - Ensure Default playlist exists in update test

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Extract _default_overlap_warning helper and add coverage tests
  ([`52d12be`](https://github.com/jtn0123/InkyPi/commit/52d12bef70c3dc942774e22852afa4786aa2b821))

- Extract duplicated Default-overlap warning logic from create_playlist and update_playlist into
  _default_overlap_warning() helper (Sonar S3776) - Merge main to pick up PRs 155+157 - Add 3 unit
  tests for the helper to satisfy 80% new code coverage gate

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Jtn-217 playlist-Default overlap warning, JTN-213 dashboard empty state
  ([`024beb6`](https://github.com/jtn0123/InkyPi/commit/024beb62969f47043df1c9ce244e012ed4bfe68c))

JTN-217: create_playlist and update_playlist now check if the saved

playlist overlaps the built-in Default playlist (which is the 00:00-24:00 catch-all). When an
  overlap is found, the success response includes a `warning` field explaining that the new playlist
  takes priority during its active hours. The playlist.js frontend stores the warning in
  sessionStorage and shows it as a warning toast after reload. The warning is suppressed when the
  playlist being created/updated is itself named "Default".

JTN-213: main.py now computes `has_preview` (processed or current image file exists) and passes it
  to the inky.html template. The overviewEmpty panel shows "Last display info unavailable." instead
  of "Display a plugin to see details here." when a preview image exists but refresh_info has no
  plugin_id — avoiding the misleading empty state on first page load after a display has run.

Tests added for both fixes covering positive and negative cases.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

- Reduce playlist route complexity and add type annotations (Sonar S3776 + CodeRabbit)
  ([`6b2692e`](https://github.com/jtn0123/InkyPi/commit/6b2692e69d91b5b51cca1ec37591f1c0209de9eb))

Extract _parse_playlist_request_data, _validate_playlist_times, and _apply_cycle_override helpers to
  bring create_playlist and update_playlist under the cognitive complexity limit. Add return type
  annotations to test helpers per CodeRabbit review.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Remove unused model import flagged by ruff F401
  ([`9ed2a4a`](https://github.com/jtn0123/InkyPi/commit/9ed2a4aec9a45e2ddcd25ec5a26df405f4d634af))

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Refactoring

- Extract shared test helpers per CodeRabbit nitpick
  ([`07011bd`](https://github.com/jtn0123/InkyPi/commit/07011bdc5e000c38e8a6d185cd61acf6126a3101))

Extract _ensure_default_playlist and _assert_overlap_warning helpers to reduce duplication across
  playlist overlap warning tests.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.4.19 (2026-04-07)

### Bug Fixes

- Edited API key values no longer silently discarded on save
  ([`df75dfc`](https://github.com/jtn0123/InkyPi/commit/df75dfc9761befe0fc744580f9fc571ea87b187e))

In saveGenericKeys(), existing rows with a new value entered by the user now send { key, value }
  instead of always sending keepExisting:true. Adds two regression tests covering both the update
  and preserve paths.

Fixes JTN-250.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Include value: null in keepExisting test payload per CodeRabbit review
  ([`8b7273b`](https://github.com/jtn0123/InkyPi/commit/8b7273b9d2be0d12beaeeae471f1544b2907dd51))

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.4.18 (2026-04-07)

### Bug Fixes

- Block SSRF in ImageURL and ImageAlbum plugins (JTN-226, JTN-229)
  ([`649cd1c`](https://github.com/jtn0123/InkyPi/commit/649cd1c6eb02d2247324dc8a3534550e3cc332bb))

Call validate_url() before fetching user-supplied URLs in both the ImageURL plugin and the Immich
  provider in ImageAlbum, preventing requests to localhost, private IP ranges, and cloud metadata
  endpoints. Add SSRF-specific tests for both plugins; update existing ImageAlbum tests to mock DNS
  so validate_url passes for public hostnames.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

- Extract _fetch_immich_image to reduce cognitive complexity (Sonar S3776)
  ([`eabea38`](https://github.com/jtn0123/InkyPi/commit/eabea38768caada9a571fcc7ff330759b0e5eccc))

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.4.17 (2026-04-07)

### Bug Fixes

- Add defensive href checks and integration tests for dashboard plugin cards (JTN-214)
  ([`64e6366`](https://github.com/jtn0123/InkyPi/commit/64e6366f7fbdb31a5367080c0cdbb7627934071b))

Adds a console.warn in dashboard_page.js init() to surface plugin cards missing href attributes, and
  adds two integration tests asserting that all plugin card links render with valid hrefs and that
  each linked plugin page returns HTTP 200.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

### Documentation

- Mark hourly weather, saturation, and bi-color as implemented (JTN-219)
  ([`cd97f8f`](https://github.com/jtn0123/InkyPi/commit/cd97f8fe022d99793ecdeb0d3313900ea81513e1))

All three features previously marked :soon: are already present in the codebase — remove the
  placeholder footnote and flip each row to ✅.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

### Refactoring

- Reduce Sonar maintainability debt in settings_page.js (JTN-206)
  ([`0935376`](https://github.com/jtn0123/InkyPi/commit/0935376a21293f9fe5202ecdad384795b5027a4e))

Address 50 Sonar findings across 6 rules: optional chaining (S6582, 18 fixes), logged catch blocks
  (S2486, 9 fixes), window→globalThis (S7764, 6 fixes), for...of over forEach (S7773, 10 fixes), and
  move pure helpers isErrorLine/isWarnLine/prefKey to IIFE scope (S7721). No behaviour changes.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

- Sonar maintainability cleanup for plugin_page.js (JTN-205)
  ([`acbc9b6`](https://github.com/jtn0123/InkyPi/commit/acbc9b6fe52f8f000cfc85c0a3d38689f8f951b9))

- Replace all window.* references with globalThis.* (S7764, 23 findings) - Extract
  syncModalOpenState, setHidden, buildProgressKey, fadeSkeleton, updateCombinedColorPreview to IIFE
  scope instead of inner functions (S7721, 8 findings) - Apply optional chaining for foo && foo.bar
  patterns (S6582, 7 findings) - Add console.warn to previously empty catch blocks (S2486, 3
  findings)

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>


## v0.4.16 (2026-04-04)

### Bug Fixes

- Remove unused timeout_s param and add tests for extracted helpers
  ([`778fb1c`](https://github.com/jtn0123/InkyPi/commit/778fb1c4ae0c0570fd53c61e4cdf87327d905572))

- Remove unused timeout_s parameter from _cleanup_subprocess (CodeRabbit) - Add 7 tests for
  _timeout_msg, _cleanup_subprocess, and _handle_process_result to satisfy 80% new code coverage
  gate

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Validate refreshTime as HH:MM format per CodeRabbit review
  ([`6bcfe87`](https://github.com/jtn0123/InkyPi/commit/6bcfe877e87da914c21a90cada4fdda469702d5c))

Reject non-string, empty, and malformed refreshTime values with a 422 response before persisting
  them to the playlist config.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Documentation

- Add fork comparison table to README
  ([`1bf8dfa`](https://github.com/jtn0123/InkyPi/commit/1bf8dfa10d28a09af229fc087449a74c9c3325d1))

Add "What's New in This Fork" section with a feature comparison table showing what this fork adds
  (security, UX, performance) and what upstream has that we plan to port (tracked in JTN-219).

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Refactoring

- Extract helpers to reduce cognitive complexity in _execute_with_policy (JTN-209)
  ([`e5f4b60`](https://github.com/jtn0123/InkyPi/commit/e5f4b60ec9cd6d4871b6fe1486b9646b2c19b67a))

Extract _timeout_msg(), _cleanup_subprocess(), and _handle_process_result() from the 43-complexity
  _execute_with_policy() method to flatten nested conditionals and eliminate duplicate timeout
  message strings.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

- Reduce cognitive complexity in playlist blueprint (JTN-207)
  ([`beecf87`](https://github.com/jtn0123/InkyPi/commit/beecf87c1e5d9b502a4c1bca34d6b8cb78f57523))

Extract shared helpers to eliminate duplicate logic and flatten deeply nested control flow in
  playlist.py:

- Add _CODE_VALIDATION, _MSG_INVALID_TIME_FORMAT, _MSG_SAME_TIME, _MSG_TIME_OVERLAP constants —
  eliminates ~9 duplicated string literals - Extract _check_playlist_overlap() — deduplicate
  overlap-check loops shared by create_playlist and update_playlist - Extract
  _validate_plugin_refresh_settings() — pull the deeply-nested interval/scheduled refresh validation
  out of add_plugin - Extract _safe_next_index() and _safe_until_next_min() — isolate the
  error-prone index/time arithmetic that fed the rotation ETA logic - Extract
  _compute_playlist_rotation_eta() — replace the 40-line nested ETA block in playlists() and the
  duplicate in playlist_eta() with one clean loop; both callers now use the same helper

No behavior changes; all 2096 tests pass.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

- **JTN-208**: Reduce cognitive complexity in config and utility modules
  ([`7441923`](https://github.com/jtn0123/InkyPi/commit/744192373c23947a7fd3e223e9ff5f8009dfb53f))

Extract helper functions to flatten nested logic in _validate_device_config,
  _sanitize_config_for_log, handle_request_files, http_get, and take_screenshot. Pure refactor — no
  behavior changes.

- config.py: _format_validation_message(), _sanitize_playlist() - app_utils.py:
  _process_uploaded_file() - http_utils.py: _resolve_timeout() - image_utils.py:
  _find_browser_command(), _SCREENSHOT_ERROR_PREFIX constant

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>


## v0.4.15 (2026-04-04)

### Bug Fixes

- Address CodeRabbit review — isfile check and plugin cleanup settings
  ([`71d904e`](https://github.com/jtn0123/InkyPi/commit/71d904eebf287506569f5706099296f4c3190810))

- history.py: use os.path.isfile() instead of os.path.exists() in _validate_and_resolve_history_file
  to reject directories - plugin.py: capture instance settings before deletion and pass them to
  _cleanup_plugin_resources so plugins like image_upload can clean up their own files

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Extract _parse_filename_from_request to eliminate duplicated blocks
  ([`5362486`](https://github.com/jtn0123/InkyPi/commit/5362486b200a62123d8fdc26233557f35c4222ed))

Sonar flagged lines 260-275 and 290-304 as near-identical (3.6% duplication exceeded the 3% gate).
  Both history_redisplay and history_delete parsed JSON request bodies identically — now share a
  single helper.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Validate deviceName and zero interval in settings save (JTN-218)
  ([`f136a09`](https://github.com/jtn0123/InkyPi/commit/f136a09ef1c5b92115028ecfc180cc88e800432a))

Backend now returns 422 with field-level details when deviceName is missing/empty/whitespace, or
  when interval is zero, preventing silent no-op saves that left the UI without any error feedback.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

- **jtn-215**: Hide visibility toggle for unconfigured keys and clarify clear vs delete controls
  ([`43b67a7`](https://github.com/jtn0123/InkyPi/commit/43b67a7113c1e24c546b14742563a1b513895d47))

- Skip adding the show/hide toggle button for password inputs with no value (unconfigured providers
  no longer show a meaningless "Show key" button) - Add distinct title tooltips to the clear (×) and
  Delete buttons so users understand that clear only empties the field until saved, while delete
  permanently removes the key from .env - Update delete button aria-label to include "permanently"
  for screen-reader clarity - Add integration tests covering all three behaviours

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

### Refactoring

- Reduce Sonar S1192/S3776 maintainability debt in blueprint files (JTN-212)
  ([`1e32c37`](https://github.com/jtn0123/InkyPi/commit/1e32c3715c43f151fc81192c6341e053971c5426))

Extract duplicate string constants (_CONFIG_KEY, _PLUGIN_ID, _ERR_INTERNAL, _ERR_NOT_FOUND,
  _ERR_INVALID_FILENAME, _EXT_PNG, _EXT_JSON) and reduce cognitive complexity in plugin.py,
  history.py, and apikeys.py by extracting helpers: _cleanup_plugin_resources(),
  _validate_and_resolve_history_file(), _has_invalid_control_chars(), and _validate_api_key_entry().
  No behaviour changes.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.4.14 (2026-04-04)

### Bug Fixes

- Resolve merge conflicts with main after PRs 146+148 merged
  ([`5e21a6c`](https://github.com/jtn0123/InkyPi/commit/5e21a6c44a02a32f28c65023d8770531dc8929e6))

- Keep both IIFE-level helpers (copy + form snapshot/restore) - Include all tests from both branches

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.4.13 (2026-04-04)

### Bug Fixes

- Address Sonar issues and CodeRabbit feedback for dirty-state tracking
  ([`296e195`](https://github.com/jtn0123/InkyPi/commit/296e195486a8609fcd7ae3d0f2ec04b0a79c5ce5))

- Extract appendGeoData to reduce handleAction cognitive complexity - Accept form parameter in
  getFormSnapshot to satisfy outer-scope rule - Use optional chaining (saveBtn?.disabled,
  saveBtn?.textContent) - Replace form.reset() with restoreFormFromSnapshot on save failure - Add
  sonar.qualitygate.wait=true to enforce quality gate in CI

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Disable Save until form is dirty and reset after successful save (JTN-204)
  ([`e37b071`](https://github.com/jtn0123/InkyPi/commit/e37b0715ef1f6bf33c6d3b5122f1cf3f95cdb433))

Track a form snapshot on init so the Settings Save button starts disabled and only enables when a
  value actually changes. After a successful save the snapshot resets and the button is disabled
  again, giving clear feedback that nothing further needs saving. Add integration tests confirming
  the Save button and Image Processing sliders are present in the rendered page.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

- Move helper functions to outer scope and handle catch for Sonar
  ([`eb67fc4`](https://github.com/jtn0123/InkyPi/commit/eb67fc48fd7e6a9265950eff39f0f6ad96e47e85))

- Move getFormSnapshot and restoreFormFromSnapshot to IIFE level (S7721) - Log error in catch block
  instead of discarding (S2486)

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.4.12 (2026-04-04)

### Bug Fixes

- **a11y**: Add aria-labels with filenames/key names to history and API key rows (JTN-202)
  ([`1bf0f67`](https://github.com/jtn0123/InkyPi/commit/1bf0f67d42ea6d9edfbc9ba9dc959afe99d0d08f))

History action buttons (Display, Download, Delete) now include aria-label="<action> <filename>" so
  screen readers can distinguish each row. API keys list-view delete button and inputs now include
  the key name in their aria-labels; card-view delete button includes the provider label.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>


## v0.4.11 (2026-04-04)

### Bug Fixes

- Apply log sanitization consistently across all model.py warning paths
  ([`97f07fe`](https://github.com/jtn0123/InkyPi/commit/97f07fe0d1f9848681f9686330eda251e8e69405))

Address CodeRabbit review: extend _sanitize_log_value() usage to all remaining user-controlled log
  parameters (update_plugin, delete_plugin, scheduled time, snooze_until) for complete log-injection
  mitigation.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Remove unused pytest import flagged by ruff
  ([`2c030b9`](https://github.com/jtn0123/InkyPi/commit/2c030b9ddf75d450a1c420d05fd319441f84f87b))

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Resolve Sonar S2583 and S5145 in display_manager.py and model.py
  ([`01d07f5`](https://github.com/jtn0123/InkyPi/commit/01d07f5d264f1bd866fe6817646581a1db1a1b9d))

Initialize InkyDisplay and WaveshareDisplay to None before try/except import blocks so Sonar flow
  analysis correctly recognizes the variables may remain None (S2583). Add _sanitize_log_value
  helper in model.py to strip control characters from user-controlled data before logging (S5145).

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Sanitize remaining user-controlled log values in model.py
  ([`0b3bb30`](https://github.com/jtn0123/InkyPi/commit/0b3bb3022042414312716e0b2dce5278132b5b11))

Address second CodeRabbit review: apply _sanitize_log_value() to add_plugin_to_playlist
  playlist_name and is_show_eligible self.name for complete log-injection coverage.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Testing

- Add coverage for _sanitize_log_value helper to meet Sonar gate
  ([`0e991e5`](https://github.com/jtn0123/InkyPi/commit/0e991e5ac3f41736faa8038a44e95b9380a4b672))

Add 8 tests covering control char stripping, clean passthrough, non-string conversion, and empty
  input to bring new code coverage above the 80% quality gate threshold.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Assert sanitized log content per CodeRabbit review
  ([`7f182df`](https://github.com/jtn0123/InkyPi/commit/7f182dfe83437485442e95991e764576e0fbf8d7))

Use caplog to verify warning messages are emitted with control characters stripped, not just that
  the return value is False.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Cover add_plugin_to_nonexistent_playlist warning path
  ([`6ce9878`](https://github.com/jtn0123/InkyPi/commit/6ce987855d20b6bda82d5c63853dc4471abda94b))

Exercises the sanitized log line at model.py:190 to bring new code coverage above the 80% Sonar
  quality gate.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Cover update_playlist warning path for Sonar 80% gate
  ([`457ecc9`](https://github.com/jtn0123/InkyPi/commit/457ecc992493f9573594080ea4149c611e67f818))

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.4.10 (2026-04-04)

### Bug Fixes

- Move copy helpers to outer scope and handle catch for Sonar
  ([`2b92fef`](https://github.com/jtn0123/InkyPi/commit/2b92fef244d568b449a414cf71f04916dfa1252e))

- Move showCopyFeedback and copyViaExecCommand to IIFE level (S7721) - Log error in catch block
  instead of discarding (S2486) - Remove eslint-disable-line comment (S7724)

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Prevent Settings page thread starvation (JTN-195, JTN-196)
  ([`aa50e39`](https://github.com/jtn0123/InkyPi/commit/aa50e393c2075609781eaa1c2c45d653a7b00f9b))

The Settings page suffered from thread starvation under Waitress's 4-thread pool: initProgressSSE()
  holds one thread, then checkForUpdates() fires a fetch to /api/version whose backend
  _check_latest_version() makes a 10-second GitHub API call—blocking a second thread. With other
  requests competing, all threads get exhausted, causing the "Manage API Keys" link to hang
  (JTN-195) and the version check to show "CHECKING..." forever (JTN-196).

Changes: - Add 8-second AbortController timeout to the client-side version check fetch so it
  resolves to "Check failed" instead of hanging indefinitely - Reduce backend GitHub API timeout
  from 10s to 5s to free threads faster

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Resolve Sonar issues in copyLogsToClipboard and enforce quality gate
  ([`fa548f9`](https://github.com/jtn0123/InkyPi/commit/fa548f96522b18fc20e062ee5874d85f4f5320cb))

- Replace var with const/let, extract nested functions to reduce depth - Use globalThis instead of
  window, el.remove() instead of removeChild - Handle catch exception, add
  sonar.qualitygate.wait=true

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Set inert attribute on background elements when lightbox opens
  ([`8bf8f8e`](https://github.com/jtn0123/InkyPi/commit/8bf8f8ed4f2586c0006ffbb81c81112c623bc5a3))

When the lightbox modal opens, background elements remained interactable despite aria-modal and
  focus trap. This adds the inert attribute to all sibling elements of the modal on open and removes
  it on close, ensuring screen readers and keyboard navigation cannot reach background content.

Fixes JTN-203

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Settings timezone default and log copy fallback (JTN-216, JTN-197)
  ([`a38c23b`](https://github.com/jtn0123/InkyPi/commit/a38c23babc870794604b548e81a417cad5cc8fd8))

- JTN-216: Use Jinja get() with 'UTC' default for timezone input so it renders correctly when config
  has no timezone key - JTN-197: Replace silent clipboard write with HTTP-fallback (execCommand) and
  visual button feedback ('Copied!'/'Copy failed') using correct button id logsCopyBtn - Tests: two
  new integration tests verify UTC default and configured value rendering

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>


## v0.4.9 (2026-04-04)

### Bug Fixes

- Add /playlists redirect and show plugin display names on dashboard
  ([`b85f1c2`](https://github.com/jtn0123/InkyPi/commit/b85f1c28371bad120f4afba19f1c16f4efe2e3c3))

JTN-198: Add redirect from /playlists (plural) to /playlist so users hitting the plural URL no
  longer get a 404.

JTN-193: Build a plugin_names lookup dict in the dashboard template and use display_name instead of
  raw plugin_id (e.g. "AI Image" instead of "AI_IMAGE") in the status chip, now-showing, and next-up
  sections.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.4.8 (2026-04-04)

### Bug Fixes

- Increase Waitress threads from 1 to 4 to prevent request blocking
  ([`90c44c2`](https://github.com/jtn0123/InkyPi/commit/90c44c214bc55ea4f12fccbfc16453490cd8d4f4))

Waitress was configured with threads=1, which meant Chrome's HTTP/1.1 keep-alive connections would
  monopolize the single worker thread. This caused all subsequent AJAX requests (redisplay, clear
  history, pagination) to hang indefinitely, appearing as silent no-ops to the user.

Increasing to 4 threads matches the Raspberry Pi Zero 2 W's quad-core CPU and ensures concurrent
  requests are handled properly.

Fixes JTN-191, JTN-192, JTN-199, JTN-200

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.4.7 (2026-04-04)

### Bug Fixes

- Remove orphaned vendor/icons/makin_things submodule index entry
  ([`16d6d4b`](https://github.com/jtn0123/InkyPi/commit/16d6d4bf6bd3a235249f1610ae9e022452146ed3))

The git index contained a submodule entry for vendor/icons/makin_things with no corresponding URL in
  .gitmodules, causing git submodule commands to fail with "no submodule mapping found" errors.

Fixes JTN-201

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Documentation

- Polish README for fork — expand plugins, add badges, trim verbose sections
  ([`cd059cb`](https://github.com/jtn0123/InkyPi/commit/cd059cb7874d109723e394703ee794ace6a40388))

- Re-point repo links to jtn0123/InkyPi - Add CI, SonarCloud, Python, and license badges - Expand
  plugin list from 6 to all 20 in a categorized table - Add Development quick-start section - Add
  Documentation links section - Trim Testing section (detail moved to docs/testing.md) - Remove
  upstream-only sections (Sponsoring, Roadmap/Trello, Acknowledgements, wiki) - Fix typos
  (aesthetic, LEDs, uninstall) - Add single-line attribution to original repo

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.4.6 (2026-04-04)

### Bug Fixes

- Correct fallback path for benchmarks.db default location
  ([`e466898`](https://github.com/jtn0123/InkyPi/commit/e4668981a0167666f5335be11491e3ba68111af7))

The fallback when BASE_DIR is missing used __file__ (src/benchmarks/), making project_root resolve
  to src/ instead of the actual project root. Now uses abspath to go up one level from
  src/benchmarks/ to src/.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Harden falsy BASE_DIR handling and add coverage for runtime paths
  ([`ded6017`](https://github.com/jtn0123/InkyPi/commit/ded60172e20a9611f18f950258dacd6897cd38d3))

- Add `or fallback` guard for falsy BASE_DIR in benchmark_storage - Add test for mock_display
  default output dir under runtime/ - Add test for benchmark_storage falsy BASE_DIR fallback

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Include benchmarks module in coverage collection
  ([`61180f3`](https://github.com/jtn0123/InkyPi/commit/61180f342dac7f228e114af0e582ac7bd3570ff8))

Remove src/benchmarks/* from .coveragerc omit list — the module now has 21 passing tests at 90%
  coverage. This fixes SonarCloud quality gate which saw 0% coverage on new benchmark_storage.py
  lines.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Rebalance settings layout and move runtime artifacts (JTN-150, JTN-132)
  ([`91f93ce`](https://github.com/jtn0123/InkyPi/commit/91f93cee1babb7dc72ff0b629c6b819c55735e72))

Settings page: collapse logs panel by default on all viewports — extends the proven mobile toggle
  pattern to desktop. Settings form now gets full width; logs remain one click away via the floating
  "Show Logs" button.

Runtime artifacts: move benchmarks.db and mock_display_output defaults from src/ and project root
  into runtime/ directory. Update CI, scripts, docs, and tests to match.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Strengthen test assertions per CodeRabbit review
  ([`bc7db3a`](https://github.com/jtn0123/InkyPi/commit/bc7db3a70fe1fdf8dda6d1130a1c02677342b90f))

- Force truly falsy BASE_DIR after MockDeviceConfig init normalization - Use exact path component
  assertions instead of substring checks

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Refactoring

- Apply CodeRabbit feedback — dynamic plugin discovery and helper extraction
  ([`aa2a966`](https://github.com/jtn0123/InkyPi/commit/aa2a9664e7b154b19ba031065342fabb68f2aff5))

- Replace hardcoded _ACTIVE_PLUGINS list with dynamic directory discovery - Extract duplicated
  plugin class lookup into _get_plugin_class() helper - Add return type annotation to
  _collect_fields()

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Harden regression tests per CodeRabbit review
  ([`0f2741b`](https://github.com/jtn0123/InkyPi/commit/0f2741bbd1c8171142ed38d7ae87d062058ffc9f))

- Add override assertion to catch plugins missing build_settings_schema() - Use pathlib for
  OS-portable orphan detection - Add plugin_cls assertion guard in background fields test

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Remove 19 orphaned legacy settings.html templates (JTN-153)
  ([`22aee5a`](https://github.com/jtn0123/InkyPi/commit/22aee5a2396aed65bf5d84c74d7ff71210e05480))

All plugins now use the schema-driven form system exclusively. Delete 1,573 lines of dead HTML/JS, 1
  orphaned widget template, and 7 tests that read deleted files. Add 3 regression-guard tests to
  prevent drift back to legacy templates.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.4.5 (2026-04-04)

### Bug Fixes

- Add server-side required field validation for plugin save (JTN-187, JTN-186)
  ([`14879f0`](https://github.com/jtn0123/InkyPi/commit/14879f02f3c6867f11ee8cf46911f8c481fef727))

JTN-187: _save_plugin_settings_common() and update_plugin_instance() now validate required fields
  from the plugin schema before persisting settings. Missing required fields return 400 with a
  descriptive error message.

JTN-186: API keys page buttons verified working — listeners are correctly wired via optional
  chaining and event delegation. Added defensive console.warn guards that log when expected DOM
  elements are absent.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Playlist modal defaults and context-aware preview helper text (JTN-188, JTN-189)
  ([`fdd231d`](https://github.com/jtn0123/InkyPi/commit/fdd231d79d7704de2a5155e24a4c1f40b9d41bff))

- Change openCreateModal() defaults from 00:00-24:00 to 09:00-17:00 to avoid overlapping with the
  Default playlist time range - Make plugin.html helper text conditional: show "Update Instance"
  guidance on instance pages, "Add to Playlist" guidance on draft pages - Add tests for both fixes

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Strengthen test assertions per CodeRabbit review
  ([`8973740`](https://github.com/jtn0123/InkyPi/commit/897374033d917f0d34bb666d54e5c2dfcfd5e7dd))

Rewrite test_playlist_modal_defaults_to_non_overlapping_range to parse the openCreateModal function
  body and verify exact default values. Rewrite test_preview_helper_text_is_conditional to scope
  assertions to the workflow-help section rather than checking globally.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Use const instead of var in api_keys_page.js (SonarCloud S3504)
  ([`941d1b5`](https://github.com/jtn0123/InkyPi/commit/941d1b590d1553581f62cb60beb04bad59eef2fd))

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Refactoring

- Split oversized test modules for maintainability (JTN-133)
  ([`98c0456`](https://github.com/jtn0123/InkyPi/commit/98c0456c63c8773030f9eba6c5052158279b501a))

Split test_settings_blueprint.py (~1163 lines) into four focused modules: - test_settings_update.py:
  update/start-update operations - test_settings_save.py: save settings, validation, isolation, API
  keys - test_settings_import.py: import/export operations - test_settings_blueprint.py: logs,
  health, misc, helpers (remainder)

Split test_weather.py (~1000 lines) into three focused modules: - test_weather_providers.py:
  OpenWeatherMap/OpenMeteo API mocking - test_weather_validation.py: input validation (location,
  units, API key) - test_weather.py: core rendering/integration tests (remainder)

No test logic changed. Test count verified: 2045 before and after.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.4.4 (2026-04-04)

### Bug Fixes

- Make playlist refresh button test robust to attribute ordering
  ([`3cf87f5`](https://github.com/jtn0123/InkyPi/commit/3cf87f50b120d70f71da405535d1e9993ba2a7fb))

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Wire Edit Refresh Settings button listener on playlist page (JTN-185, JTN-151)
  ([`07c03b4`](https://github.com/jtn0123/InkyPi/commit/07c03b44ba0260fadc53849c402316f730406cda))

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Code Style

- Fix black formatting in test file
  ([`028203a`](https://github.com/jtn0123/InkyPi/commit/028203ac744858ddff34f31b716ee66ba560fed5))

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.4.3 (2026-04-04)

### Bug Fixes

- Hide desktop tab bar and deduplicate plugin page status (JTN-89, JTN-152)
  ([`e0fd64b`](https://github.com/jtn0123/InkyPi/commit/e0fd64bddc73b149b0724484bd649a52ad6901ec))

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Plugin settings UX polish — empty state, accessibility, affordances (JTN-184, JTN-174, JTN-157,
  JTN-158, JTN-154)
  ([`7f9100f`](https://github.com/jtn0123/InkyPi/commit/7f9100fd5c79727e6628669fade7f52e86096824))

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Reduce function nesting and fix label association (SonarCloud)
  ([`dcfe6ce`](https://github.com/jtn0123/InkyPi/commit/dcfe6cebf84d4f6c7e8ce223d6f785e3f4ca3220))

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Remove orphaned grid property and harden test assertions
  ([`ec6a228`](https://github.com/jtn0123/InkyPi/commit/ec6a2280c3a4e6d3913a2a0b9a65131ff7d7cba4))

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.4.2 (2026-04-04)

### Performance Improvements

- Lazy sidecar loading and early-exit in history/plugin lookups (JTN-97, JTN-91)
  ([`8d5290b`](https://github.com/jtn0123/InkyPi/commit/8d5290bf8264dbc3954cfa98bb63d14818990d37))

Push pagination offset/limit into _list_history_images so expensive stat + sidecar JSON reads only
  happen for the requested page, not all files. In plugin.py, sort .json files by filename
  descending and return on first match in latest_plugin_image, _find_history_image, and
  _find_latest_plugin_refresh_time for O(1) reads in the common case.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.4.1 (2026-04-03)

### Bug Fixes

- Add fetch timeout, AbortError handling, and failure visibility in plugin preview
  ([`4054d92`](https://github.com/jtn0123/InkyPi/commit/4054d9226a799c5cbba84e7e18e49619bbe80ad4))

- Wrap fetch with AbortController + 90s timeout so requests don't hang indefinitely (JTN-160) -
  Handle AbortError in catch block with user-friendly timeout message - Show "Failed — see error
  above" instead of "Done" when request errors (JTN-161) - Display elapsed time in progress step
  text after 15s for long-running requests

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Refactoring

- Consolidate rate limiters into shared module (JTN-103)
  ([`5ce8c06`](https://github.com/jtn0123/InkyPi/commit/5ce8c069596469ad54d96fc6cd8e85267b03cb99))

Extract four ad-hoc rate limiter implementations into two reusable, thread-safe classes in
  src/utils/rate_limiter.py:

- CooldownLimiter: fixed-window cooldown (display-next, shutdown) - SlidingWindowLimiter: per-key
  sliding window (logs API, mutation guard)

Migrate all four call sites (main.py, settings/__init__.py, _system.py, inkypi.py) to use the new
  classes, removing ~70 lines of duplicated timing/locking logic. Existing _rate_limit_ok wrapper
  kept for test compatibility. Add 16 new unit tests covering both classes plus thread safety. All
  1967 tests pass.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.4.0 (2026-04-03)

### Bug Fixes

- Add accessibility labels to color pickers and dialog semantics to modals (JTN-155, JTN-156)
  ([`76feedd`](https://github.com/jtn0123/InkyPi/commit/76feedd727279ade6e701b5477c2ee46809cb55b))

Add labeled form groups with aria-labels to GitHub contribution color pickers in both the widget
  template and legacy settings page. Add role="dialog", aria-modal, and aria-labelledby to weather
  map modals, and convert close-button spans to semantic button elements.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Hide Display Next on empty playlists and add calendar editor empty state (JTN-151, JTN-172)
  ([`acb7ea1`](https://github.com/jtn0123/InkyPi/commit/acb7ea1c1a8e6c71150ec14195c3e3ee04d5b210))

Hide the "Display Next" button when a playlist has no plugins to prevent dead-end clicks. Add
  empty-state messaging to both the schema-driven and legacy calendar repeater editors so users see
  guidance when the calendar list is empty. Includes JS safety-net guard and integration tests.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Features

- Add SSRF and path-traversal input validation (JTN-96)
  ([`c5130be`](https://github.com/jtn0123/InkyPi/commit/c5130be46767ba1255351c52472175a316b3054e))

Add security_utils module with validate_url (SSRF protection blocking
  private/loopback/link-local/reserved IPs and non-HTTP schemes) and validate_file_path
  (directory-traversal prevention). Wire them into the screenshot and image_upload plugins, and add
  comprehensive unit and integration tests.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.3.13 (2026-04-03)

### Bug Fixes

- Add loading feedback to backup/restore buttons and disable restore when no file selected (JTN-179,
  JTN-180)
  ([`7e8446e`](https://github.com/jtn0123/InkyPi/commit/7e8446e4b53de1eca787156b72a97bdf1262954d))

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Extract syncImportButton helper to resolve SonarCloud shadowing and line length
  ([`9718f04`](https://github.com/jtn0123/InkyPi/commit/9718f04be9a7234d63c7d432bf3248783af6af80))

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Resolve SonarCloud issues — optional chaining, catch logging, inline helper
  ([`7dec520`](https://github.com/jtn0123/InkyPi/commit/7dec5206ca0998dbfb0f2f06788af8806757fac2))

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.3.12 (2026-04-03)

### Bug Fixes

- Improve display-next error handling, preview a11y, and plugin empty state (JTN-178, JTN-177,
  JTN-173)
  ([`fbcbeaa`](https://github.com/jtn0123/InkyPi/commit/fbcbeaad056593b7b14cde09c091f707ad89ea61))

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Render all 6 API key provider cards in managed mode (JTN-176, JTN-159)
  ([`b963857`](https://github.com/jtn0123/InkyPi/commit/b963857b42f08cde9bbc0b273ccb58cf9da9000e))

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.3.11 (2026-04-03)

### Bug Fixes

- History page — add delete loading state and normalize metadata display (JTN-168, JTN-169)
  ([`50d0114`](https://github.com/jtn0123/InkyPi/commit/50d011457dc82735f99ba93bc6a3efc8e1bf9c82))

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Plugin validation and API key UX — enforce form checks, disable actions when key missing (JTN-162,
  JTN-163, JTN-170, JTN-171)
  ([`7587def`](https://github.com/jtn0123/InkyPi/commit/7587def1764fda6f8202fb66419cc46aaee6f081))

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Replace var with const in new JS code for SonarCloud compliance
  ([`7b31bd8`](https://github.com/jtn0123/InkyPi/commit/7b31bd85d752bf6e83ba7b3c9987196c4a3731ee))

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Replace var with const/let in new JS code for SonarCloud compliance
  ([`2b8236b`](https://github.com/jtn0123/InkyPi/commit/2b8236bdacc5fb22505c462fc5c741f861cc9ea0))

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.3.10 (2026-04-03)

### Bug Fixes

- Rename unused lambda parameter per CodeRabbit review
  ([`206a160`](https://github.com/jtn0123/InkyPi/commit/206a160dbb8e3007db4c06e4ead85d955617e395))

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Replace var with const, use RegExp.exec per SonarCloud review
  ([`3bfd5eb`](https://github.com/jtn0123/InkyPi/commit/3bfd5eb76f5d45db9268feb5b5313ee394160ce2))

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Settings log viewer — sanitize output, add clear/download feedback (JTN-166, JTN-167, JTN-175)
  ([`5469e4c`](https://github.com/jtn0123/InkyPi/commit/5469e4ccc7f415a40e6997c9324869ed89f8c05a))

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.3.9 (2026-04-02)

### Bug Fixes

- Migrate pytz→zoneinfo and align settings API key flows (JTN-114, JTN-135)
  ([`30d6247`](https://github.com/jtn0123/InkyPi/commit/30d6247ef31fce78155d31fe2ac46e94a04fa0e8))

JTN-114: Replace deprecated pytz with stdlib zoneinfo across 8 source files and all test files.
  Removes pytz==2025.2 from both requirements files and adds tzdata>=2024.1 as a cross-platform IANA
  timezone database fallback. Fixes 8 SonarCloud CRITICAL findings (python:S6890).

JTN-135: Extend settings-managed API key flows to include GITHUB_SECRET and GOOGLE_AI_SECRET —
  aligning export_settings, api_keys_page, save_api_keys, and delete_api_key with the full set of
  secrets already supported by apikeys.py and the import allowlist.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

- Remove stale pytz imports from CI smoke tests and narrow exception handling
  ([`888df30`](https://github.com/jtn0123/InkyPi/commit/888df30cc6962c8c5007646841a534578dd7b9ad))

- Replace `import pytz` with `import zoneinfo` in preflash_smoke.py and CI container smoke test
  (fixes 3 CI failures after pytz removal) - Narrow `except Exception` to `except
  (ZoneInfoNotFoundError, ValueError)` in get_timezone() per CodeRabbit review - Use specific
  ZoneInfoNotFoundError in weather timezone test

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Split compound assertion for clearer test failure output
  ([`6f9307c`](https://github.com/jtn0123/InkyPi/commit/6f9307cfb26c80f63de2ca8a0ab7e222e3556933))

Address CodeRabbit review: separate "Visibility" and "Air Quality" membership checks into individual
  assert statements.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.3.8 (2026-04-01)

### Bug Fixes

- Address CodeRabbit review feedback
  ([`2addb23`](https://github.com/jtn0123/InkyPi/commit/2addb23ce03655f71dd3eb8c99a0ef979ce37194))

- Validate keepExisting as boolean in API key save (apikeys.py) - Validate plugin_id not None in
  add_plugin (playlist.py) - Reject NaN/Infinity in image settings validation (_config.py) - Fix
  TOCTOU race in shutdown cooldown with lock-based reservation (_system.py) - Use per-test tmp_path
  for env files in tests (isolation) - Strengthen error assertions (explicit status codes, non-empty
  error) - Remove unused fixture args, guard against empty plugin lists - Add NaN/Infinity rejection
  tests

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Harden history and plugin route validation
  ([`4b5e49a`](https://github.com/jtn0123/InkyPi/commit/4b5e49a6253598031fb09295e3d59d4987d68359))

- Harden input validation across 8 endpoints (JTN-134–142)
  ([`ddaf3eb`](https://github.com/jtn0123/InkyPi/commit/ddaf3eb5ed205913e4724022c374551ef4e80558))

Replace 500 internal errors with proper 400/422 validation responses for malformed client input, fix
  log injection, prevent exception text leaks, correct shutdown cooldown logic, and fix plugin
  cleanup type bug.

Closes JTN-134, JTN-136, JTN-137, JTN-138, JTN-139, JTN-140, JTN-141, JTN-142

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Testing

- Format validation coverage files
  ([`262eb91`](https://github.com/jtn0123/InkyPi/commit/262eb91622fff9d9e2a1976e998793fcaf846ec3))

- Remove duplicate plugin order coverage
  ([`9bcdce4`](https://github.com/jtn0123/InkyPi/commit/9bcdce44021ab16628ec8436b5d27203324c1ff7))


## v0.3.7 (2026-04-01)

### Bug Fixes

- Harden settings update and isolation routes
  ([`a5945bb`](https://github.com/jtn0123/InkyPi/commit/a5945bb1c8a566d836c8d691b316b22e9c7087a8))

### Testing

- Align settings update flow stubs with fallback args
  ([`59255c3`](https://github.com/jtn0123/InkyPi/commit/59255c35fdccc9c3a1773edb8a0bd08ecad0bbd0))

- Cover settings update helper paths
  ([`3d0d6d8`](https://github.com/jtn0123/InkyPi/commit/3d0d6d8e7e2fec7b24c5044bf23220de7339cd9d))


## v0.3.6 (2026-04-01)

### Code Style

- Use datetime.UTC alias per ruff UP017
  ([`3f1f19b`](https://github.com/jtn0123/InkyPi/commit/3f1f19b12abeb5d4a091eb93c8176e4cb00b125b))

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.3.5 (2026-04-01)

### Bug Fixes

- Address review feedback on exports and history
  ([`e9b1cce`](https://github.com/jtn0123/InkyPi/commit/e9b1ccecd619340bde9d6a244514e700be7b1728))

- Avoid history snapshot hotspot and cover collisions
  ([`15da29f`](https://github.com/jtn0123/InkyPi/commit/15da29f0aa869517ce69390102481e7ac9f24c9f))

- Harden exports, history snapshots, and plugin a11y
  ([`4dfda65`](https://github.com/jtn0123/InkyPi/commit/4dfda6550b95ba90ab2659112a0a03646f43e2d7))

- Resolve SonarCloud CSRF hotspot and backgroundOption fallback
  ([`767d097`](https://github.com/jtn0123/InkyPi/commit/767d097c2294b60ac87bbe15ac5905674a5dca80))

Split export route into separate GET/POST decorators to satisfy SonarCloud rule S3752 (mixed
  safe/unsafe HTTP methods). Add missing 'blur' fallback for backgroundOption in image_folder
  settings template to match sibling plugins and prevent null-reference errors.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Code Style

- Fix Black formatting on export route decorator
  ([`597f5a4`](https://github.com/jtn0123/InkyPi/commit/597f5a4270936ddf37883ff6d7c8ee85ee64f8f8))

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Refactoring

- Share image plugin background fill markup
  ([`c8e50d8`](https://github.com/jtn0123/InkyPi/commit/c8e50d8f48c20164787aeb16a55ce0d368d24a6f))


## v0.3.4 (2026-04-01)

### Bug Fixes

- Address sonar findings
  ([`cf63147`](https://github.com/jtn0123/InkyPi/commit/cf63147b88ad446d206fb7253cf157de61c6efd6))

### Chores

- Format sonar regression tests
  ([`72d4b33`](https://github.com/jtn0123/InkyPi/commit/72d4b33655d67c966475a7f407cbf92d39a5414c))


## v0.3.3 (2026-04-01)

### Bug Fixes

- Update test mocks to match new http_get and fetch_and_resize_remote_image APIs
  ([`dcd0906`](https://github.com/jtn0123/InkyPi/commit/dcd09061209926847110144203f5c1c94f1cf3e0))

- test_unsplash_search_success: mock fetch_and_resize_remote_image since grab_image now delegates to
  it instead of using the HTTP session directly - test_cache_ttl_respected: monkeypatch
  blueprints.settings.http_get instead of removed _requests.get alias

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Code Style

- Format updated tests for black
  ([`7f6e3bd`](https://github.com/jtn0123/InkyPi/commit/7f6e3bde77b852f87cb029be73c4f1f4a8f2505c))

- Sort settings imports for ruff
  ([`b84792f`](https://github.com/jtn0123/InkyPi/commit/b84792f575e57cb493844469c958a5386c7553f4))

### Testing

- Add coverage for fetch_and_resize_remote_image
  ([`a22d6b9`](https://github.com/jtn0123/InkyPi/commit/a22d6b96acc473e39ac127d56154939b521ff129))

Tests success path, HTTP failure, invalid image bytes, and raise_for_status error to satisfy
  SonarCloud ≥80% new code coverage gate.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.3.2 (2026-04-01)

### Bug Fixes

- Harden backend issue handling for JTN-109 JTN-111 JTN-112
  ([`57e717d`](https://github.com/jtn0123/InkyPi/commit/57e717dfd0f0a9c2382be3e6a8878a1cd4e7bb03))


## v0.3.1 (2026-04-01)

### Bug Fixes

- Apply Black formatting to test_js_api_contracts.py
  ([`952f79b`](https://github.com/jtn0123/InkyPi/commit/952f79bf4a87c2a2a26ba83cfae806f1e4af3f5d))

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Harden playlist UI edge cases
  ([`c6970dd`](https://github.com/jtn0123/InkyPi/commit/c6970dd43f05e48513a905d688a7c70e64762749))

### Refactoring

- Split refresh_task.py into package (JTN-73)
  ([`a073a70`](https://github.com/jtn0123/InkyPi/commit/a073a70a41e6f16707e6c86f67e73bff71c55ceb))

Convert src/refresh_task.py (1,075 lines) into src/refresh_task/ package:

- __init__.py: re-exports all public API for zero-breakage imports - task.py: RefreshTask class
  (main coordinator, ~850 lines) - worker.py: subprocess helpers (_get_mp_context,
  _restore_child_config, _remote_exception, _execute_refresh_attempt_worker, ~85 lines) -
  actions.py: RefreshAction, ManualRefresh, PlaylistRefresh, ManualUpdateRequest (~125 lines)

Updated 11 test files to patch correct submodule paths. Updated coverage_gate.py threshold key.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.3.0 (2026-04-01)

### Bug Fixes

- Address CodeRabbit review feedback
  ([`d5f564e`](https://github.com/jtn0123/InkyPi/commit/d5f564ed22b219f8d0026e13704773c014227ddc))

- Fix typo "022d" → "02d" in weather code lookup (weather_data.py) - Initialize display_driver
  before try block (refresh_task.py) - Use timezone-aware datetime in health window filter
  (_health.py) - Scope rate-limit buckets to app instance (inkypi.py) - Add bounds checking for AQI
  index lookup (weather_data.py) - Update test expectation for corrected weather code

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Ship linear bugfix batch
  ([`24b7d46`](https://github.com/jtn0123/InkyPi/commit/24b7d46ccf802b64887a44a384d5c0ffcf52f54b))

### Chores

- Format linear bugfix batch
  ([`8ddc5ad`](https://github.com/jtn0123/InkyPi/commit/8ddc5adebb334cfba50fa683227d87937bb09939))

### Code Style

- Fix black formatting in history.py
  ([`653cfcc`](https://github.com/jtn0123/InkyPi/commit/653cfcc098cfdb9c61e1967d2f570678948ca239))

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Fix black formatting in test_history.py
  ([`9fa27e3`](https://github.com/jtn0123/InkyPi/commit/9fa27e39194d769f9e75fbde4a7adbce5b84ced4))

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Features

- Add server-side pagination to history page (JTN-91)
  ([`0e6144e`](https://github.com/jtn0123/InkyPi/commit/0e6144ee9bb4797b5280c0c1ae44e92423b4f82a))

History page now paginates at 24 items per page instead of loading all items at once. Adds
  Previous/Next navigation and page indicator. Keeps lazy-loading on images for additional
  performance.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Refactoring

- Extract create_app() helpers to reduce complexity (JTN-113)
  ([`85a138f`](https://github.com/jtn0123/InkyPi/commit/85a138f780060a6160985dd1cfb165c467278ed5))

Extract 8 focused helper functions from the 337-line create_app() monolith to bring cognitive
  complexity well under the SonarCloud limit of 15. No behavior changes — pure structural
  extraction.

Extracted: _setup_secret_key, _register_blueprints, _register_health_endpoints,
  _setup_https_redirect, _setup_csrf_protection, _setup_rate_limiting, _setup_security_headers,
  _setup_signal_handlers.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Extract refresh_task helpers to reduce complexity (JTN-119)
  ([`ff357a4`](https://github.com/jtn0123/InkyPi/commit/ff357a4abb75b54bd619145ecb0262c494dfa9be))

Extract _push_to_display(), _save_benchmark(), _notify_watchdog(), and _complete_manual_request()
  from the 287-line _perform_refresh() and _run() methods to bring cognitive complexity under the
  SonarCloud limit of 15. No behavior changes.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Extract settings blueprint helpers to reduce complexity (JTN-115)
  ([`963ab5a`](https://github.com/jtn0123/InkyPi/commit/963ab5a1337eb4af3f54ee1c20e77814aeb3a069))

Extract focused helper functions from 5 settings blueprint functions that exceeded SonarCloud's
  cognitive complexity limit of 15. No behavior changes — pure structural extraction.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Extract weather_data helpers to reduce complexity (JTN-120)
  ([`5471ad2`](https://github.com/jtn0123/InkyPi/commit/5471ad2e5f9d86cfc138c81947344bb9b526e191))

Replace if-elif chains with lookup tables and extract per-datapoint builder functions from the 4
  weather_data.py functions that exceeded SonarCloud's cognitive complexity limit of 15. No behavior
  changes.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Testing

- Add pagination tests for history page
  ([`c1a87d1`](https://github.com/jtn0123/InkyPi/commit/c1a87d178c6b4c359867dd8f9a0af5a784a2b38f))

Covers multi-page navigation, invalid params, and edge cases to satisfy SonarCloud 80% coverage gate
  on new code.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.2.1 (2026-04-01)

### Bug Fixes

- Ui/ux polish batch from dogfood session
  ([`72074c8`](https://github.com/jtn0123/InkyPi/commit/72074c836c513a9b214f48ec47f23685912466c9))

- JTN-86: Plugin not found now uses styled 404 page instead of plain text - JTN-87: Add visible "to"
  label on playlist modal end-time combobox - JTN-88: Countdown date fields default to tomorrow
  instead of 0/0/0 - JTN-89: Plugin tabs scroll to target panel on desktop click - JTN-90: 404 page
  "Back to Home" uses prominent action-button style - JTN-92: Image Upload radio buttons wrapped in
  fieldset with legend

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Refactoring

- Extract helpers and constants from create_app()
  ([`8a3ab9d`](https://github.com/jtn0123/InkyPi/commit/8a3ab9d93db327b7021b6ab760e340744eb91768))

- Add _env_bool() helper to replace 7 repeated ("1","true","yes") checks - Extract
  _register_error_handlers() (38 lines) from create_app() - Add named constants: _CACHE_1_YEAR,
  _CACHE_1_DAY, _DEFAULT_MAX_UPLOAD - create_app() reduced from 382 to ~340 lines

JTN-74

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Replace bare except Exception in utils, plugins, and config
  ([`6b7c5b2`](https://github.com/jtn0123/InkyPi/commit/6b7c5b2ebb3bb349a0892c16f2fc97fece99d5e8))

Replace 26 bare `except Exception` blocks with specific exception types across 13 files (utils,
  plugins, config, model). Intentional catch-alls for logging safety, cleanup, and top-level
  fallbacks are preserved.

Key changes: - Flask context checks → RuntimeError - Env var parsing (float/int) → (ValueError,
  TypeError) - PIL image operations → (OSError, ValueError) - File I/O → OSError - Playwright import
  → ImportError - Cache-Control parsing → (ValueError, IndexError) - Schema validation →
  (AttributeError, TypeError, IndexError)

JTN-41

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Testing

- Add coverage for specific exception paths (JTN-41)
  ([`697a482`](https://github.com/jtn0123/InkyPi/commit/697a48231b305211019dd6ba174df328e722e7d6))

9 tests covering: RuntimeError on Flask context access, ValueError on env var parsing, malformed
  Cache-Control header, psutil failure fallback, invalid snooze datetime, playwright ImportError,
  AttributeError on file stream rewind.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Improve coverage for exception paths to satisfy SonarCloud
  ([`50b7e1e`](https://github.com/jtn0123/InkyPi/commit/50b7e1e9e5dcf6926a2c79caffffccd9ea98222a))

Cover chmod OSError, image loader wrapper, image upload cleanup, apod/weather/unsplash timeout
  parsing, and base_plugin timeout.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Increase coverage for specific exception paths (JTN-41)
  ([`ea0ffd2`](https://github.com/jtn0123/InkyPi/commit/ea0ffd2a55105160c8a11a493ebee040bf793f6f))

11 tests covering changed except blocks: RuntimeError on Flask context, ValueError on env var
  parsing, malformed Cache-Control, psutil failure, invalid snooze datetime, playwright ImportError,
  AttributeError on seek, unsplash timeout fallback, image upload deletion OSError.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.2.0 (2026-03-31)

### Features

- Make plugin API base URLs configurable via environment variables
  ([`7d3017b`](https://github.com/jtn0123/InkyPi/commit/7d3017b2d75d187440b6a33696293af87cdd08ca))

Add env var overrides for all hardcoded API base URLs across 7 plugin files. Defaults preserve
  current behavior. Enables pointing to self-hosted proxies, mock servers, or alternative endpoints.

Env vars added: - INKYPI_OPENWEATHER_API_URL (weather) - INKYPI_OPEN_METEO_API_URL (weather) -
  INKYPI_OPEN_METEO_AQI_API_URL (weather air quality) - INKYPI_UNSPLASH_API_URL (unsplash) -
  INKYPI_NASA_API_URL (apod) - INKYPI_WIKIPEDIA_API_URL (wpotd) - INKYPI_GITHUB_API_URL (github
  stars/contributions/sponsors)

JTN-40

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Refactoring

- Extract hourly value lookup helper in weather_data.py
  ([`eb7a81a`](https://github.com/jtn0123/InkyPi/commit/eb7a81afd6472f614bbe5aa61ffc9eb6fdb36901))

Replace 5 identical for-loop patterns (humidity, pressure, UV index, visibility, air quality) with a
  shared _get_current_hourly_value() helper. Net reduction of ~45 lines with no behavior change.

JTN-72

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Testing

- Add coverage for _get_current_hourly_value helper
  ([`9398b48`](https://github.com/jtn0123/InkyPi/commit/9398b481848fa0cb42d2550889a3c580da797a3b))

5 tests covering match, no-match, empty, invalid time string, and out-of-bounds index paths. Fixes
  SonarCloud coverage gate.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Add critical coverage for scheduling logic and refresh task
  ([`4055136`](https://github.com/jtn0123/InkyPi/commit/40551364c0d9cbfcbd9945cf84b50a06772ca3da))

Add 22 tests for Playlist.is_active() (normal range, midnight wraparound, edge cases) and
  PlaylistManager.determine_active_playlist() (priority sorting, multiple active playlists).

Add 14 tests for refresh_task.py: _remote_exception reconstruction, _get_mp_context,
  _execute_refresh_attempt_worker success/failure/error paths, RefreshTask.stop() cleanup, and
  _execute_with_policy error handling (empty queue, non-zero exit, error payload,
  timeout+terminate).

JTN-71

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.1.13 (2026-03-31)

### Bug Fixes

- Thread-safe ETA cache and bounded screenshot timeout
  ([`6a73e58`](https://github.com/jtn0123/InkyPi/commit/6a73e585fd98d8340efca16a855a31399a75c333))

Add threading.Lock to _eta_cache in playlist.py to prevent RuntimeError from concurrent dict
  mutation during Flask requests (JTN-69). Add default/max timeout ceiling for browser subprocess in
  take_screenshot() to prevent indefinite thread blocking (JTN-70).

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Code Style

- Black formatting for playlist.py
  ([`33b27a3`](https://github.com/jtn0123/InkyPi/commit/33b27a354f23d3d4f9ed5882df6032a48257be54))

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.1.12 (2026-03-31)

### Bug Fixes

- Correct exit code capture in lint.sh
  ([`bfc8c85`](https://github.com/jtn0123/InkyPi/commit/bfc8c85c26b283c345e7c678c17c966e387f4acd))

The previous `if ! cmd; then EXIT=$?` pattern always captured 0 because bash inverts the exit code
  for the if-condition. This meant ruff/black/mypy failures were silently passing in CI.

Switch to capturing exit code directly with `cmd; EXIT=$?`.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Make mypy non-blocking in lint.sh, centralize config in mypy.ini
  ([`e889ea2`](https://github.com/jtn0123/InkyPi/commit/e889ea222540226b259688a81db658216085c882))

Mypy was never actually enforced (due to the exit code bug). Making it suddenly blocking would fail
  CI with 149 pre-existing type errors. Keep it advisory until those are resolved in a follow-up.

Move ignore_missing_imports and follow_imports settings from pre-commit args into mypy.ini for
  consistency.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Resolve all ruff and black violations across codebase
  ([`36fc75e`](https://github.com/jtn0123/InkyPi/commit/36fc75ed389281f6ae517e0c80037205eecf6ced))

Fix 317+ pre-existing violations (previously hidden by lint.sh bug) and ~89 new violations from the
  B/SIM/C4/PERF rules:

- B904: add raise-from to 19 bare raises in except blocks - B023: bind loop variable in
  refresh_task.py closure - B006/B007/B009/B010: fix mutable defaults, unused loop vars -
  SIM102/SIM103/SIM108/SIM118: simplify conditionals and dict access - SIM115: use context managers
  for file operations - C4/PERF: use comprehensions instead of append loops - F401: remove unused
  imports in settings/__init__.py - E402: suppress intentional late imports in test files - E741:
  rename ambiguous variable names - Fix pre-existing test_parse_form_list_handling failure (missing
  __iter__ and getlist behavior on FakeForm)

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Chores

- Add .coveragerc and update CI coverage flags
  ([`5b9023d`](https://github.com/jtn0123/InkyPi/commit/5b9023dde2f94ba69d36d33e02990fb828819c44))

Centralize coverage configuration with branch coverage enabled, fail_under=70 global floor, and
  proper omit patterns for vendor code. Update CI pytest command to use .coveragerc instead of
  inline flags.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Enable B/SIM/C4/PERF ruff rules, fix pre-commit scoping
  ([`d0fdd8c`](https://github.com/jtn0123/InkyPi/commit/d0fdd8c104f4098da5277b394de580ce833ed23e))

Add flake8-bugbear, flake8-simplify, flake8-comprehensions, and perflint rules to catch real bugs
  (raise-without-from, mutable defaults, loop variable capture). Ignore noisy rules (B011, B017,
  SIM105, SIM117).

Expand pre-commit hooks to lint tests/ and scripts/ directories, matching CI behavior.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Continuous Integration

- Eliminate duplicate SonarCloud test run
  ([`870b590`](https://github.com/jtn0123/InkyPi/commit/870b59068c3bb64571f7887743a1af7a74e63ddf))

Delete standalone sonarcloud.yml that ran its own redundant pytest (~3 min wasted per CI run). Move
  SonarCloud scan into ci.yml as a job that downloads coverage artifacts from the existing test
  matrix.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.1.11 (2026-03-30)

### Bug Fixes

- Resolve SonarCloud bugs, vulns, and CSS issues
  ([`3dc249c`](https://github.com/jtn0123/InkyPi/commit/3dc249c5729ccd13d4b6b861b10587697bb6fbd9))

- Fix 2 log injection vulns in model.py (f-string → %r format) - Remove always-true ternary in
  refresh_task.py - Use make_response in Flask error handlers for explicit status codes - Add
  DOCTYPE, lang, charset, title to plugin render template - Add generic font-family fallback
  (sans-serif) to 8 plugin CSS files - Remove duplicate max-width and font-size in weather/ai_text
  CSS - Exclude third-party waveshare_epd/ from SonarCloud analysis

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.1.10 (2026-03-30)

### Bug Fixes

- Address CodeRabbit review findings
  ([`f86acd2`](https://github.com/jtn0123/InkyPi/commit/f86acd2cfc612503d91c1f8db9fcf8e3fc840082))

- Reset class-level DisplayManager state between prune tests - Remove unused tmp_path parameter from
  lowmem test - Add assertion for empty mask behavior in API keys test - Set explicit
  INKYPI_HEALTH_WINDOW_MIN in health tests - Fix docstrings to match actual test behavior (logs
  level tests) - Remove unused monkeypatch arg, fix test name (system tests) - Restore APP_VERSION
  in try/finally to prevent cross-test contamination

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Testing

- Expand unit test coverage for untested core modules (JTN-39)
  ([`2c89a8c`](https://github.com/jtn0123/InkyPi/commit/2c89a8cd5d654f334a74f8a49d72a488d5fd4395))

Add 87 new tests targeting error paths and edge cases in settings sub-modules, display manager, HTTP
  client, and image loader. Brings total test count from 1,707 to 1,794.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.1.9 (2026-03-29)

### Bug Fixes

- Dashboard Home icon and client-side form validation (JTN-46, JTN-47)
  ([`b5f5dbc`](https://github.com/jtn0123/InkyPi/commit/b5f5dbced9dc84faa46b76f73c37d99bfb33f80b))

JTN-46: Replace header-nav-spacer on dashboard with a Home icon link

matching other pages. Styled with muted opacity + pointer-events:none to indicate current page.

JTN-47: Add client-side validation to playlist and plugin modals: - Validate playlist name
  (required, max 64 chars) before fetch - Validate instance name (required) in Add to Playlist modal
  - Show inline error messages with aria-invalid + validation-message - Server-side validation
  remains as safety net

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.1.8 (2026-03-29)

### Bug Fixes

- Add graceful shutdown handler and fix Image.open file handle leaks (JTN-42)
  ([`57a0dce`](https://github.com/jtn0123/InkyPi/commit/57a0dce9a5500c027392f0afa2c418f064a0cc05))

- Register SIGTERM/SIGINT handler in create_app() for clean shutdown (stops refresh task, closes
  HTTP session, main process only) - Add explicit img.load() calls in image_loader file-based opens
  to release file handles immediately instead of relying on GC - Prevents file descriptor exhaustion
  on Pi Zero under memory pressure

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.1.7 (2026-03-29)

### Bug Fixes

- Add HTTPS redirect and playlist name validation (JTN-30, JTN-38)
  ([`41cd75c`](https://github.com/jtn0123/InkyPi/commit/41cd75c8873135c2f562efb3d4864ee25eeb1ee3))

JTN-30: Add opt-in HTTPS redirect via INKYPI_FORCE_HTTPS=1 env var. Redirects HTTP→HTTPS in
  production mode via before_request hook. Skipped in dev mode and when already behind HTTPS proxy.

JTN-38: Add format, length, and character constraints to playlist names. Max 64 chars, alphanumeric
  + spaces/hyphens/underscores only. Applied in create_playlist and delete_plugin_instance routes.

Adds 8 new tests (4 HTTPS redirect, 4 playlist validation).

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Refactoring

- Split weather plugin into API client and data modules (JTN-36)
  ([`cb58fb1`](https://github.com/jtn0123/InkyPi/commit/cb58fb1f9f67b3a2414d5de05e4ef1eeb8d3bba8))

Extract weather.py (887 lines) into 3 focused modules: - weather.py (277 lines): Weather class,
  settings schema, orchestration - weather_api.py (78 lines): HTTP client functions (5 API
  endpoints) - weather_data.py (622 lines): parsing, transformation, utility functions

Delegate methods on Weather class preserve backward compatibility for tests and external callers.
  Test mock paths updated for new API module.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.1.6 (2026-03-29)

### Bug Fixes

- Address SonarCloud high-value findings
  ([`e699aea`](https://github.com/jtn0123/InkyPi/commit/e699aeaddc462e796b338442aa63287043821f54))

- BLOCKER vuln: resolve path with realpath before send_file (plugin.py) - MAJOR vuln: use
  send_from_directory for plugin assets (path traversal) - MINOR vuln: sanitize user input before
  logging to prevent log injection - CRITICAL bug: fix duplicate HTML ids on radio buttons
  (image_album, image_folder) - MAJOR bug: remove redundant always-true condition
  (settings/__init__.py) - CRITICAL smell: use tz.localize() instead of tzinfo= for pytz
  (year_progress) - MINOR vuln: use %r formatting for user data in model.py logs

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.1.5 (2026-03-29)

### Bug Fixes

- Correct SonarCloud project key
  ([`f32258d`](https://github.com/jtn0123/InkyPi/commit/f32258d069c0a3057019ee29d61f82da73306d31))

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Chores

- Add SonarCloud integration for code quality analysis
  ([`9654195`](https://github.com/jtn0123/InkyPi/commit/9654195f79e7137a50f18e80a293f1c45c55b42d))

Add sonar-project.properties and GitHub Actions workflow for SonarCloud. Runs on PRs and pushes to
  main, generates coverage report, and feeds it to SonarCloud for code smell, bug, and vulnerability
  analysis.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Refactoring

- Split settings.py (1,434 lines) into focused sub-modules
  ([`2e2c121`](https://github.com/jtn0123/InkyPi/commit/2e2c12174b48186138b0b5c4f5449820d8864b36))

Convert blueprints/settings.py into a package with 7 files: - __init__.py (507 lines): state,
  constants, helpers - _updates.py (134 lines): update, status, version routes - _benchmarks.py (178
  lines): benchmark API routes - _health.py (98 lines): health + SSE streaming routes - _logs.py
  (126 lines): log download + API routes - _system.py (86 lines): shutdown + client logging routes -
  _config.py (374 lines): settings pages, save, import/export, API keys, isolation, safe reset,
  legacy aliases

All 27 route paths unchanged. All 1699 tests pass without modification.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.1.4 (2026-03-29)

### Bug Fixes

- Address CodeRabbit review findings
  ([`7dae7e6`](https://github.com/jtn0123/InkyPi/commit/7dae7e6ce429189b53adbca71838b753af7140ae))

- Replace lambda assignments with def (Ruff E731) in test_weather_errors - Add exception chaining
  (from e) in unsplash error handlers - Remove unused monkeypatch params in test_apod and
  test_weather

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Refactoring

- Extract shared dimension helper and migrate plugins to HTTP session
  ([`be45a6b`](https://github.com/jtn0123/InkyPi/commit/be45a6b2d0f972fb4a1b1b27f35ce8699c3dd5e7))

Add BasePlugin.get_oriented_dimensions() to replace the 3-line get_resolution + orientation check
  pattern duplicated across 20 plugins. Migrate 10 plugins from raw requests.get/post to the shared
  HTTP session (get_http_session) for connection pooling, retries, and consistent headers.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.1.3 (2026-03-29)

### Bug Fixes

- Security hardening and thread safety improvements
  ([`030d750`](https://github.com/jtn0123/InkyPi/commit/030d7508140290e932c38a523b9a2db0bbf8be53))

- Remove os.environ writes after API key save; plugins already reload via load_dotenv() so keys no
  longer leak in process memory (JTN-27) - Add threading.Lock around DisplayManager
  _history_count_estimate and _history_increment_count to prevent data races (JTN-29) - Set
  SESSION_COOKIE_HTTPONLY and SESSION_COOKIE_SAMESITE=Lax; change CSP default from report-only to
  enforcing in production (JTN-31) - Add threading.Lock around _LAST_HOT_RELOAD in plugin registry
  to prevent race between concurrent plugin loads and pop (JTN-33)

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.1.2 (2026-03-29)

### Bug Fixes

- Add styled 404 page and stop leaking UUIDs in error toasts
  ([`f84c93a`](https://github.com/jtn0123/InkyPi/commit/f84c93aa51782977754f5abf228f00d7ae8f6680))

- Create 404.html template with app layout, nav, and "Back to Home" link instead of plain "Not
  found" text (JTN-43) - Change includeRequestId default to false in handleJsonResponse() so
  internal request UUIDs are no longer shown in user-facing error toasts (JTN-44) - Add 404 error
  handler to test fixture and integration tests - JTN-45 (toast z-index) canceled as false positive
  — toast z-index (10000) already higher than modal (1000)

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.1.1 (2026-03-29)

### Bug Fixes

- Sanitize target_version, fix mutable defaults, guard JSON.parse
  ([`c47b91c`](https://github.com/jtn0123/InkyPi/commit/c47b91c9e7e1ba812d420896fd346a4010c81a2c))

- Validate target_version against semver regex before passing to subprocess in update route (JTN-26)
  - Fix mutable default argument image_settings=[] in 4 display classes by using None with runtime
  guard (JTN-28) - Wrap localStorage JSON.parse in try-catch to prevent page crash on corrupted data
  (JTN-32) - Add tests for injection rejection, valid semver acceptance, and mutable default
  isolation

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.1.0 (2026-03-28)

### Bug Fixes

- Add missing csrf.js and client_errors.js, fix preflash refs
  ([`f3777eb`](https://github.com/jtn0123/InkyPi/commit/f3777eb2df92798134345687cc09c764e3c72bcc))

- Track csrf.js (CSRF token auto-injection) and client_errors.js (uncaught error reporting) —
  base.html references both but they were gitignored, causing 404s in browser smoke tests - Add
  allowlist entries to .gitignore for the new scripts - Remove duplicate test_config_validation.py
  entries in preflash coverage suite

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Add support for inky impressions 7.3 2025 edition
  ([#102](https://github.com/jtn0123/InkyPi/pull/102),
  [`fca2fa9`](https://github.com/jtn0123/InkyPi/commit/fca2fa92a2754b05db877bcde8481b85ecac88b3))

Adds support for new spectra 6 e-ink displays from Inky Impressions

- Add type hint for font variable in weather mock script
  ([`e21d343`](https://github.com/jtn0123/InkyPi/commit/e21d343e50c10b63aa145ad059b78a456f1d4dfe))

- Introduced a type hint for the `font` variable in the render_weather_mock.py script, specifying it
  as a Union of ImageFont.FreeTypeFont and ImageFont.ImageFont. This enhancement improves code
  clarity and assists with type checking.

- Address CodeRabbit critical findings
  ([`5749e81`](https://github.com/jtn0123/InkyPi/commit/5749e81ac8eefa28082379961ad047f407d118dc))

- Use /var/lib/inkypi instead of /tmp for version state (symlink attack) - Run checked-out tag's
  update.sh, not the launcher's copy - Add threading lock to _set_update_state and start_update for
  atomicity - Pass empty dict to plugin cleanup (instance already deleted)

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Audit pass — security, reliability, accessibility, and dark mode polish
  ([`06d6b75`](https://github.com/jtn0123/InkyPi/commit/06d6b75de3d3d8ad69ed1c43878c41667dc798c8))

- Path traversal: replace startswith() with commonpath() in plugin image route - Symlink DoS: add
  followlinks=False to image_folder os.walk() - RSS: check feedparser bozo flag on malformed feeds -
  Refresh task: preserve traceback in worker error results - Dark mode: replace hardcoded rgba
  overlays with CSS variable fallbacks - A11y: move inline onerror to JS, add aria-label on playlist
  cycle input

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Avoid backslash in playlist debug f-string
  ([`2c45d20`](https://github.com/jtn0123/InkyPi/commit/2c45d205837bde7a760d6d920d11d85fba2be89b))

- Ci failures — update preflash refs, mock systemd in test, fix refresh test
  ([`0c30ee6`](https://github.com/jtn0123/InkyPi/commit/0c30ee6f874688bfc2ddb20c477f347c8d6b4b76))

- Update preflash_validate.sh references to consolidated test files - Mock _systemd_available in
  test_update_status_running to prevent auto-clear from systemctl in CI - Replace
  test_playlist_refresh_uses_execute (tested nonexistent code path) with
  test_perform_refresh_calls_execute_with_policy

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Code review findings — rate limiter leak, XSS, cache-busting, breadcrumb macro, version API
  ([`0713f38`](https://github.com/jtn0123/InkyPi/commit/0713f384ce2fa665aec9996a37ae8fa593e6ccb3))

- Fix rate limiter memory leak: prune empty IP entries after expiring timestamps - Fix epdconfig
  digital_read bug: read GPIO device values instead of pin numbers - Fix XSS in RSS plugin: sanitize
  HTML tags and remove |safe from Jinja2 template - Add static asset cache-busting via versioned
  url_for context processor - Stop leaking endpoint URLs in user-facing error toasts - Add exc_info
  to plugin cleanup warning logs for debuggability - Add breadcrumb navigation macro and wire into
  all page templates - Add /api/version endpoint with GitHub release checking and semver comparison
  - Add update script target_tag support and auto-clear stale update state - Persist SECRET_KEY in
  production (not just dev) for stable sessions - Consolidate scattered test files into canonical
  modules - Replace black with ruff-format, add pre-commit hooks and conventional commits - Replace
  time.sleep with mock time in cache tests to eliminate flakiness - Fix macOS case-insensitive path
  comparison in plugin registry test

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Code review findings — rate limiter, XSS, cache-busting, breadcrumb, version API
  ([#85](https://github.com/jtn0123/InkyPi/pull/85),
  [`433e7dd`](https://github.com/jtn0123/InkyPi/commit/433e7ddd304f0650c0981e4544f976edd72581a5))

fix: code review findings — rate limiter, XSS, cache-busting, breadcrumb, version API

- Comprehensive quality sweep — memory leaks, security, a11y, error handling, tests, and DRY
  templates
  ([`0d629b0`](https://github.com/jtn0123/InkyPi/commit/0d629b091951366ea9110a2ca995d431ffb376c1))

Memory Leak Sweep: - Guard fetch wrapping to prevent stacking on repeated submissions - Close
  EventSource on page navigation (dashboard) - Disconnect MutationObserver on modal close/page
  unload - Clear skeleton loader timers before re-creating and on element removal - Clear settings
  update interval on page navigation - Register atexit handler to close HTTP session pool - Use
  context manager for Image.open in refresh_task

Security Hardening: - Replace innerHTML with DOM APIs (createElement/textContent) in
  operation_status - Add 30s rate limiting on shutdown/reboot endpoint - Add JSON input validation
  on settings and history POST endpoints - Implement session-based CSRF protection with
  auto-injected fetch wrapper

Error Handling Cleanup: - Surface file upload errors to users via showResponseModal - Add
  logger.warning for silent except clauses (config, http_utils) - Log os.chmod failures instead of
  silently passing - Log env var parse failures in _env_float/_env_int/_env_bool - Standardize error
  responses to json_error() across blueprints

Accessibility: - Add aria-labelledby to response modal - Add skip-to-main-content link in base.html
  - Update aria-valuenow dynamically on progress bars - Use semantic h3 headings for playlist titles

Template DRY-up: - Extract API key card Jinja2 macro (48 lines → 4 calls) - Convert inline styles to
  CSS custom properties - Clean up icons macro with proper aria attributes

Test Quality: - Add 16 tests for ProgressEventBus (pub/sub, threading, SSE format) - Add 6 tests for
  handle_request_files (upload, rejection, EXIF, PDF) - Tighten 33 weak assertions to exact expected
  status codes - Add 3 tests for /display-next rate limiting - Add 20 tests for cron parsing edge
  cases

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Correct playlist rendering logic for improved user experience
  ([`e8416bb`](https://github.com/jtn0123/InkyPi/commit/e8416bbbea24e57f5be6264cc5d0669670c16898))

- Adjusted the rendering logic in the playlist template to ensure accurate display of plugin
  information. - Enhanced the conditions for displaying the next plugin, improving clarity when the
  time until the next plugin is zero or negative. - This change aims to provide users with a more
  intuitive and responsive interface when interacting with playlists.

- Dark mode text colors, header icon sizing, and hardcoded white values
  ([`28f9ad1`](https://github.com/jtn0123/InkyPi/commit/28f9ad1bc2148be59a3621717767848a64e81cf6))

- Add `color: var(--text)` to body so all pages inherit correct text color in dark mode - Add
  `.header-button.icon` sizing rules so home/clock/theme icons render uniformly - Remove hardcoded
  width/height from theme toggle SVGs (now sized via CSS) - Add generic `.icon-image svg` and
  `.app-icon svg` fill rules for consistent icon rendering - Replace hardcoded `white` with
  `var(--on-accent)` in navigation, feedback, and modal styles - Replace `background-color: white`
  with `var(--surface)` on toggle knob

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Full app polish audit — memory leaks, race conditions, UX, and robustness
  ([`d047710`](https://github.com/jtn0123/InkyPi/commit/d047710bdd7570dd4ce906da97b09896c67ffc11))

- Fix rate limiter memory leak by pruning empty IP deque keys - Reject manual update requests when
  queue is full instead of silent eviction - Add try/except for scheduled time parsing to prevent
  refresh loop crash - Reset plugin failure_count on success so plugins can recover from unhealthy -
  Force periodic history count recount to prevent estimate drift - Add threading lock around display
  image hash check to prevent race condition - Persist playlist state in display-next direct path to
  prevent index loss - Add 10s cooldown on /display-next to protect e-ink hardware - Validate plugin
  IDs in save_plugin_order against registered plugins - Cap ETA cache size to prevent unbounded
  memory growth - Log exceptions in is_show_eligible instead of silently swallowing - Change
  response modal close button from span to semantic button element - Add console.warn in
  localStorage catch blocks for debuggability - Show key length in API key masking for visual
  differentiation - Remove -q flag from pytest.ini to restore summary line output

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Plugin icon serving with dynamic path resolution
  ([#286](https://github.com/jtn0123/InkyPi/pull/286),
  [`697fb6e`](https://github.com/jtn0123/InkyPi/commit/697fb6e56be0923ddebdd1e450ffaa04199dc3ba))

Fix 404 errors for plugin icons by resolving paths dynamically in request handlers.

Changes: - Remove module-level PLUGINS_DIR variable that was resolved at import time - Resolve
  plugin paths dynamically in the image route handler - Add security checks to prevent directory
  traversal - Convert to absolute paths for send_from_directory - Add proper error handling with
  logging

This fixes broken plugin icons regardless of the working directory when InkyPi starts.

- Polish sweep — untrack stale files, fix typos, dead code, status codes, and UI inconsistencies
  ([`1b0f27b`](https://github.com/jtn0123/InkyPi/commit/1b0f27b5be442571b0d68a71f95379909b3594b5))

Remove tracked artifacts (true/, benchmarks.db, PHASE2_SUMMARY.md), define --transition-speed CSS
  variable, rename drew_clock_center → draw_clock_center, move imports to top-level, remove
  weather_icon_preview stub, fix 500→404 for missing plugin instances, remove duplicate HTML id,
  consolidate _to_minutes with validation, and make expand/collapse labels data-driven.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Remove orphaned makin_things submodule entry
  ([`d195258`](https://github.com/jtn0123/InkyPi/commit/d195258fb05f6fd4e3368a971f7a0ddc14f597a6))

The submodule was tracked in the git index but had no corresponding entry in .gitmodules, causing CI
  checkout cleanup to fail with "no submodule mapping found" errors.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Remove unused import from weather mock script
  ([`5d43955`](https://github.com/jtn0123/InkyPi/commit/5d439551434785e95fef4f3317ead949aba396cf))

- Removed the import statement for FreeTypeFont from the render_weather_mock.py script, as it was
  not being utilized in the code. This cleanup helps improve code readability and maintainability.

- Security hardening, bug fixes, and resource leak prevention
  ([`78fe07c`](https://github.com/jtn0123/InkyPi/commit/78fe07c982e8a8c51129333008f2e81512d03c85))

Address XSS vulnerabilities (icon titles, operation status, inline handlers), path traversal in
  history image route, and unrestricted settings import/export. Fix config write race condition,
  .env quote escaping, checkbox always-checked bug, newspaper orientation logic, datetime
  deprecation, ImageColor fallback, playlist type coercion, and SQLite connection leaks. Add blob
  URL cleanup, fetch monkey-patch restoration, and dashboard connectivity warning.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Stabilize CI Python version
  ([`691b32f`](https://github.com/jtn0123/InkyPi/commit/691b32f8be38c98313fd84f64bba9206455a6f19))

- Standardize API key error messages, add logging, and surface plugin errors in /update_now
  ([`51ff1de`](https://github.com/jtn0123/InkyPi/commit/51ff1de17adf1c90d6b7063b23edad55852f51a2))

- Add logger.error() before every missing-key raise across all plugins - Standardize error messages
  (e.g. "OPEN AI" → "OpenAI", "Open Weather Map" → "OpenWeatherMap") - Prevent weather's except
  Exception from swallowing RuntimeError key errors - Surface plugin RuntimeErrors as 400 responses
  in /update_now instead of generic 500 - Add missing-key tests for GitHub contributions and
  sponsors plugins - Update all affected test assertions to match new error codes and messages

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Track all CSS source partials, ignore built main.css
  ([`7fe9fb7`](https://github.com/jtn0123/InkyPi/commit/7fe9fb759ed7d462ca83315cfe1478262a05729c))

The .gitignore was ignoring the entire styles/ directory, which meant 9 of 14 CSS source partials
  were missing from the repo while the build artifact (main.css) was tracked. Now all partials are
  tracked as source and main.css is properly gitignored as a build output.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Unescape html named symbols ([#318](https://github.com/jtn0123/InkyPi/pull/318),
  [`194a8e2`](https://github.com/jtn0123/InkyPi/commit/194a8e23b9e28e68faa53f5d45fbb9c6de8fa6ec))

- Update ETA test to reflect current logic for time display
  ([`1cd73ee`](https://github.com/jtn0123/InkyPi/commit/1cd73eeb20e442704cf97b6e717cd76aa039fa05))

- Adjusted the test for ETA rendering to account for the first item being at "now", which is not
  captured by the regex. - Ensured that the subsequent expected times are still validated, improving
  the accuracy of the integration tests for playlist snapshots.

- Update gitleaks action token
  ([`4d87d92`](https://github.com/jtn0123/InkyPi/commit/4d87d928207304df1b8d9aaca12f3d6a0b68a6e0))

- Update logging configuration and adjust logger name in plugin registry
  ([`8118c58`](https://github.com/jtn0123/InkyPi/commit/8118c58677a89dbf90f9582aed04889d5e4ef15d))

- Update next plugin display logic in playlist template
  ([`b14f190`](https://github.com/jtn0123/InkyPi/commit/b14f1904629a2c2b008cafabce95c44d31cef05f))

- Adjusted the logic for displaying the next plugin information in the playlist HTML template. -
  Changed the condition to clear the next plugin text when the time until the next plugin is less
  than or equal to zero, ensuring a cleaner UI experience. - This update enhances user feedback
  regarding upcoming plugins and improves overall template functionality.

- Update pi config.txt path ([#542](https://github.com/jtn0123/InkyPi/pull/542),
  [`44ea8b5`](https://github.com/jtn0123/InkyPi/commit/44ea8b51a5a94501d40a35a7163c754e2b0edd63))

- Use b64 instead of url for gpt-image-1 ([#311](https://github.com/jtn0123/InkyPi/pull/311),
  [`87361ab`](https://github.com/jtn0123/InkyPi/commit/87361ab8b8d90ec6001ebd9bddb6341516955e68))

Co-authored-by: teyang_lau <teyang_lau@singaporeair.com.sg>

- **ai_image): default to 'dall-e-3' and support base64 for gpt-image-1\nfix(plugin**: Resolve
  plugin image paths dynamically with traversal checks (align with upstream)
  ([`dfbba8e`](https://github.com/jtn0123/InkyPi/commit/dfbba8efb8177ff090c5b8758cc721899c0fb1f3))

- **plugin_form**: Update metrics handling to use object format for steps; enhance error logging for
  better debugging during plugin form submission
  ([`fe41ddd`](https://github.com/jtn0123/InkyPi/commit/fe41ddde1e6174b9c89103c9f43ea711fdd7eff2))

### Chores

- Add code quality hooks
  ([`155e220`](https://github.com/jtn0123/InkyPi/commit/155e2204519aed1df5b24771261676509f671db1))

- Harden install script
  ([`8176ff2`](https://github.com/jtn0123/InkyPi/commit/8176ff2f8ac456b9899114e071793f1d99edc976))

- Remove unused imports
  ([`f3bba2c`](https://github.com/jtn0123/InkyPi/commit/f3bba2c6f7e8fed54526d5574e5f1dd7f5caa957))

- Remove unused imports
  ([`132b010`](https://github.com/jtn0123/InkyPi/commit/132b010d33405084df04212d784683b631251b97))

- Skip time freeze tests without freezegun
  ([`3c6e690`](https://github.com/jtn0123/InkyPi/commit/3c6e690e242a73816016d169c67dd6506edf9e1b))

- Sort history imports
  ([`a0ae0c8`](https://github.com/jtn0123/InkyPi/commit/a0ae0c81773ddf35fedcef01591a6f526aac6c3d))

- Update development requirements and enhance playlist template accessibility
  ([`1395db5`](https://github.com/jtn0123/InkyPi/commit/1395db5440774bdf0564a9dd4a1cf108b6eee33f))

- Added Playwright to the development requirements for improved testing capabilities. - Updated the
  playlist HTML template to include a main element for better semantic structure and accessibility.
  - Enhanced the end time select element with an aria-label for improved screen reader support. -
  Made CSS adjustments to ensure uniform rendering of inline SVG icons within the plugin icon
  container.

- **ci**: Enforce pip check in smoke job
  ([`905d07e`](https://github.com/jtn0123/InkyPi/commit/905d07ea85a1aa2775168221ecb389650bd23b4b))

- **dev**: Add Ruff and Black configs, scripts, and docs; wire into dev requirements
  ([`ae31b0f`](https://github.com/jtn0123/InkyPi/commit/ae31b0f12b6b970f4bbacb3ddad39d88fab00e60))

- **install**: Add hypothesis==6.122.3 to requirements-dev.txt for enhanced testing capabilities
  ([`e5ca785`](https://github.com/jtn0123/InkyPi/commit/e5ca7857435c37269c57ee1d16019e5e16eefd26))

- **install**: Bump inky to 2.2.1 (match upstream commit 33ef680)
  ([`0db50be`](https://github.com/jtn0123/InkyPi/commit/0db50be88cc509965c323c401510f504ecbe47f9))

### Code Style

- Update UI elements for improved theming and consistency
  ([`4a7d20d`](https://github.com/jtn0123/InkyPi/commit/4a7d20d594b57fae8028ea024e2cdeeb02ea4253))

- Changed text color in settings and history templates to use CSS variables for better theme
  support. - Updated background colors for buttons and form elements in main.css to enhance visual
  consistency across the application. - Introduced subtle notes in settings for improved user
  guidance. - Ensured all color changes align with the new theming strategy for a cohesive user
  experience.

### Documentation

- Add PR guardrails and contributing workflow
  ([`a2ebef0`](https://github.com/jtn0123/InkyPi/commit/a2ebef0502c5a83d463c2dcd5020bb91cad906aa))

- Add structured polishing plan with phases, tasks, and validation criteria
  ([`440b0da`](https://github.com/jtn0123/InkyPi/commit/440b0da9bc21d064790a84c8a8af78b799ccb9d2))

- Remove outdated polishing plan document, consolidating improvement strategies and validation
  criteria
  ([`966342a`](https://github.com/jtn0123/InkyPi/commit/966342aea511a5929e016dfe409c692728250e63))

- Update future improvements document with completed features and their implementation details,
  including dark mode, request timing, backup & restore, benchmarking, developer workflow, and light
  monitoring. Remove obsolete planning documents for plugin fixes.
  ([`42ea7c9`](https://github.com/jtn0123/InkyPi/commit/42ea7c94629a9a7cc6c9d0f3e1edb546d8c6e806))

### Features

- Add .editorconfig ([#374](https://github.com/jtn0123/InkyPi/pull/374),
  [`527f012`](https://github.com/jtn0123/InkyPi/commit/527f012b05f35020523a3d0da87a76d085e7df20))

- Add client logging endpoint and enhance weather settings
  ([`16930a2`](https://github.com/jtn0123/InkyPi/commit/16930a212de79361cc217c3ce6cb3101bc5a9289))

- Implemented a new endpoint for accepting client logs, allowing for better visibility of front-end
  flows without impacting user experience. - Updated the weather settings to include saved settings
  for location and display options, improving user customization. - Enhanced JavaScript in the
  weather settings to handle approximate location fallback and log client actions, ensuring better
  error tracking and user feedback. - Refactored image handling in the weather plugin to utilize
  data URIs for local assets, improving resource loading reliability.

- Add cycle interval support to playlists and enhance UI interactions
  ([`eeddc6a`](https://github.com/jtn0123/InkyPi/commit/eeddc6a00003b9c7cb81693e28990fe2e069ba43))

- Introduced `cycle_interval_seconds` attribute in the Playlist class to allow per-playlist cycle
  interval configuration. - Updated the `to_dict` and `from_dict` methods to handle the new cycle
  interval attribute. - Enhanced the RefreshTask to utilize the playlist-specific cycle interval
  when determining refresh timings. - Modified the playlist update functionality to accept an
  optional cycle interval override. - Updated the playlist HTML template to include cycle interval
  input and display next eligible plugin information. - Removed the snooze feature and adjusted
  related UI elements accordingly. - Enhanced integration tests to validate the new cycle interval
  functionality and ensure proper handling of playlist updates.

- Add device cycle update functionality and associated UI enhancements
  ([`9fc2477`](https://github.com/jtn0123/InkyPi/commit/9fc24770f7fa30a6cfc8298b19663db61d84bce6))

- Implemented a new endpoint to update the device refresh cadence, allowing users to specify the
  interval in minutes. - Added a modal for editing the device cycle, including validation for input
  values to ensure they are within the acceptable range. - Enhanced the playlist template and
  JavaScript to support the new device cycle functionality, including event listeners for modal
  interactions. - Updated CSS styles to accommodate the new modal and improve the overall user
  experience with device cadence settings.

- Add GitHub Sponsors and Repository Stars view ([#377](https://github.com/jtn0123/InkyPi/pull/377),
  [`2e34fe6`](https://github.com/jtn0123/InkyPi/commit/2e34fe632941a7507a7f65095c46f6120d7eca42))

* feat: add GitHub Sponsors and Repository Stars view

* add dropdown for contributions, sponsors and stars

- Add Google AI provider support and API pricing display
  ([`73aa4a2`](https://github.com/jtn0123/InkyPi/commit/73aa4a21f3b58999ca394bb32c8c56c8b1fe4476))

Add Google Imagen 4 and Gemini 3.x as provider options for AI Image and AI Text plugins alongside
  OpenAI. Remove deprecated models (DALL·E 2/3, GPT-4o/4.1). Show approximate API pricing inline in
  model dropdowns with info callouts.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Add logging for CSS handling
  ([`18ec4ea`](https://github.com/jtn0123/InkyPi/commit/18ec4ea9c245baa4c5b1d49ba8cca9f4ea34335f))

- Add next plugin preview functionality and update UI
  ([`b8d8050`](https://github.com/jtn0123/InkyPi/commit/b8d805078de20dad02e4c95ebf4d9c3a05275260))

- Implemented `peek_next_plugin` method in the Playlist class to return the next plugin instance
  without altering the current index. - Enhanced the main route to compute and display a
  non-mutating preview of the upcoming plugin for server-side rendering. - Added a new `/next-up`
  endpoint to provide structured JSON data for the next plugin instance. - Updated the inky.html
  template to conditionally display the next plugin information. - Introduced integration tests to
  verify the functionality of the new next-up feature and ensure proper rendering in the main page.

- Add option to invert images ([#118](https://github.com/jtn0123/InkyPi/pull/118),
  [`08566a7`](https://github.com/jtn0123/InkyPi/commit/08566a74ffbba378395b38abd3d793e8554f532e))

- Add rotation ETA calculation for plugins in playlists
  ([`2f5cc60`](https://github.com/jtn0123/InkyPi/commit/2f5cc6003f6137d61c7337869a7d0377efd23585))

- Introduced a new `rotation_eta` dictionary to compute and store estimated time of arrival for each
  plugin in the playlist. - Enhanced the `playlists` function to calculate the time until the next
  cycle for each plugin, improving user feedback on upcoming plugin displays. - Updated the playlist
  HTML template to show the next execution time for each plugin, enhancing the user interface and
  experience. - Made adjustments to the device configuration JSON to reflect changes in refresh
  times and plugin settings for better functionality.

- Add submodule for weather icons
  ([`8f608c9`](https://github.com/jtn0123/InkyPi/commit/8f608c9a87891734af5daed51405b0838144bfdc))

- Introduced a new submodule for weather icons from the basmilius repository, enhancing the
  project's iconography resources. - Updated .gitmodules to include the path and URL for the new
  submodule, ensuring proper integration and version control.

- Bundle JS and CSS instead of using CDN ([#373](https://github.com/jtn0123/InkyPi/pull/373),
  [`d51925e`](https://github.com/jtn0123/InkyPi/commit/d51925eefaed8c5b60066a7aeaebdaa4fdab71b9))

* feat: bundle JS and CSS instead of using CDN

* add missing cs and js + call from install and update

* fix missing file download

* correct filename for jquery

* adjust to feedback after review

- Comic enhancements ([#298](https://github.com/jtn0123/InkyPi/pull/298),
  [`cef9110`](https://github.com/jtn0123/InkyPi/commit/cef9110e792feb7a074fd4cf02f8e536cbb4a3bb))

* Feat/comic enhancements (#1)

Multiple comic plugin enhancements:

- Features: - Added "webcomic name" feed. - Upscale image for small comic panels (looking at you,
  xkcd!) or big screens. - Optional comic title and caption when present. - Possibility to select
  title/caption font size. - Refactor: - Feed parser in a separate module. - Feed parsing is linked
  with the comic list, no way to forget adding parsing logic when adding a new feed. - Image
  composition in a separate method as logic became more complex.

* Fix default checkbox state

* Fix: add questionable content panel title

* Fix: comic panel vertical alignment

- Comprehensive testing additions and UI/UX CSS polish
  ([`bad7eb2`](https://github.com/jtn0123/InkyPi/commit/bad7eb2aba700fdfad58b21cb5ea0c92f1680fe7))

Add 54 new tests covering plugin error scenarios, property-based API fuzzing, dark mode CSS
  verification, template snapshots, concurrent requests, error recovery, and Playwright E2E form
  workflows. Fix disabled button/input styles, print stylesheet hardcoded colors, plugin hover
  overlay variable, header touch target sizing, and dashboard empty state consistency.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Enable local development mode without hardware
  ([#285](https://github.com/jtn0123/InkyPi/pull/285),
  [`f7fe839`](https://github.com/jtn0123/InkyPi/commit/f7fe8398509d51ccb9dac699134c0270b2f94a55))

* feat: Enable local development mode without hardware

Add development mode that allows running InkyPi without Raspberry Pi or e-ink display hardware.

Changes: - Add MockDisplay class that saves images to files instead of hardware - Add --dev flag to
  run on port 8080 with dev config - Make display imports conditional with fallback to mock -
  Improve path resolution to work from any directory - Add device_dev.json config for development

This enables contributors to develop and test InkyPi on any platform (Mac/Linux/Windows) without
  needing physical hardware.

* docs: Add development quick start guide and enhance dev mode IP logging

- Introduced a new `development.md` file outlining the quick start guide for developing InkyPi
  without hardware. - Updated `inkypi.py` to log the local IP address only when in development mode,
  improving clarity and functionality. - Enhanced the development experience by detailing setup,
  essential commands, and tips for testing changes.

* feat: Enhance MockDisplay with initialization logging

- Added logging functionality to the MockDisplay class for better visibility during development. -
  Introduced an `initialize_display` method that logs the dimensions of the mock display upon
  initialization.

- Enhance device configuration and UI responsiveness
  ([`2e78e7f`](https://github.com/jtn0123/InkyPi/commit/2e78e7f8fbe99fee01e24f9d71ed6089e2a1be16))

- Added new plugin settings for "wpotd" in device_dev.json to support additional functionality. -
  Updated refresh metrics in device_dev.json to reflect current processing times. - Improved header
  layout in CSS using flexbox for better alignment and spacing of elements. - Adjusted theme toggle
  button styling in multiple templates for consistent design and responsiveness. - Introduced a
  plugin icon mapping in playlist.html to streamline icon rendering for various plugins.

- Enhance history and plugin UI with metadata and status updates
  ([`8b812fe`](https://github.com/jtn0123/InkyPi/commit/8b812fe9f85bbc07f102855da7235005a2fc6bae))

- Added history metadata support in the RefreshTask to display source information for images. -
  Implemented sidecar metadata loading in the history blueprint to enrich image details. - Updated
  plugin page to show the last refresh time for instances, improving user awareness of status. -
  Introduced a status bar in the plugin template to display current display and instance
  information. - Enhanced CSS for the status bar to improve layout and visual consistency across the
  application. - Added integration tests to verify the rendering of history sidecar metadata and
  status bar presence.

- Enhance HTML templates with improved accessibility and structure
  ([`93b2a39`](https://github.com/jtn0123/InkyPi/commit/93b2a392bcb349d626399a719b9a7c87892aaad6))

- Added <main> elements to the plugin, response modal, and settings templates for better semantic
  HTML structure. - Updated input fields across templates to include 'aria-label' attributes,
  enhancing accessibility for assistive technologies. - These changes aim to improve user experience
  and ensure better compatibility with screen readers and other accessibility tools.

- Enhance playlist UI with new button interactions and modal functionality
  ([`b8f600d`](https://github.com/jtn0123/InkyPi/commit/b8f600dc837943eb0cc6e9eb85c5b825e2fef750))

- Added event listeners for new playlist creation, editing, running next in the playlist, and
  deleting playlists and instances, improving user interaction. - Refactored the HTML structure to
  utilize data attributes for dynamic button actions, streamlining the JavaScript event handling. -
  Removed inline script for drag-and-drop functionality, centralizing all related logic in the
  external JavaScript file for better maintainability. - Improved overall user experience by
  providing clear modal confirmations for delete actions and enhancing the accessibility of playlist
  controls.

- Enhance plugin instance handling and UI updates
  ([`9c7c6ff`](https://github.com/jtn0123/InkyPi/commit/9c7c6ffd49c77f5da52b942c4dbe180d56919b6a))

- Added error handling for displaying images in RefreshTask to support backward compatibility with
  tests lacking history metadata. - Improved logging for plugin page rendering, including instance
  and playlist resolution. - Implemented fallback mechanisms for instance images, allowing for
  history-based retrieval if the current image is missing. - Updated templates to display current
  plugin, instance, and playlist information dynamically. - Enhanced integration tests to verify the
  rendering of the "Now showing" block and instance image fallback functionality.

- Enhance settings and history templates with semantic structure
  ([`872024a`](https://github.com/jtn0123/InkyPi/commit/872024a20e91a2188624f90eda4e08758a9ee46c))

- Added <main> elements to the history and settings templates for improved semantic HTML structure
  and accessibility. - Updated input fields in the clock settings to include 'id' attributes,
  enhancing form element identification and accessibility. - These changes aim to improve the
  overall user experience and ensure better compatibility with assistive technologies.

- Enhance UI with delete confirmation modals and device frame overlays
  ([`95644e8`](https://github.com/jtn0123/InkyPi/commit/95644e8605679adefe2c68d12c89ca39172d2c98))

- Introduced delete confirmation modals for both playlists and plugin instances, improving user
  experience by providing clear actions before deletion. - Added functionality to toggle device
  frame overlays in thumbnails, enhancing visual presentation and user interaction. - Updated
  JavaScript to handle key reordering of playlist items, allowing for better accessibility and
  usability. - Enhanced CSS styles for various elements, including snackbar notifications for undo
  actions, improving overall UI consistency and feedback.

- Enhance weather mock data generation and improve CSS layout
  ([`6a7b469`](https://github.com/jtn0123/InkyPi/commit/6a7b46952f8c3bac7ce38acdb01d8e8dbe4dfe1d))

- Updated the weather mock data generation to reflect a more realistic diurnal temperature curve and
  precipitation patterns. - Adjusted CSS for the NY layout to improve positioning and visual
  consistency. - Modified HTML to streamline the refresh time display logic, ensuring it only
  renders when applicable. - Enhanced chart rendering with a new temperature gradient for better
  visual representation of data.

- Enhance weather plugin with icon pack selection and preview functionality
  ([`d198dd9`](https://github.com/jtn0123/InkyPi/commit/d198dd992533712adff5f1eef2a12db50b00bd80))

- Added support for selecting different weather and moon icon packs in the weather plugin settings,
  improving customization options for users. - Implemented a new endpoint for previewing selected
  icon packs without refetching data, enhancing user experience and interactivity. - Updated HTML
  and JavaScript to facilitate icon pack selection and preview, ensuring seamless integration with
  existing settings. - Enhanced CSS for better layout and visual consistency across different icon
  pack variants.

- Enhance weather plugin with NY layout iteration and A/B testing support
  ([`0715592`](https://github.com/jtn0123/InkyPi/commit/07155925f21a0513658542ab5b2a4c5d7cd24fa9))

- Introduced a detailed iteration plan for the NY layout of the weather plugin, aligning with
  ESP32-style hierarchy and newspaper density. - Added functionality for A/B testing variants in the
  weather rendering script, allowing users to generate and compare different visual styles. -
  Updated HTML and CSS for the NY layout to improve accessibility, visual prominence, and overall
  user experience. - Enhanced chart rendering with new features such as min/max labels and a "now"
  line for better data visualization. - Included validation criteria and testing instructions for
  quick iterations and mock rendering.

- Image preview polish — lightbox a11y, skeleton fades, hover feedback, click-to-close
  ([`ba3c7cd`](https://github.com/jtn0123/InkyPi/commit/ba3c7cded26a6e68f9deef62b582036d49175559))

- Fix plugin compact preview: remove native mode class, guard dblclick toggle - Smooth
  skeleton-to-image fade transition across dashboard, plugin, history pages - Lightbox: upgrade
  close span to button, add focus trap, persistent Esc handler, loading spinner, error state, click
  image to close, SVG close icon - Hover feedback on dashboard preview, history thumbnails, status
  card images - History thumbnails: cursor zoom-in, hover lift + border accent - Dashboard: remove
  duplicate CSS rule, add hover border/shadow on preview - Consistent lightbox-preview-image class
  for dynamic and pre-existing modals

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Implement A/B comparison functionality for weather plugin
  ([`9ba109f`](https://github.com/jtn0123/InkyPi/commit/9ba109f4c22cae0e2d08c6b2da4ec9a6e5e19aff))

- Added a new endpoint for A/B image comparison, allowing users to generate and compare two images
  with optional extra CSS. - Enhanced the display manager to support saving images without
  processing, facilitating easier previews for A/B testing. - Updated weather plugin settings to
  include a layout style option, enabling users to select different styles and corresponding CSS. -
  Introduced a modal in the weather settings for A/B comparison, improving user interaction and
  customization capabilities. - Adjusted HTML templates to accommodate new features and ensure a
  seamless user experience.

- Implement browser geolocation support for device location settings
  ([`dc917a5`](https://github.com/jtn0123/InkyPi/commit/dc917a524ad8ceb6221f0a1097b2568789922342))

- Added functionality to capture and save the user's device location from the browser, enhancing
  user experience by auto-populating location fields. - Introduced a button in the weather settings
  UI to allow users to use their browser's current location. - Updated the settings form to include
  an option for users to enable or disable the use of browser geolocation on save. - Enhanced the
  JavaScript to handle geolocation requests and populate latitude and longitude fields accordingly.
  - Made adjustments to the settings.py to store device location if provided, ensuring compatibility
  with existing configurations.

- Implement eligibility-aware plugin selection and UI enhancements
  ([`0e4566b`](https://github.com/jtn0123/InkyPi/commit/0e4566b4084f1dd9ed691c5f29338653a12350fb))

- Added `get_next_eligible_plugin` and `peek_next_eligible_plugin` methods in the Playlist class to
  select plugins based on eligibility criteria. - Updated the RefreshTask to utilize the new
  eligibility-aware selection for determining the next plugin. - Enhanced the main route and
  templates to support displaying eligible plugins, including a new button for immediate display. -
  Implemented drag-and-drop functionality for reordering plugins in the playlist, with corresponding
  API endpoints for reordering, snoozing, and toggling display settings. - Added integration tests
  to validate the new plugin selection, reordering, and display functionalities.

- Implement request ID handling and enhance success response structure
  ([`c230c1f`](https://github.com/jtn0123/InkyPi/commit/c230c1f0f82e6cd99801d193ab1f5d8e5ad79f2d))

- Added a request ID mechanism to track requests across the application, improving traceability in
  responses. - Updated the JSON response structure to include a request ID for successful
  operations, enhancing client-side error handling and user feedback. - Introduced a new ETA
  endpoint in the playlist blueprint to compute and return estimated times for plugins, including
  request ID in the response. - Refactored existing endpoints to utilize the new success response
  format, ensuring consistency across the API. - Enhanced integration tests to validate the new
  request ID functionality and ensure proper response handling.

- Improve labels for Add to playlist refresh ([#363](https://github.com/jtn0123/InkyPi/pull/363),
  [`e69b37d`](https://github.com/jtn0123/InkyPi/commit/e69b37df4094379255891b5f2a3141eaecb157e2))

testing

add js for both radios

improvements

- Remove only-fresh functionality and enhance playlist time validation
  ([`621f0e0`](https://github.com/jtn0123/InkyPi/commit/621f0e0312f7c70546b0e97c9c0740c52e3afee7))

- Removed the `toggle_only_fresh` endpoint and associated UI elements as per product decision. -
  Updated the `create_playlist` and `update_playlist` functions to include validation for
  overlapping time windows, ensuring playlists do not conflict in their scheduled times. - Adjusted
  the `save_plugin_settings` function to clarify that saved settings do not schedule recurrence,
  prompting users to use the "Add to Playlist" feature for automation. - Enhanced integration tests
  to reflect the removal of the only-fresh feature and validate the new time overlap checks.

- Systemd hardening, CSS build improvements, API key UX, and comprehensive test additions
  ([`cb064bc`](https://github.com/jtn0123/InkyPi/commit/cb064bc766d95c7ca3f1fd90c06888dae5b85f1f))

- Systemd: add Type=notify, WatchdogSec, raise memory limits - Install/update: validate CSS build
  output, configure journal size limit - CSS build: use _imports.css manifest instead of main.css as
  source - API keys: show which plugins use each key in the UI - Display manager: track image hash
  to skip redundant refreshes - Refresh task: improve error handling and logging - Frontend: plugin
  page and dashboard JS/CSS polish - Tests: add coverage for plugins (comic, countdown, github,
  image_album, rss, todo_list, year_progress), blueprints (apikeys, main), display manager, image
  loader/utils, install scripts, time utils, epdconfig - Conftest: short-circuit Playwright
  detection when SKIP flags are set

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Ui polish pass — focus states, error persistence, async UX, and accessibility
  ([`a53b7b7`](https://github.com/jtn0123/InkyPi/commit/a53b7b7e5ac8bec73ea7bef7a9da34fadd5327ba))

- Error toasts/modals no longer auto-close so users can read details - Global :focus-visible
  outlines on all interactive elements - Normalized transition durations via --transition-speed CSS
  variable - Buttons disabled during async saves (API keys, settings, plugins) - Confirmation
  dialogs before destructive API key deletions - Password visibility toggle on API key inputs - High
  contrast mode fixes for skeletons, shadows, disabled states - Touch target sizing for
  toggle/delete buttons on mobile - aria-live regions on dynamic content (preview fallback, response
  modal) - Form validation summary with error count on submit - Placeholder text replaced with
  persistent field notes (playlist) - Added --border-radius-pill token

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- **ai_image**: Enhance progress tracking by recording key steps during image generation process.
  Updated error handling for missing thumbnails in APOD plugin to provide clearer guidance. Added
  tests to verify progress steps and ensure key stages are recorded correctly.
  ([`bdfd509`](https://github.com/jtn0123/InkyPi/commit/bdfd5093e37f81f336269fa2090b72a080c32722))

- **caching**: Implement static asset caching in inkypi.py for improved performance; enhance button
  grid and icon button styles in main.css for consistency and better touch targets; add
  comprehensive unit tests for metadata handling and icon path resolution in base_plugin and
  weather_plugin tests.
  ([`dee9676`](https://github.com/jtn0123/InkyPi/commit/dee967620d9f091f64c9cad27c9ff9d70b1a1fca))

- **lightbox**: Integrate shared Lightbox functionality for image previews across templates.
  Refactor image preview handling to utilize Lightbox API, enhancing user experience with consistent
  behavior. Update CSS for improved layout and responsiveness.
  ([`26af442`](https://github.com/jtn0123/InkyPi/commit/26af4421fd0a88010aa806376be641dc1702cb80))

- **logging**: Implement in-memory log capture for development mode; add DevModeLogHandler to
  capture logs and display them in the settings interface; update log retrieval methods to show
  development logs when journal is unavailable; enhance settings template with collapsible sections
  for better organization.
  ([`0d578ff`](https://github.com/jtn0123/InkyPi/commit/0d578ff30a7a3b60d3116b6eaa1de5a7fd438e49))

- **plugin**: Add API key presence check and latest image retrieval for plugins; enhance plugin page
  with refresh time display and corresponding tests
  ([`d59daaa`](https://github.com/jtn0123/InkyPi/commit/d59daaaa0e8a03a105cd37a58765bd79d69fb2d0))

- **plugin**: Implement plugin management routes and functionality, including settings saving,
  instance updates, and image serving. Enhance venv.sh to support python3 as a fallback for pip
  installations, ensuring compatibility across environments.
  ([`49866e7`](https://github.com/jtn0123/InkyPi/commit/49866e76c2d2850d07f6e366e574055da0f6e509))

- **plugin_form**: Add onAfterSuccess callback to sendForm for enhanced image refresh after
  successful submission
  ([`f44fe18`](https://github.com/jtn0123/InkyPi/commit/f44fe1825aa83fc2e8254a097154c6ee2575140f))

### Performance Improvements

- Frontend loading — minify CSS bundle and defer modal script
  ([`fc503d0`](https://github.com/jtn0123/InkyPi/commit/fc503d0adb24d12db35c32601fc10f49ac888537))

- Add defer attribute to response_modal.js in base.html to unblock HTML parsing (theme.js remains
  sync to prevent flash of wrong theme) - Add build_css.py --minify step to install.sh and update.sh
  so production deployments serve a 84KB bundle instead of 117KB (28% smaller)

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Lazy plugin module loading — defer imports until first use
  ([`0f49825`](https://github.com/jtn0123/InkyPi/commit/0f498254777b9d8bd18c405f76f16512cc19c35a))

Plugin modules are no longer imported at startup. load_plugins() now validates directories and
  stores configs, deferring importlib.import_module() to the first get_plugin_instance() call. This
  reduces startup memory and time on Pi Zero 2W by only loading plugins when they're actually needed
  for rendering.

Adds get_registered_plugin_ids() helper for checking registration without triggering imports.
  Updates tests to use the new API.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Reduce SD card wear with PNG compression and write guards
  ([`e9df46d`](https://github.com/jtn0123/InkyPi/commit/e9df46d9ec8c88dedadd72bf1511c0343d1ab51e))

- Add optimize=True to all image.save() calls in DisplayManager, reducing PNG file sizes from ~5MB
  to ~600KB per refresh cycle - Skip config file writes when serialized content is unchanged,
  avoiding unnecessary SD card I/O on every refresh - Track history entry count in memory to skip
  directory scans when clearly below the pruning threshold

On a Pi Zero 2W these changes reduce write volume from ~17MB/hour to ~3MB/hour at default refresh
  intervals.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

### Refactoring

- Clean up playlist template by removing device frame toggle
  ([`4929c98`](https://github.com/jtn0123/InkyPi/commit/4929c988ddbec2f186150164793fd37e66b3e9ef))

- Removed the device frame toggle button from the playlist template to streamline the user
  interface. - This change enhances clarity and focuses on the primary actions available to users,
  improving overall usability.

- Compute moon phases locally
  ([`b22098a`](https://github.com/jtn0123/InkyPi/commit/b22098a866122d891808449482992afb2ded0132))

- Deduplicate lightbox handlers, centralize modal-open state, fix pointer-events
  ([`34164b7`](https://github.com/jtn0123/InkyPi/commit/34164b7b7ea3355253f6c95bec76852e509eba18))

- Extract bindImageLoadHandlers() and addFocusTrap() helpers to eliminate copy-paste between
  ensureModal branches - Use CSS class (.lightbox-img-visible) instead of inline opacity so hidden
  images also get pointer-events: none - Centralize syncModalOpenState() in InkyPiUI, delegate from
  lightbox, playlist, and plugin_page scripts - Reuse .lightboxable utility class for thumbnail
  cursor - Remove redundant aria-label on img (alt is sufficient) - Move lightbox transition rule
  from _feedback.css to _layout.css

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Enhance playlist.js initialization and improve integration test coverage
  ([`442e2bd`](https://github.com/jtn0123/InkyPi/commit/442e2bd5fe3d762d546f3289b4cb110d8905ce68))

- Refactored the initialization of playlist.js to ensure it runs correctly regardless of DOM
  readiness. - Updated integration tests to remove skipped markers and improve request validation
  for playlist interactions. - Added a new marker for integration tests in pytest.ini to categorize
  tests requiring browser automation.

- Extract plugin image fallbacks
  ([`558d9eb`](https://github.com/jtn0123/InkyPi/commit/558d9eb55a50520a33550bc0c452467fc62b95e7))

- Isolate HTTP sessions per thread
  ([`2360f14`](https://github.com/jtn0123/InkyPi/commit/2360f144d62d0b8196053e7374ca8d0930d78945))

- Modernize time utils annotations
  ([`f52e963`](https://github.com/jtn0123/InkyPi/commit/f52e963c2067d7842616777c56a83f0a51590d76))

- Optimize preview refresh
  ([`530da1e`](https://github.com/jtn0123/InkyPi/commit/530da1ef27d1f2789cf2820f435de6bfa340b7f3))

- Remove icons loader script and update templates for inline icons
  ([`25cdcc1`](https://github.com/jtn0123/InkyPi/commit/25cdcc1003775012c52699a08b64c03cbf6ca458))

- Removed the `icons_loader.js` script as icons are now fully integrated via templates/macros. -
  Updated multiple HTML templates to eliminate references to the Phosphor icons stylesheet,
  enhancing load performance. - Introduced a lightweight skeleton loader in CSS for image
  placeholders, improving user experience during image loading. - Adjusted button styles in the main
  CSS for better visual consistency and interaction feedback.

- Simplify time display logic in playlist template
  ([`50297ea`](https://github.com/jtn0123/InkyPi/commit/50297ea8e73006e9d980673007c00b3ce9817c11))

- Removed the device vs local time toggle functionality to streamline the user interface. - Updated
  the JavaScript to continuously render device time based on the device's timezone offset. - Cleaned
  up the HTML structure by eliminating the toggle button, enhancing clarity and usability. - This
  change improves the user experience by providing a consistent time display without unnecessary
  toggling options.

- Update device_dev.json for improved performance metrics; enhance header layout and styling in CSS;
  restructure inky.html for better icon alignment and responsiveness
  ([`ab3f450`](https://github.com/jtn0123/InkyPi/commit/ab3f4502d1f8e0b6567a14ecd2532e3151662d24))

- Updated refresh metrics in device_dev.json to reflect new request and processing times. - Modified
  CSS for the header to use flexbox for better alignment and spacing of icons. - Restructured
  inky.html to group navigation icons and theme toggle button, improving layout and accessibility. -
  Adjusted button styles for a more cohesive design across the application.

- **logs): streamline journalctl command construction in logs.sh for improved readability and
  maintainability. Enhance venv.sh to ensure proper exit behavior when sourced or executed.
  feat(http_utils**: Add optional caching support in http_get function with configurable TTL,
  improving performance for repeated requests. Update unit tests to reset cache state before tests
  for consistency.
  ([`0ca475d`](https://github.com/jtn0123/InkyPi/commit/0ca475d6d962cc8c4b8f75e1aa764614fc331c7c))

- **plugin**: Streamline error handling in plugin_page function to return a more user-friendly 404
  response. Update Weather plugin to replace deprecated path_to_data_uri method with to_file_url for
  improved file handling. Enhance form submission logic in plugin_form.js to include fallback
  mechanism for legacy support. Add additional assertions in integration tests for plugin routes to
  verify error messages.
  ([`951f576`](https://github.com/jtn0123/InkyPi/commit/951f576f455ea6e62fc50c211f8a88b2c5942cf2))

- **plugin**: Update import paths in base_plugin.py to remove 'src' prefix for improved module
  accessibility and consistency across the codebase.
  ([`84424f1`](https://github.com/jtn0123/InkyPi/commit/84424f11a2d9c361049619e5c92a20298718753e))

- **scripts**: Update PYTHONPATH handling in dev and web scripts to use absolute paths, improving
  environment setup consistency. Remove redundant PYTHONPATH export in dev and web scripts.
  ([`717fbec`](https://github.com/jtn0123/InkyPi/commit/717fbeccb8af458b5f8694855c75dc97242e4e1d))

- **tests**: Update import paths in test_enhanced_progress_integration.py to remove 'src' prefix for
  improved module accessibility and consistency with recent changes in the codebase.
  ([`36f5cfd`](https://github.com/jtn0123/InkyPi/commit/36f5cfdec721f985667a5555014b0aff6213c2e2))

- **venv**: Introduce setup_pythonpath function to streamline PYTHONPATH configuration in venv.sh,
  ensuring consistent environment setup. Add unit tests to validate PYTHONPATH handling and plugin
  imports.
  ([`a3499d8`](https://github.com/jtn0123/InkyPi/commit/a3499d883df426a481411ff2c672525318fe91c5))

### Testing

- Add 108 tests for polish audit fixes, model edge cases, image utils, and routes
  ([`491eb6d`](https://github.com/jtn0123/InkyPi/commit/491eb6de1cf09d243cb9522bfa57e0bf8ccfdf18))

- test_polish_audit_fixes: validates all 15 audit fixes (rate limiter cleanup, queue overflow,
  malformed time, health recovery, hash lock, cooldown, etc.) - test_model_edge_cases: 37 tests for
  playlist overnight wrap, reorder, eligibility, snooze, scheduled refresh, round-trip serialization
  - test_image_and_display: 28 tests for orientation, resize, enhancement, hashing, image loading,
  history pruning, duplicate detection - test_blueprint_coverage: 25 tests for /display-next
  cooldown, plugin order validation, /next-up, /preview, /api/current_image, /healthz, /readyz, rate
  limiter pruning, API key masking, response modal semantics

Coverage: 85% overall (+1%), display_manager 91% (+8%), model 88% (+5%)

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

- Add e2e browser tests and integration helpers
  ([`798388b`](https://github.com/jtn0123/InkyPi/commit/798388b1baf8ee8c7d2a0fa3415ced983d633f4f))

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Add integration tests for display-next
  ([`b5b104e`](https://github.com/jtn0123/InkyPi/commit/b5b104ead62cb7694dc16fdd562e06e4e552b552))

- Cover current_dt helper
  ([`bff02b4`](https://github.com/jtn0123/InkyPi/commit/bff02b4906bb29784da35de1140fdd8bd3ac934b))

- Cover json_internal_error
  ([`b00422c`](https://github.com/jtn0123/InkyPi/commit/b00422c895b5f4d29d66a508bb53b7f03f41ca36))

- Ensure CSP header enforced when report-only disabled
  ([`c104f75`](https://github.com/jtn0123/InkyPi/commit/c104f752b86e5df2dc6499909ff3a7d3ca0cfae9))

- Ensure main is optional
  ([`0d1264c`](https://github.com/jtn0123/InkyPi/commit/0d1264cca1b52580fa8b10f9ccc7780df03d96f6))

- Ensure newspaper plugin initializes
  ([`7108787`](https://github.com/jtn0123/InkyPi/commit/7108787c61a3868aca2d6a3fdd1c0cb9ab0580eb))

- **plugin**: Add integration test to ensure failing plugin does not block successful plugin
  execution
  ([`2f7ef62`](https://github.com/jtn0123/InkyPi/commit/2f7ef62c6e436328e98c6fd29590d3af2006bfbc))
