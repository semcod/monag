# Ticket 109: audit LLM agent session storage health and uncrash ecosystem tools in monag doctor

- **ID**: ticket-109
- **Owner**: agent:gemini
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-10-10

## Goal and scope

Integrate `uncrash` ecosystem tool discovery and agent session storage integrity audits into `monag doctor`. Proactively detect corrupted SQLite conversation databases and agent panics during workspace doctor scans, recommending salvage and crash-isolation actions conforming to `wellmanifest/session-recovery`.

## Acceptance criteria

- [x] AC-01: Register `uncrash` in `monag.ecosystem.KNOWN_TOOLS`.
- [x] AC-02: Implement `audit_agent_storage_health` in `monag.doctor`.
- [x] AC-03: Include agent storage diagnostics and remediation recommendations in `monag.doctor.diagnose()`.
- [x] AC-04: Add unit tests in `tests/test_doctor.py`.
- [x] AC-05: Unit tests pass and governance check passes.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
