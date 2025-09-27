# Playlist & Weather Fix Plan

## Goals
- Restore the Add to Playlist modal flow so the UI issues a POST to `/playlist/add_plugin` when saving, keeping the integration test green and aligning with expected backend behavior.
- Ensure weather forecast icons resolve to PNG/SVG asset URLs rather than inline base64 data URIs, honoring the PNG/SVG preference and fixing unit expectations in tests.

## Current Findings
- Playwright UI test `tests/integration/test_plugin_add_to_playlist_ui.py::test_plugin_add_to_playlist_flow` fails because no POST requests hit `/add_plugin`. Modal flow now uses `fetch` within `PluginForm.sendForm`, but needs to actually submit when invoked from Playwright’s minimal DOM.
- Weather unit test `tests/unit/test_weather_plugin.py::test_parse_forecast_basic` fails since `parse_forecast` returns a base64 `data:` URI; unit expects a path ending with `01d.png`.

## Tasks
1. Playlist Modal Submission
   - Confirm that `handleAction('add_to_playlist')` serializes modal form data and calls `fetch` with the correct endpoint.
   - Investigate whether `PluginForm.sendForm` is executed in Playwright test context (no bundled JS modules). Consider direct POST fallback for non-JS contexts or minimal DOM—maybe the modal Save button lacks `type="submit"` semantics.
   - Implement a small adapter so clicking the Save button dispatches the same POST path even when `PluginForm` isn’t wired, e.g., fallback `form` submit handler or ensure stubbed `fetch` sees `/playlist/add_plugin`.
   - Update comments/tests accordingly; add inline JS doc if necessary.

2. Weather Icon Paths
   - Modify `parse_forecast` (and other helpers if needed) to return file URLs (or relative paths) instead of base64 data URIs when the icon asset exists on disk, preferring PNG/SVG.
   - Ensure moon icons follow the same pattern.
   - Adjust templates to accept URLs (they already work with data URIs, so no template change likely needed).
   - Update unit tests if expectations change (e.g., `endswith('.png')` remains valid).

3. QA & Tests
   - Run `pytest tests/unit/test_weather_plugin.py` to confirm icon path changes.
   - Run targeted integration test `pytest tests/integration/test_plugin_add_to_playlist_ui.py` (requires Playwright deps).
   - If heavier Playwright run is expensive, explain any skips and suggest manual verification.

## Open Questions
- None beyond ensuring fetch fallback aligns with UI requirements.
