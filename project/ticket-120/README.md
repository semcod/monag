# Ticket 120: Fix workspace parent collision and locked worktree pruning

- **ID**: ticket-120
- **Owner**: agent:antigravity
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-10-16

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: the operator requested analyzing the last 12 hours
of development via `semcod/monag` and `subactor/reflex`, proposing improvements,
and executing them.

During the 12-hour workspace analysis on the `maskservice` fleet workspace:
1. `triage.check_agent_collision` treated any agent running in a parent workspace
   directory (`p in repo_path.parents`) as colliding with every child repository in
   the workspace.
2. `worktrees.prune_worktrees_safe` did not unlock Git-locked worktrees that had
   already passed all Wellmanifest v5 safety checks (merged, clean, inactive, no
   active lease), leaving ghost `.git/worktrees/*` entries when removing directories.
3. `doctor.audit_worktrees` flagged dirty newly created worktrees at `main` as stale,
   and `doctor.prune_and_remediate` did not delete standalone merged `ticket/*` branches.
4. `advise.collect_reflex_patterns` walked full `.subactor/sessions/*/checkout` trees
   instead of `.planfile/events` and session log files.

## Acceptance criteria

- [x] AC-01: `check_agent_collision` only matches processes inside `repo_path` (`p == repo_path or repo_path in p.parents`), not parent workspace directories.
- [x] AC-02: `prune_worktrees_safe` unlocks Git-locked worktrees after verifying all Wellmanifest v5 safety invariants before removal/prune.
- [x] AC-03: `doctor.audit_worktrees` excludes dirty worktrees from `stale`, and `doctor.prune_and_remediate` deletes standalone merged ticket branches.
- [x] AC-04: Unit tests and `project/governance-check.sh` pass.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
