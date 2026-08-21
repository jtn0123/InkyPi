# Tracking: SonarCloud S2083 on `utils/crash_breadcrumb.py`

Created: 2026-08-20

## Finding

- Rule: `pythonsecurity:S2083` — "Change this code to not construct the path from user-controlled data."
- Severity: Blocker (drives `new_security_rating` to **E**, failing the PR quality gate)
- Location: `src/utils/crash_breadcrumb.py`, the `write_text` call inside `_write_json`
- First reported: PR [#632](https://github.com/jtn0123/InkyPi/pull/632)

## Why It Fires

Sonar's taint analysis treats `os.getenv()` as an attacker-controlled source and
`Path.write_text()` as a file-write sink. The breadcrumb's directories come from
`INKYPI_RUNTIME_DIR` / `INKYPI_LOCKFILE_DIR` / `INKYPI_STATE_DIR`, so there is a
source-to-sink path and the rule reports it.

## Assessment: false positive, but the code was hardened anyway

**Not a privilege boundary.** These variables are set by the systemd unit that
launches the service. Anyone able to change them can already execute code as the
service user, so redirecting a breadcrumb write gains an attacker nothing they
did not already have. This is configuration, not untrusted input.

The environment override exists so tests and dev runs can redirect state to a
temp directory — the same contract `install/update.sh` and
`blueprints/settings/_update_status.py` already honour. Those modules read the
same variables and are not flagged, because they have no write sink.

Hardening applied in #632 regardless, because one part of the finding pointed at
a real (if minor) bug:

- The directory must now be **absolute**, and is resolved. A relative value used
  to scatter breadcrumbs relative to the service's working directory instead of
  where the next boot reads them — a genuine correctness bug, not just a
  security one.
- `_in_dir()` refuses a filename that resolves outside its directory, so these
  helpers cannot become an arbitrary-write primitive if a future caller passes
  something that is not a module constant.
- Values read back out of the breadcrumb are sanitised before they reach logs or
  `disabled_reason` (this closed the three companion `S5145` findings).

Sonar's engine does not model any of that as a sanitizer. It recognises
allow-list comparison against literals, which is not usable here: the tests that
exercise crash recovery need arbitrary `tmp_path` directories.

## Deliberately Not Done

- **No `# NOSONAR`.** Suppressing the marker in code hides the finding from
  future readers and from any genuinely unsafe path added later.
- **No laundering the value** through string/`Path` round-trips to break taint
  propagation. That would clear the gate only by confusing the analyser, and
  would silence the rule for real issues in this file afterwards.

## Resolution Required

Mark the issue **Safe** (or *Won't Fix*) in the SonarCloud UI, referencing this
document. This needs a maintainer with project permissions; it is a review
decision rather than a code change, which is why it is not automated.

Until then `SonarCloud Scan`, `SonarCloud Code Analysis`, and the aggregate
`CI gate` stay red on any PR touching this file. Note `main`'s Sonar gate is
independently red on `new_reliability_rating`.

## Closure Criteria

Close this tracking item when either:

- The issue is marked Safe in SonarCloud and `new_security_rating` returns to A; or
- The environment override is removed from the breadcrumb write path entirely
  (for example, resolved once at startup in `config.py` and injected), which
  would remove the source-to-sink flow rather than mask it.

## GitHub Issue Attempt

Preferred tracking was a GitHub issue, but the `jtn0123/InkyPi` repository has
issues disabled — same constraint recorded in
[the pip advisory tracking doc](./pip-ghsa-58qw-9mgm-455v-tracking.md).
