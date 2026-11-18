# Ticket 144: Pin published procache credential guard for tests

- **ID**: ticket-144
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-11-18

## Goal and scope

Fixes semcod/monag#172. `test_unprovable_credential_scope_is_never_shared`
(ticket-142) needs the procache credential guard published in dockuri/procache
PR 16 (`72538629`). Environments that still carry an older procache revision
fail it, because the manifest declares no procache dependency.

Add a `test` dependency group that pins the published guard. Runtime
dependencies and the optional runtime fallback stay unchanged. The patch is
the one qualified in the issue (SHA-256 `de4778d6…`).

## Acceptance criteria

- [ ] AC-1: A fresh isolated environment with `--group test` passes
  `tests/test_procache_integration.py`, including the credential-scope test.
- [ ] AC-2: Wheel runtime metadata does not gain procache.
- [ ] AC-3: `project/governance-check.sh` passes.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.

<!-- ticket-radar:start -->
## Ticket Radar

Initial planned-scope estimate; advisory only, not execution or merge approval.

| Measure | Initial assessment |
| --- | --- |
| Impact score | 36/100 |
| Complexity | M |
| Estimated effort | 37 min |
| Planning budget | 30 min |
| Split recommended | yes |

Diagnostics: RADAR-ACCEPTANCE-MISSING, RADAR-BUDGET-EXCEEDED.
<!-- ticket-radar:end -->
