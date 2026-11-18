# Ticket 143: Adopt new-project 0.20.156 with provable standard levels

- **ID**: ticket-143
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-11-18

## Goal and scope

Adopt new-project 0.20.156 (from 0.20.32). The scheduled governance run on
`main` always fails: the 0.20.32 workflow passes `--changed-file
project/TICKETS.md` when there is no range, which `GOV-MATERIAL-001` rejects.

The old adoption records claim S3/S4 with one self-asserted manifest digest.
They are replaced by records the 0.20.156 pack checker verifies (same policy
as semcod/diagit#80): S3 for new-project, git-lifecycle, merge,
validation-attestation and ticket-lifecycle; S2 for worktrees and docs; S0 for
logs. Mode is `audit`. The repository is public, so S4 becomes provable once a
ruleset on `main` requires the exact checks.

## Acceptance criteria

- [ ] AC-1: Goal reports the target up-to-date at 0.20.156.
- [ ] AC-2: The pack check has no evidence or drift findings.
- [ ] AC-3: `project/governance-check.sh` passes.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
