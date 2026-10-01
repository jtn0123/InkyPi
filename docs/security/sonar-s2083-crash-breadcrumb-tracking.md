# Tracking: SonarCloud S2083 on `utils/crash_breadcrumb.py`

Created: 2026-08-20. Updated: 2026-10-01.

## Finding

- Rule: `pythonsecurity:S2083` — "Change this code to not construct the path from user-controlled data."
- Severity: Blocker. The current main quality gate fails; recent PR quality gates passed.
- Location: `src/utils/crash_breadcrumb.py`, the former `write_text` call inside `_write_json`
- First reported: PR [#632](https://github.com/jtn0123/InkyPi/pull/632)

## Observed boundaries

The breadcrumb's directories come from `INKYPI_RUNTIME_DIR`,
`INKYPI_LOCKFILE_DIR`, and `INKYPI_STATE_DIR`. These are launcher configuration;
request handlers do not set them. Overrides must be absolute and are resolved.
The two final filenames are module constants, and `_in_dir()` refuses a final
path that resolves outside its configured directory.

The September 30 open S2083 flow also follows parsed JSON read from the
breadcrumb through the history payload into the write helper. Parsed fields
are file **contents**; they do not select directories or filenames. A regression
loads crafted `path` and `filename` fields and confirms the only persistent
file created is the fixed `last_death.json`.

The earlier assessment focused on launcher-controlled environment variables.
The current reproduction extends that assessment by checking the temporary
write target and the persisted values read back into logs.

## Confirmed defects and repair

The previous writer used predictable `breadcrumb.json.tmp` and
`last_death.json.tmp` paths. The final-path containment check did not cover those
temporary paths. A local actor able to write in a configured directory could
plant a temporary-file symlink, causing the service to overwrite an outside
file. Both cases were reproduced against disposable directories; HTTP control
of those directories has not been established.

The writer now uses `tempfile.mkstemp` to exclusively allocate an unpredictable
0600 temporary file in the destination directory. JSON is written through the
returned descriptor, flushed and synced before atomic replacement. Failed
serialization, synchronization and replacement retain the previous record and
remove the temporary file. A stream-open failure also closes the still-owned
descriptor. Pre-planted predictable symlinks are never opened.

The open S5145 log-injection flow was also reproducible: the raw `operation`
and `started_at` fields were interpolated into a log message. The complete log
representation is now JSON-escaped with ASCII escapes, sanitized and bounded to
2000 characters. CR/LF, NUL, tabs and Unicode line separators cannot create log
lines. Returned and persisted forensic fields retain their original values;
crash quarantine still applies its separate identifier validation.

Temporary-file and write failures remain best-effort. Directories must be
protected by the operator; these changes do not make launcher environment overrides an OS
privilege boundary or establish physical-Pi crash/soak results.

## Verification and closure

Focused regressions cover both temporary symlink destinations, single-line log
output with preserved forensic data, payload/path separation, previous-record
retention and temporary cleanup. Existing lifecycle/quarantine tests continue
to exercise ordinary recovery and unwritable paths.

Fresh Sonar analysis must confirm the S2083 and S5145 findings are closed and
the quality gate passes. Local regression results alone do not prove scanner
closure. No gate changes, suppressions, exclusions or issue waivers are part of
this repair.
