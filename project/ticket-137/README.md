# Ticket 137: Wave 2 autonomy stall probes, doctor budget, day/summary separation, and triage deduplication

- **ID**: ticket-137
- **Owner**: agent:antigravity
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-11-14

## Goal and scope

Implement Wave 2 diagnostic and operational reliability improvements across `monag` (`MON-01`..`MON-04`, issues `#162`, `#163`, `#164`, `#165`):

1. **`MON-01` (`#162`)**: Add deterministic, read-only autonomy stall probes to `monag autodiagnose` (`systemd --user` status of known autonomy units, loopback Heyasa `/v1/daemon/status` eligibility/slot/velocity probe, and host load saturation vs CPU count), ranking operational stall anomalies strictly above repository hygiene findings.
2. **`MON-02` (`#163`)**: Hoist `worktrees.get_repo_leases(repo)` and default branch resolution outside the per-worktree loop in `monag doctor` (`O(1)` per repository instead of `O(N)` per worktree), and add a monotonic `--timeout` / `budget_seconds` deadline with structured partial output (`timed_out`, `completed_phases`, `timed_out_phases`, `skipped_phases`, `skipped_repositories`).
3. **`MON-03` (`#164`)**: Separate `monag day` (24h operational delta: completed/blocked Planfile tasks in window, completed/failed local agent task runs, and 24h merged/opened PRs) from `monag summary` (current portfolio/queue snapshot, active `.subactor/leases`, and open PR queue), attaching explicit `source` + `scope`/`filter` labels to every count in JSON and Markdown while preserving `gather_planfile_daily` compatibility for the frozen acceptance probe.
4. **`MON-04` (`#165`)**: Group and deduplicate repeated `monag triage` findings by `(repository, cause)` with `affected_count`, `sample_items`, and `estimated_unblock_impact`, sorting deterministically by unblock impact and severity descending.

Session authorization: `SESSION_EXECUTION_AUTHORIZATION` granted by caller to implement, test, commit, push, open PR, and invoke the independent Validator for Wave 2 (`MON-01..MON-04`, 2026-11-14).

## Acceptance criteria

- [x] AC-01: `autodiagnose` detects failed autonomy systemd units, Heyasa dispatch/velocity stalls, and host load saturation with graceful degradation and ranks them strictly above repo hygiene defects (`#162`).
- [x] AC-02: `doctor` reads repository leases once per repo instead of once per worktree and returns structured partial diagnostics within monotonic `--timeout` / `budget_seconds` (`#163`).
- [x] AC-03: `monag day` and `monag summary` render distinct 24h delta vs current portfolio snapshot reports with explicit `source` and `scope`/`filter` metadata on every count in JSON and Markdown (`#164`).
- [x] AC-04: `monag triage` collapses repeated `(repository, cause)` items into grouped steps with `affected_count` and `sample_items`, sorted by unblock impact descending (`#165`).
- [x] AC-05: Unit tests (`unittest` and `pytest`), `./project/governance-check.sh`, and `wellman check` pass cleanly.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
