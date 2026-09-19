# Ticket 070: Fix MONAG report correctness

- **ID**: ticket-070
- **Owner**: codex:monag-report-fixes-20260919
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-09-19
- **Authorization**: SESSION_EXECUTION_AUTHORIZATION — user requested execution of the verified fixes and tasks.

## Goal and scope

Implement source fixes for Planfile PLF-004 through PLF-011 (GitHub Issues #70–77). Preserve the separate advise ticket-069 and docs ticket-068. Local queue reconciliation is tracked by PLF-006 and does not change application ownership.

## Acceptance criteria

- [x] AC-01: Offline ancestry differences never claim an unmerged PR.
- [x] AC-02: Canonical Planfile records supersede stale snapshots; incompatible external identities remain explicit.
- [x] AC-03: Lease phases, heartbeat evidence and prefixed ticket IDs are observable without granting ownership.
- [x] AC-04: Unborn repositories and descendant agent directories are handled consistently.
- [x] AC-05: Commit age is separate from unknown remote observation freshness.
- [x] AC-06: Focused regression tests, complete application tests and governance checks pass.

## Delivery

A single bounded application change resolves the eight related report defects. Publication uses the repository's protected delivery process.

## Validation evidence

2026-09-19: `PYTHONPATH=src python -m pytest -q`: 318 passed. `./project/governance-check.sh`: GOV-PASS, zero errors/warnings. Queue reconciliation preserves Issue #5 under PLF-001 and allocates a distinct identity for Issue #7. Test log and operational receipts: host audit `monag-report-audit-20260919`.
