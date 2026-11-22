# Ticket 155: Surface live autonomy blockers in triage with budget and stale ledger in usage

- **ID**: ticket-155
- **Owner**: agent:antigravity
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-11-22

## Goal and scope

Fixes semcod/monag#185:
- Add read-only bounded `probe_live_autonomy_blockers` (`src/monag/autonomy_probes.py`) probing Willman `/v1/health?readiness=1`, Planfile `/tickets/discovery`, Heyasa `/health` & paused plans, Willman `projects.sqlite` `uncertain` jobs, and failed user systemd autonomy units, ranked as P0/FLOOR in `triage`.
- Add `--budget-seconds` to `triage` and `autodiagnose` with bounded partial coverage reporting.
- Surface `STALE_LEDGER` (>7d expired) and `IDLE_LONG_RUNNING_AGENT` (>24h uptime, <60s CPU) warnings in `usage.py`.

## Acceptance criteria

- [x] AC-01: Live P0 autonomy blockers rank above routine worktree inspection when enabled.
- [x] AC-02: `triage` and `autodiagnose` accept `--budget-seconds` and return partial coverage when exceeded.
- [x] AC-03: `monag usage` flags `STALE_LEDGER` and `IDLE_LONG_RUNNING_AGENT`.
- [x] AC-04: Unit tests, `./project/governance-check.sh`, and `wellman check` pass.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.

<!-- ticket-radar:start -->
## Ticket Radar

Initial planned-scope estimate; advisory only, not execution or merge approval.

| Measure | Initial assessment |
| --- | --- |
| Impact score | 56/100 |
| Complexity | M |
| Estimated effort | 60 min |
| Planning budget | 30 min |
| Split recommended | yes |

Diagnostics: RADAR-ACCEPTANCE-MISSING, RADAR-BUDGET-EXCEEDED.
<!-- ticket-radar:end -->
