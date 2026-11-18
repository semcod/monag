# Ticket 148: Count distinct confirmed daily Planfile completions

- **ID**: ticket-148
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-11-18

## Goal and scope

Repair the daily Planfile report requested in Heyasa PLF-25993. The operator authorized implementation, testing and independent publication on 2026-11-18.

## Acceptance criteria

- [x] Count each terminal ticket once per repository and day in fast, canonical YAML and legacy YAML sprints. Current status resolves duplicate IDs.
- [x] Preserve the recorded finish and offset, attribute fallback times, and expose undated terminal records. Compare calendar dates in UTC.
- [x] Exercise both report modes and the published ticket-136 probe.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.

<!-- ticket-radar:start -->
## Ticket Radar

Initial planned-scope estimate; advisory only, not execution or merge approval.

| Measure | Initial assessment |
| --- | --- |
| Impact score | 52/100 |
| Complexity | M |
| Estimated effort | 51 min |
| Planning budget | 30 min |
| Split recommended | yes |

Diagnostics: RADAR-ACCEPTANCE-MISSING, RADAR-BUDGET-EXCEEDED.
<!-- ticket-radar:end -->
