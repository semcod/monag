# Ticket 121: Remediate PERF-AUDIT findings and adopt Wellmanifest standards

- **ID**: ticket-121
- **Owner**: agent:antigravity
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-10-17

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: User authorized autonomous remediation of all `PERF-AUDIT-*` findings and adoption of `wellmanifest/wellman` standards across `semcod` repositories.

Remediate all 31 `PERF-AUDIT-*` findings (`PERF-AUDIT-SQLITE-001`, `PERF-AUDIT-PARSE-001`, `PERF-AUDIT-SUBPROC-001`, `PERF-AUDIT-KWARG-001`) across 12 modules in `src/monag/` and populate `.governance/standard-adoption.json` so `standard_pack_check.py` reports 0 findings in enforce mode.

## Acceptance criteria

- [x] AC-01: Hoist or extract SQLite execution helpers outside loops/comprehensions in `src/monag/cli.py`, `src/monag/doctor.py`, and `src/monag/history.py` (`PERF-AUDIT-SQLITE-001`).
- [x] AC-02: Extract mtime-keyed `@lru_cache` YAML parse helpers outside loops in `src/monag/autodiagnosis.py`, `src/monag/resume.py`, and `src/monag/summary.py` (`PERF-AUDIT-PARSE-001`).
- [x] AC-03: Extract subprocess helpers outside loops in `src/monag/ecosystem.py`, `src/monag/triage.py`, and `src/monag/worktrees.py` (`PERF-AUDIT-SUBPROC-001`).
- [x] AC-04: Wire all optional parameters across `src/monag/ecosystem.py`, `src/monag/panel.py`, `src/monag/prs.py`, `src/monag/report.py`, `src/monag/summary.py`, `src/monag/triage.py`, and `src/monag/worktrees.py` (`PERF-AUDIT-KWARG-001`).
- [x] AC-05: Populate `.governance/standard-adoption.json` and pass `standard_pack_check.py`, `audit_repository` (`0` findings), `pytest -q`, and `./project/governance-check.sh`.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
