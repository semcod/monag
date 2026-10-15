# Ticket 118: Classify the planfile failed status as blocked pending work

- **ID**: ticket-118
- **Owner**: claude
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-10-15

## Goal and scope

`failed` is a first-class planfile `TicketStatus` (a ticket whose execution
attempts are exhausted). `monag resume` knew neither it in `OPEN` nor in
`CLOSED`, so `summarize_tickets` counted it in `unknown_statuses`. The fleet
admission gate (`fleet_admission.py`) requires `unknown_statuses == 0`, so it
denied willman project intake with `ambiguous_queue_state` for every
repository holding a single failed ticket: 352 local repositories, including
`subactor/reflex` (PLF-012) and `subactor/subllm`. Observed on a willman
canary campaign on 2026-10-15 (job 45547e85, `intake_denied`).

`failed` now belongs to a `STALLED = {'blocked', 'failed'}` subset of `OPEN`:
it stays visible as remaining work that needs triage and is counted in
`blocked`, never as ready work. Nothing else changes.

## Acceptance criteria

- [x] AC-01: `tests/test_resume.py` covers failed + blocked + done
  (unknown 0, remaining A/B, blocked 2); 27 passed.
- [x] AC-02: full suite: 520 passed, 1 skipped; `test_panel::test_report_endpoints`
  timed out once under load and passes alone on both main and this branch.
- [x] AC-03: `project/governance-check.sh` passes.

## Tracking boundary

The willman controller pins a monag release; rolling this fix out is a
separate deployment step.
