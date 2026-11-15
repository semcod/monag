# Ticket 138: MON-01 follow-up: report ExecCondition skips as AUTONOMY_UNIT_SKIPPED instead of a CRITICAL failure

- **ID**: ticket-138
- **Owner**: agent:claude
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-11-15

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: the user asked to analyse the Heyasa autonomy
stall with semcod/monag, semcod/diagit and subactor/reflex and to plan fixes,
then repeatedly said "kontynuuj". This is a follow-up correction to MON-01
(#162, PR #166) found while verifying it on the live host
(heyasa/heyasa docs/analysis/heyasa-autonomy-fix-deployment-gap-2026-11-15.md).

`_probe_systemd_user_units` reported `subactor-repair-agent.service` with
`ActiveState=inactive, Result=exec-condition` as a CRITICAL
`AUTONOMY_UNIT_FAILED`. An ExecCondition exit of 1-254 is a deliberate skip,
not a crash. It is now reported as `AUTONOMY_UNIT_SKIPPED` (MEDIUM, weight
700, below failures) with its own remediation text. A condition crash that
leaves the unit failed stays CRITICAL.

## Acceptance criteria

- [x] AC-01: `inactive` + `Result=exec-condition` yields one MEDIUM
  `AUTONOMY_UNIT_SKIPPED`; failed units and other non-success results stay
  `AUTONOMY_UNIT_FAILED` CRITICAL; healthy units report nothing.
- [x] AC-02: New tests (5) and `tests/test_wave2_mon01_mon04.py` pass (15 in
  total, unittest); Ruff keeps 141 existing findings in autodiagnosis.py and
  the new test file has none; governance check passes.
- [ ] AC-03: Protected CI and independent Validator approval lead to merge.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
