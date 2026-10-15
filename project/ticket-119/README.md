# Ticket 119: Check resume status sets against the planfile ticket status contract

- **ID**: ticket-119
- **Owner**: claude
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-10-15

## Goal and scope

ticket-118 added planfile's `failed` status by hand after it had silently
become an unknown status and blocked fleet admission. semcod/planfile now
publishes `planfile/schemas/ticket-status.v1.json` (semcod/planfile#262,
6670b38). This ticket vendors that contract as a digest-pinned test fixture
and asserts, for every planfile status, that resume's `OPEN`/`CLOSED`
sets contain it by its `pending` flag, `STALLED` matches the `stalled`
class, and it never counts as unknown. A future planfile status fails this
test when the fixture is refreshed instead of failing admission in
production.

## Acceptance criteria

- [x] AC-01: `tests/test_resume.py`: 28 passed, 7 subtests.
- [x] AC-02: `project/governance-check.sh` passes.

## Tracking boundary

No runtime dependency on planfile; refreshing the fixture is a deliberate
change with a new pinned digest.
