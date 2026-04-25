# Mutmut survivor suppressions

This file records mutmut-triage outcomes across three categories: surviving
mutants we have chosen **not** to kill (with a one-line justification),
mutants that were killed by the same PR as this file (cross-referenced to the
assertion that catches them), and acceptable / deferred survivors. See the
headings below for the specific sections.

See `docs/mutation_testing.md` for the mutation-testing setup, CI schedule,
and triage workflow. The source tracking issue is **JTN-595**.

## Status of the nightly artifact (JTN-595, 2026-04-19 through 2026-04-25)

The `mutation-nightly` job in `.github/workflows/ci.yml` has **never produced
a usable `mutmut-cache` artifact** since the JTN-508 `paths_to_mutate`
expansion. Every scheduled run since that expansion terminates with
`The operation was canceled` at the 120-minute timeout — i.e. the full
mutmut pass does not fit inside the job budget.

Additionally, even if a run finished in time, `actions/upload-artifact@v4`
was configured without `include-hidden-files: true`, so the hidden
`.mutmut-cache` directory would have been silently excluded from the
artifact. That bug is fixed in the same PR that landed this file — see
`.github/workflows/ci.yml`.

**Consequences for this triage pass:**

- There is no real survivor list to load from an artifact.
- We did not run the full mutmut pass locally — `docs/mutation_testing.md`
  and the JTN-595 issue explicitly forbid that, since it takes hours.
- The entries below were identified by **static inspection** of small
  files in the expanded scope (`src/utils/`, `src/blueprints/`), targeting
  patterns that a surface-level mutmut run would obviously surface.

The nightly workflow is now sharded by package (`app-setup`, `blueprints`,
`utils`, `refresh-task`) so future scheduled runs can produce package-scoped
artifacts instead of timing out as one monolithic pass. A follow-up triage pass
can replace the entries here with real mutant IDs drawn from those artifacts.

## Killed in JTN-595 (2026-04-19)

These survivors were turned into kills by the same PR that added this file.
They are recorded here so future runs that flag the same code spots can be
cross-referenced to the assertion that catches them.

| file:line | mutation class | killing test |
|-----------|----------------|--------------|
| `src/utils/display_names.py:42` | remove `.strip()` from `humanize_plugin_id` | `tests/unit/test_display_names.py::TestHumanizePluginId::test_humanize_strips_surrounding_whitespace` |
| `src/blueprints/csp_report.py:47` | drop `"#"` from `_redact_url` separator tuple | `tests/test_csp_report.py::test_source_file_url_fragment_is_redacted` |
| `src/blueprints/csp_report.py:98` | drop any entry from `_sanitise_report` url_keys set | `tests/test_csp_report.py::test_all_url_fields_are_redacted` |
| `src/blueprints/version_info.py:50` | remove `value != "{version}"` guard | `tests/test_version_uptime.py::test_read_app_version_rejects_unexpanded_placeholder` |
| `src/blueprints/version_info.py:50` | remove `value != "0.1.0"` guard | `tests/test_version_uptime.py::test_read_app_version_rejects_bootstrap_placeholder` |
| `src/blueprints/version_info.py:49-51` | return-value mutation of happy path | `tests/test_version_uptime.py::test_read_app_version_accepts_real_version_string` |

## Deferred / acceptable survivors

No actionable survivors were identified by static inspection that we chose
to leave unkilled; the acceptable category below is a standing policy note
rather than a concrete survivor list.

### Acceptable — log-formatting only

Any mutant that changes only the *format* of a log line (punctuation,
template string, joiner characters) without changing the logged content
is acceptable to survive. Example pattern: mutating `"CSP violation: %s"`
to `"CSP violation %s"`. We deliberately do not assert on log-line
punctuation because doing so would couple tests to cosmetic details and
add noise without catching real regressions.

### Deferred — sharded nightly triage pending artifact review

The substantive deferred work is reviewing the first successful sharded
nightly artifacts. At that point, a follow-up issue should:

1. Download the `mutmut-cache-<shard>` artifacts from the nightly run.
2. Iterate `mutmut results` → `mutmut show <id>` for each survivor.
3. Append each survivor here under a **Deferred** heading, or kill it.

Until then, the survivor universe is effectively unknown — do not
interpret the short list above as complete.

## How to add an entry

Format: one markdown table row under the relevant heading.

```md
| file:line | mutation class | reason / killing test |
```

Use short, stable descriptions in the `mutation class` column (e.g.
``replace `>` with `>=` in bound check``) rather than raw diff output —
line numbers shift under refactors but the mutation *class* is durable.
