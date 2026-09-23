# Ticket 081: Implement doctor fix with diagit worktrees and redup housekeeping

- **ID**: ticket-081
- **Owner**: agent:antigravity
- **Status**: DONE
- **Workflow state**: DONE
- **Created**: 2026-09-22

## Goal and scope

Enhance `monag doctor` with a `--fix` housekeeping mode to audit git repositories, prune orphaned/merged linked worktrees, clean up merged ticket branches, and provide recommendations for `redup`, `diagit`, and `prefact`.

## Acceptance criteria

- [x] AC-01: Add `--fix` option to `monag doctor` CLI command.
- [x] AC-02: Implement git fleet worktree auditing, stale worktree detection, and automated remediation.
- [x] AC-03: Pass all unit tests in `tests/test_doctor.py` and governance checks.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
