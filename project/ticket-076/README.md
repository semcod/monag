# Ticket 076: Scan Wellmanifest standard adoptions in workspace reports

- **ID**: ticket-076
- **Owner**: codex:ticket-076-standards
- **Status**: IN_PROGRESS
- **Workflow state**: VALIDATION
- **Created**: 2026-09-19

## Goal and scope

Implement the report-layer slice of GitHub issue #91: scan local Wellmanifest
adoption and lock manifests, report declared packs and enforcement levels, and
surface workspace-local pin disagreement without claiming network freshness.

SESSION_EXECUTION_AUTHORIZATION: the user explicitly instructed the agent to
continue implementation on 2026-09-19.

Continuation 2026-09-19: the user requested investigation and repair, then
explicitly instructed the agent to handle lease setup autonomously. Reused
the existing Subactor repository-change-leases store and acquired the initial
ticket-076 lease through its controller API (fencing token 36). Repair remains
inside the accepted scanner/report scope: malformed metadata, bounded traversal,
and conflicting adoption/lock pins, with regression coverage.

## Acceptance criteria

- [x] AC-01: Repositories with valid, absent and malformed adoption manifests
      produce truthful structured observations.
- [x] AC-02: `monag report --sections standards` renders an adoption summary
      and reports workspace-local revision disagreement.
- [x] AC-03: Focused report/governance tests and the managed governance gate
      pass.

Validation after repair: `PYTHONPATH=src python3 -m pytest -q` — 345 passed,
4 skipped. `./project/governance-check.sh` — `GOV-PASS` (0 errors, 0 warnings).
Added 19 regression cases covering malformed metadata, bounded traversal,
symlink avoidance, conflicting pins, invalid UTF-8 and escaped report output.
Live read-only scan of the Semcod workspace at depth 1 observed 68
repositories, no observation errors, in 0.027 seconds. These observations do
not establish release freshness or deployment.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
