# Ticket 128: Complete fail-closed worktree observations, expose missing history coverage, and bound slow fleet snapshot collection

- **ID**: ticket-128
- **Owner**: agent:antigravity
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Created**: 2026-10-21

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: user requests continuing diagnosed repairs (`semcod/monag#150` and `semcod/monag#153`), policy-owned autonomous decisions and protected publication.

Resolve the remaining post-PR149 worktree safety defects (`#150`: failed `git status` and missing worktree directory with an active `wellmanifest.change-lease/v1`) and expose explicit unavailable history coverage plus deadline-bounded fleet snapshot completeness (`#153`).

## Acceptance criteria

- [x] AC-01: Preserve Git exit status. Failed, timed-out or incomplete status/reachability/registration observations block cleanup with an explicit unknown-state reason (`git_status_failed`).
- [x] AC-02: Check native ownership, lock, exact registration and lease state before treating a missing worktree directory (`exists=False`) as a dead reference; unreleased or malformed ownership remains protected.
- [x] AC-03: Do not invoke premature `git worktree prune` or `git worktree unlock` before per-worktree safety checks complete.
- [x] AC-04: Empty history or zero-event windows explicitly report `coverage_status="unavailable"`, `coverage_available=False`, `observation_gap=True`, and `fleet_health_established=False`; deadline-bounded or cached-partial fleet snapshots report explicit completeness metadata and timestamps.
- [x] AC-05: Regressions cover failed `git status`, missing worktree with active `change-lease/v1`, empty-history unavailable coverage, and deadline-bounded snapshot collection.
