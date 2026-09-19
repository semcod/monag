# Ticket 076: Scan Wellmanifest standard adoptions in workspace reports

- **ID**: ticket-076
- **Owner**: codex:ticket-076-standards
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-09-19

## Goal and scope

Implement the report-layer slice of GitHub issue #91: scan local Wellmanifest
adoption and lock manifests, report declared packs and enforcement levels, and
surface workspace-local pin disagreement without claiming network freshness.

SESSION_EXECUTION_AUTHORIZATION: the user explicitly instructed the agent to
continue implementation on 2026-09-19.

## Acceptance criteria

- [x] AC-01: Repositories with valid, absent and malformed adoption manifests
      produce truthful structured observations.
- [x] AC-02: `monag report --sections standards` renders an adoption summary
      and reports workspace-local revision disagreement.
- [x] AC-03: Focused report/governance tests and the managed governance gate
      pass.

Validation: `PYTHONPATH=src python -m pytest -q tests/test_report.py` — 33 passed;
governance plugin reported `GOV-PASS`.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
