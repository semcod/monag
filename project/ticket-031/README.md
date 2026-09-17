# Ticket 031: Track the fleet refactoring metrics work in the Planfile store

- **ID**: ticket-031
- **Owner**: claude
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-09-17

SESSION_EXECUTION_AUTHORIZATION: the user asked for a Planfile ticket in
`semcod/monag` so the fleet metrics task is tracked and delegable to Koru, then
answered "wykonaj" to the resulting three follow-ups.

## Goal and scope

`ticket-030` delivered the fleet refactoring metrics (merged as
`semcod/monag#32`, merge `ae5dac3d`). That ticket could not also carry the
Planfile record: `.planfile/**` belongs to the **integration** workstream while
`ticket-030` is `application`, and the hosted `governance / enforce` gate
rejected the mixed scope with `GOV-WORKSTREAM-003`. This ticket adds the record
in the correct workstream.

`PLF-002` is created **without** an integration mapping, on purpose. Both sync
directions are currently unsafe:

- import was reverted in `semcod/monag#29` because it mirrored pull requests as
  issues, failed every run and reopened a closed issue;
- export is defective as reported in `semcod/planfile#126`: it reported
  `Created: PLF-003 -> 19` while creating no issue and recording a mapping onto
  pull request `#19`.

Reconciliation acts on every ticket holding a `sync.github` mapping, so an
absent mapping is what keeps the hourly job healthy.

## Acceptance criteria

- [x] AC-01: The user's explicit request approves the bounded scope.
- [ ] AC-02: `PLF-002` is present in the current sprint with the delivered
      scope, the delivering ticket and the remaining delegation blocker.
- [ ] AC-03: The ticket carries no `sync.github` mapping, so an export dry run
      lists it as unmapped work rather than reconciling a pull request.
- [ ] AC-04: Governance validation passes, locally and in CI.

## Remaining delegation blocker

`koru fleet up` discovers "every project that has opted into koru's LLM-agent
policy (`.planfile/.koru/policy.yaml`, written by `koru --init`)", per its own
command help. `semcod/monag` has `.planfile/.koru/` — a queue runner left a
`queue-runner.lock` there on 2026-09-16 — but **no `policy.yaml`**, so the fleet
supervisor skips it. 66 of the 88 fleet directories carry that file.

Two corrections to an earlier reading of this, recorded so the wrong version is
not repeated: the path is `.planfile/.koru/policy.yaml`, not `.koru/policy.yaml`
at the repository root; and it needs no manifest change, because `.planfile/**`
is already owned by the integration workstream. Adding the file is therefore a
small dependent slice, not a governance extension.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
