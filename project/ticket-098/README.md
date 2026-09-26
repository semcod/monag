# Ticket 098: Add standard Apache-2.0 LICENSE file

- **ID**: ticket-098
- **Owner**: antigravity
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-09-26

## Goal and scope

1. Add the standard Apache License Version 2.0 (`LICENSE`) file to the root of the repository matching `license = "Apache-2.0"` in `pyproject.toml`.
2. Resolve autodiagnosis MEDIUM item: `Add missing LICENSE file to repository root`.
3. Verify that `monag autodiagnose` runs with 0 anomalies.

## Acceptance criteria

- [x] AC-01: Standard Apache-2.0 `LICENSE` file is present in repository root.
- [x] AC-02: Governance checks pass (`GOV-PASS`) under workstream `integration`.
- [x] AC-03: `monag autodiagnose` confirms 0 anomalies.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
