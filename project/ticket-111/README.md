# Ticket 111: History: report observation gaps and correlate task attempts with receipts

- **ID**: ticket-111
- **Owner**: agent:antigravity
- **Status**: IN_PROGRESS
- **Workflow state**: VALIDATION
- **Created**: 2026-10-11

## Goal and scope

Enhance history reporting and task telemetry correlation to:
1. Surface last sample age, observation gaps, and coverage in `src/monag/history.py` and CLI/presentation views, distinguishing unavailable stores, missing telemetry, genuine lack of activity, and zero completed tasks.
2. Connect run/task records to ticket, attempt, exact SHA, outcome, and real timing evidence (queue/execution durations).
3. Aggregate file metadata churn so dirty/clean file transitions do not drown out actual activity or falsely imply task completion.
4. Add comprehensive test coverage in `tests/test_activity.py` and `tests/test_presentation.py`.

## Acceptance criteria

- [x] AC-01: Implement history store coverage and gap reporting in `src/monag/history.py` (`history_coverage()` / `history.read()` metadata).
- [x] AC-02: Connect task records to ticket, attempt, exact SHA, receipt, and outcome in `src/monag/monitor.py` and `src/monag/cli.py` (`run_task`).
- [x] AC-03: Expose execution/queue durations and attempts only with real timing evidence, preventing inferred success from clean files.
- [x] AC-04: Aggregate metadata churn in history reporting and presentation.
- [x] AC-05: Add comprehensive tests for gaps, wrapper integration, retention, dedupe, and non-inferred success from clean files.
- [x] AC-06: Ensure unit tests pass and `./project/governance-check.sh` passes with zero errors and zero warnings.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
