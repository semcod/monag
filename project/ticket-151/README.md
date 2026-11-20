# Ticket 151: Optional uritime-urtlog bridge for Monag agent observation snapshots

- **ID**: ticket-151
- **Owner**: agent:antigravity
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-11-20
- **Authorization**: `SESSION_EXECUTION_AUTHORIZATION` (user autonomous pilot rollout mandate for `uritime/urtlog` across URI/observation repositories, including publication through the repository's protected delivery process)

## Goal and scope

Add a zero-mandatory-dependency, opt-in `uritime-urtlog` bridge (`src/monag/urtlog_bridge.py`) wired into `monag.monitor.snapshot()` when `URTLOG_STATE_DIR` is set. Normalize observed agent records and repository mappings for `urtlog.adapters.adapt_monag_snapshot` and emit them fail-open via `urtlog.sdk.UrtClient` without altering default Monag behavior when `URTLOG_STATE_DIR` is unset or `urtlog` is not installed.

## Acceptance criteria

- [x] AC-01: `src/monag/urtlog_bridge.py` normalizes Monag snapshot agent observations and lazily imports `urtlog` only when `URTLOG_STATE_DIR` is set.
- [x] AC-02: `monag.monitor.snapshot()` invokes the opt-in bridge fail-open without affecting default snapshot output or adding required dependencies.
- [x] AC-03: Unit tests in `tests/test_urtlog_bridge.py` cover opt-out no-op, missing-package graceful degradation, and live `urtlog` recording when `urtlog` is importable, with `pytest` and `governance-check.sh` passing.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.

<!-- ticket-radar:start -->
## Ticket Radar

Initial planned-scope estimate; advisory only, not execution or merge approval.

| Measure | Initial assessment |
| --- | --- |
| Impact score | 36/100 |
| Complexity | M |
| Estimated effort | 37 min |
| Planning budget | 30 min |
| Split recommended | yes |

Diagnostics: RADAR-ACCEPTANCE-MISSING, RADAR-BUDGET-EXCEEDED.
<!-- ticket-radar:end -->
