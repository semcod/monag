# Ticket 082: feat(doctor,monitor): auto-prune merged branches and handle broken gitdir pointers

- **ID**: ticket-082
- **Owner**: antigravity
- **Status**: IN_PROGRESS
- **Workflow state**: VALIDATION
- **Created**: 2026-09-23

## Goal and scope

1. Enhance `monag.monitor.discover()` to validate that `.git` targets exist before running `git worktree list`, preventing exit 128 observation errors on broken or orphaned worktrees.
2. Enhance `monag.doctor.prune_and_remediate()` to re-audit merged branches immediately after worktrees are pruned, ensuring branches freed from checkouts are deleted in the same single invocation.

## Acceptance criteria

- [x] AC-01: `discover()` gracefully ignores broken `.git` files whose `gitdir` target is missing.
- [x] AC-02: `prune_and_remediate()` deletes merged branches in a single pass after pruning secondary worktrees.
- [x] AC-03: All unit tests in `tests/test_doctor.py` pass.
