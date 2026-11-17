# Ticket 139: Bound zombie diagnostics and identify reaping parents

- **ID**: ticket-139
- **Owner**: agent:codex-autonomy-20261117
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Created**: 2026-11-17

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: user requested analysis of the last 12 hours and autonomous performance/zombie remediation. Parent workspace Planfile PLF-25975. Evidence: receipt:autonomy-host-20261117/.

## Acceptance criteria

- [x] AC-01: Report zombie counts grouped by parent PID and start time without killing processes.
- [x] AC-02: State process visibility and unavailable history explicitly.
- [ ] AC-03: Regression tests and protected publication.

## Next action

WUP PLF-17370 is merged and deployed. Continue this previously allocated independent scope under the fresh local lease; user renewed test and protected publication authorization. Read only bounded stat records, report current procfs visibility and unknown history, and never signal processes. Preserve missing-parent and PID-reuse uncertainty.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.

## Validation

Eleven procfs regression tests and ten existing autonomy tests passed. Live probe observed 2489 records in 0.17 seconds, with unreadable/vanished records explicitly marked partial. No processes are signalled and no command lines or environments are read. Protected publication remains pending.
