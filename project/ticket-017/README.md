# ticket-017 — Fix goal.yaml publish command pattern

- **ID**: ticket-017
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-09-15

## Goal and scope

`goal doctor` flagged `PY013`: `strategies.python.publish` in `goal.yaml`
used `python -m twine upload --non-interactive dist/monag-{version}*`
instead of the pattern `goal` expects, `twine upload --skip-existing
dist/monag-{version}*`. Fixed to the expected pattern.

Publishing itself stays disabled (`publish_enabled: false`,
`publishing.enabled: false`); this only corrects the command for whenever
it is turned on later.

Note: verifying with `goal doctor` also re-expands `goal.yaml` to its full
canonical template — that is `goal`'s own `advanced.auto_update_config:
true` behavior on every doctor/(-a) run, not a deliberate rewrite done
here. Reviewed the expanded file for secrets: none present, only
`token_env` variable names and credential-detection regexes.

## Acceptance criteria

- [x] AC-01: `goal doctor` no longer reports `PY013`; summary shows "No
      issues found".

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant
prose and raw command logs are not required delivery output.
