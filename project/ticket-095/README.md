# Ticket 095: implement safe worktree pruner conforming to wellmanifest worktrees v5

- **ID**: ticket-095
- **Owner**: antigravity
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-09-26

## Goal and scope

Implement safe worktree pruning across fleet repositories in accordance with the Wellmanifest Worktrees v5 standard (`AGENTS.md` worktree policy).
Ensure that worktrees are NEVER deleted or pruned if:
1. An active agent process or IDE is running inside the worktree path (process/IDE guard).
2. The working directory has uncommitted or untracked changes (`git status --porcelain` is non-empty).
3. The worktree is protected by an active lease in `.subactor/leases/`.
4. The worktree branch has unmerged work.
5. The checkout is an external or legacy primary checkout outside `.worktrees/`.

Expose safe worktree pruning via CLI (`monag worktrees list`, `monag worktrees prune [--safe] [--dry-run]`, `monag doctor --safe-fix`), integrate with `panel.py` (`/api/worktrees/prune-safe`), and write comprehensive unit tests.

## Acceptance criteria

- [x] AC-01: Implement `src/monag/worktrees.py` with `audit_worktree_safety` and `prune_worktrees_safe` enforcing process guard, dirty tree guard, lease status, and merge status.
- [x] AC-02: Expose `monag worktrees list` and `monag worktrees prune` in `src/monag/cli.py` with `--safe`, `--dry-run`, and `--json` support.
- [x] AC-03: Enhance `doctor.py` to use safe pruning so `doctor --fix` never deletes active or dirty worktrees.
- [x] AC-04: Expose safe worktree pruning in `panel.py` with `/api/worktrees/prune-safe`.
- [x] AC-05: Unit tests in `tests/test_worktrees_safe_prune.py` verify all safety invariants (active process, dirty state, active lease, unmerged branch, dead worktree removal).

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.

