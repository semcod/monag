# Ticket 130: Extract Willmux TaskUpdated error details and filter foreign project tasks in autodiagnosis

- **ID**: ticket-130
- **Owner**: agent:agy
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-10-24

SESSION_EXECUTION_AUTHORIZATION: User authorized 12h autonomy diagnostics and execution of improvement tickets across `subactor/*`, `paxlet-com/willman`, `paxlet-com/willmux`, and `semcod/monag`.

## Goal and scope

In `src/monag/autodiagnosis.py`, `inspect_repository_anomalies()` scans `~/.config/willmux/events.jsonl` for `"status": "failed"`. It assumes every entry is a `ChatPlanRun` with `data.steps`, reporting `reason = "unknown"` for `TaskUpdated` events and misattributing foreign-project tasks (where `data.project` targets another repository such as `dockuri/dockuri`) to `paxlet-com/willmux` (`PLF-18429`).

Skip `events.jsonl` records whose `data.project` names a different repository than `repo_path`, and extract the error reason from `failed_steps[0]`, `data.reason`, `data.error`, `data.result.error`, `data.result.output.error`, or `data.title` before falling back to `"unknown"`.

## Acceptance criteria

- [x] AC-01: `inspect_repository_anomalies()` ignores `events.jsonl` task failures whose `data.project` targets a foreign repository.
- [x] AC-02: `inspect_repository_anomalies()` extracts `TaskUpdated` error details (`data.error` / `data.result.error` / `data.result.output.error` / `data.title`) instead of `"unknown"`.
- [x] AC-03: Unit tests in `tests/test_advanced_autodiagnosis_and_sync.py` and `./project/governance-check.sh` pass.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
