# CHANGELOG


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
