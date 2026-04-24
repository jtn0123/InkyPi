<!--
  PR title must start with a Conventional Commits type — PRs are squash-merged
  and the title becomes the commit subject on main, which semantic-release
  parses for the next version. Use one of:
    feat: / fix: / perf:                         -> triggers a release bump
    refactor: / docs: / style: / test: / build: / ci: / chore: / revert:
                                                 -> no bump (valid but silent)
  BREAKING CHANGE: footer anywhere in the body   -> major bump
  See CONTRIBUTING.md.
-->

## Summary

-

## Base Branch Confirmation

- [ ] This PR is based on `origin/main` (not a stale long-lived branch)
- [ ] I rebased/merged latest `origin/main` before opening

## Parent-Fork Sync Checklist

- [ ] If this PR syncs from `fatihak/InkyPi`, changes were cherry-picked by feature
- [ ] Relevant upstream behavior differences were documented in PR description
- [ ] Plugin/add-to-playlist/update flows were smoke-tested after sync

## Compatibility/Release Checklist

- [ ] `pytest` relevant suites pass locally
- [ ] No breaking API route/path changes
- [ ] Error responses follow JSON contract (`success:false,error,code,details,request_id`)
- [ ] Docs updated for new flags/endpoints/UI
- [ ] **Frontend changes** (`src/static/**`, `src/templates/**`): ran browser tests (`SKIP_BROWSER=0 .venv/bin/python -m pytest tests/`) and all passed

## Testing

-
