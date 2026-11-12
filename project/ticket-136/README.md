# Ticket 136: Add frozen acceptance probe for the daily summary (PLF-25993)

- **ID**: ticket-136
- **Owner**: agent:claude
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-11-12

## Goal and scope

Add a standard-library probe for `monag.summary.gather_planfile_daily` that an external
evaluator can run isolated (`python -I -S -B tests/acceptance/summary_probe.py`): it reads one
JSON request, writes the described `*.fast.json` sprint files to a temporary directory and
prints the function's counts or finish times as JSON. No change to `src/`.

The probe is the fixed entry point for the PLF-25993 repair pilot (canceled and blocked history
entries counted as completed; truncated `finished_at`). This ticket does not fix that defect and
asserts only behaviour that holds today.

Session authorization: the user asked to continue, merge and test this work (2026-11-12).

## Acceptance criteria

- [x] AC-01: The probe runs under `-I -S -B` and returns counts and finish times for today's history and current sprint files.
- [x] AC-02: It refuses another day's history file, a path outside the sprint directory and an unknown view, with no output.
- [x] AC-03: Tests cover only currently true behaviour; the suite and the governance check pass.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
