# CHANGELOG


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
