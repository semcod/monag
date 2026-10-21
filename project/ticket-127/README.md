# Ticket 127: Fail closed on unknown worktree state and preserve controller leases

- **ID**: ticket-127
- **Owner**: codex-policy-autonomy-20261021
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Created**: 2026-10-21

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: user requests diagnosed repository repairs and autonomous decisions governed by separate Wellmanifest policy, with protected publication. Parent intake PLF-3193. This disjoint Monag defect does not supersede Willmux ticket-337.

Repair worktree lifecycle classification and execution guards in the four allowed source/test files. Treat observation as evidence, never cleanup authority. Preserve unknown work and existing controller ownership; no destructive fleet cleanup is requested. Do not edit the independently deployed admission policy or issue grants from this ticket.

## Acceptance criteria

- [x] AC-01: Native change-lease/v1 identity and phase are recognized; an unreleased, expired, malformed or unreadable lease blocks cleanup until independent resolution.
- [x] AC-02: Git observation failure blocks cleanup, and a branch cannot establish integration merely by comparing against its own HEAD.
- [x] AC-03: Locked, missing, external or unknown worktree registrations remain protected; failed Git removal never falls back to recursive filesystem deletion.
- [x] AC-04: Cleanup is separated from observational eligibility, requires exact existing authorization, and rechecks dirty state, reachability and ownership before effects; no controller lease is rewritten by Monag.
- [x] AC-05: Meaningful regression tests, stack checks, native governance and protected exact-head review pass before authorized merge.

## Evidence and verification

- `get_repo_leases` parses both native `wellmanifest.change-lease/v1` and legacy leases, indexing by ticketId, worktreeId, and branchRef.
- `is_lease_active` enforces fail-closed semantics: only explicitly released/merged/closed/cancelled phases allow cleanup; malformed and unreadable leases block cleanup.
- `is_branch_merged` verifies target reachability against main/master without comparing against own HEAD.
- `audit_worktree_safety` and `prune_worktrees_safe` strictly protect locked worktrees and never fall back to recursive filesystem deletion (`shutil.rmtree`).
- Lease rewrite logic removed from Monag; controller leases remain immutable.
- `audit_worktrees` in `doctor.py` integrates lease and lock guards.
- All 20 regression and unit tests pass (`20 passed in 22.89s`):
  `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/test_worktrees_safe_prune.py tests/test_doctor.py`.
- Native governance passes (`./project/governance-check.sh`): `GOV-PASS: passed (0 errors, 0 warnings)`.
