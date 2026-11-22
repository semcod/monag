# Ticket 154: Fix advise blank issue number, doctor timeout, and summary lease split

- **ID**: ticket-154
- **Owner**: agent:antigravity
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-11-22

## Goal and scope

Fixes semcod/monag#184:
- Include `'issue_number'` on `audit-untracked-issue` candidates in `export.py` so `advise.py` renders `#<num>` instead of blank `#`.
- Remove the hardcoded 10s cap on `agent_storage` in `doctor.py` when no phase budget is configured, and distinguish phase budget caps from overall budget in timeout recommendations.
- Split `active_live_leases_count` vs `expired_non_terminal_leases_count` in `summary.py`, flag truncated `gh search prs` counts (`>=50` / `>=100`), and add read-only optional 24h runtime telemetry adapters for Willman/URTLog/Heyasa in `monag day`.

## Acceptance criteria

- [x] AC-01: `export.py` preserves `issue_number` and `advise.py` renders `#<num>`.
- [x] AC-02: `doctor.py` lets `agent_storage` use remaining overall budget by default and accurately reports phase vs overall timeout.
- [x] AC-03: `summary.py` splits live vs expired non-terminal leases, flags truncated GitHub PR queries, and exposes optional `runtime_telemetry_24h` in `day`.
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
