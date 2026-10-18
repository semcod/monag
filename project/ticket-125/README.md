# Ticket 125: Optimize triage git subprocesses and bound advise audit scan

- **ID**: ticket-125
- **Owner**: agent:agy
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-10-18

SESSION_EXECUTION_AUTHORIZATION: User authorized performance optimization of `semcod/monag` triage and advise execution.

## Goal and scope

1. In `src/monag/triage.py`:
   - Cache resolved working directories per fleet process in `check_agent_collision()` and skip invoking `algocode.engine.check_conflict` for repositories without `project/`, `.governance/`, or `governance/`.
   - Skip spawning `git rev-list --count @{u}..HEAD` when `.git` has neither `refs/remotes` nor `packed-refs`, skip spawning `git worktree list --porcelain` when primary `.git/worktrees` does not exist, and inspect multi-repo workspaces concurrently using `ThreadPoolExecutor(max_workers=16)`.
2. In `src/monag/export.py` and `src/monag/advise.py`:
   - Expose `total_worktrees` and `repos_with_worktrees` in `export.scan()['sources']['audit']` and reuse them in `advise.advise()` so `collect_workspace_metrics()` does not re-scan all workspace repositories a second time.

## Acceptance criteria

- [x] AC-01: `triage.run_holistic_triage()` skips redundant `git rev-list` and `git worktree list` subprocess calls on repositories without remote refs or `.git/worktrees` and parallelizes multi-repo inspection.
- [x] AC-02: `export.scan()` exposes `total_worktrees` and `repos_with_worktrees` in `sources['audit']`, and `advise.advise()` reuses them without calling `collect_workspace_metrics()`.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
