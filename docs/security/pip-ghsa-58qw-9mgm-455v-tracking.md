# Tracking: unpatched pip advisory GHSA-58qw-9mgm-455v

Created: 2026-04-26

## Advisory

- Package: `pip`
- Advisory: `GHSA-58qw-9mgm-455v`
- CVE: `CVE-2026-3219`
- Severity: Medium
- Upstream advisory: https://github.com/advisories/GHSA-58qw-9mgm-455v
- Fix / upstream PR: https://github.com/pypa/pip/pull/13870 (merged upstream; no patched `pip` release is listed by the advisory data yet)
- Current upstream status: no patched version is listed by the advisory data as of 2026-04-26; affected versions include `pip` through `26.0.1`.

## InkyPi Tracking Scope

Affected manifests to keep tracking separately from broad dependency cleanup:

- `uv.lock`
- `install/requirements-dev.in`
- `install/requirements-dev.txt`

Local manifest check on 2026-04-26 found `pip==26.0.1` in `install/requirements-dev.txt`. Live Dependabot inspection also reports `uv.lock` as affected for this advisory, so keep the runtime lock and dev requirements source/generated pair in scope even if local lockfile contents need a follow-up verification pass.

## Closure Criteria

Close this tracking item only when all of the following are true:

- GitHub advisory data lists a patched `pip` version for `GHSA-58qw-9mgm-455v` / `CVE-2026-3219`.
- InkyPi updates all affected manifests to a non-vulnerable `pip` version.
- Dependabot no longer reports the advisory for `uv.lock` or `install/requirements-dev.txt`.
- Dev requirements changes are handled through the `install/requirements-dev.in` workflow and regenerated with `pip-compile --generate-hashes`.
- Runtime lock changes are handled through the uv runtime dependency workflow with `uv lock` and `bash scripts/check_requirements_drift.sh`.

Re-check monthly until closed.

## GitHub Issue Attempt

Preferred tracking was a GitHub issue, but `gh issue create` was blocked because the `jtn0123/InkyPi` repository has issues disabled.
