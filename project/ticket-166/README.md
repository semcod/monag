# Ticket 166: PLF-29792 Deliver atomic output from the scheduled Monag continuation service

- **ID**: ticket-166
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-11-24

## Goal and scope

Use the reviewed snapshot writer under a systemd oneshot that also has ExecStartPost. Supply a reusable drop-in and verify an actual scheduled cycle on the user-approved existing service.

## Acceptance criteria

- [ ] A scheduled continuation scan leaves fresh JSON after its history command.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.

<!-- ticket-radar:start -->
## Ticket Radar

Initial planned-scope estimate; advisory only, not execution or merge approval.

| Measure | Initial assessment |
| --- | --- |
| Impact score | 48/100 |
| Complexity | M |
| Estimated effort | 47 min |
| Planning budget | 30 min |
| Split recommended | yes |

Diagnostics: RADAR-ACCEPTANCE-MISSING, RADAR-BUDGET-EXCEEDED.
<!-- ticket-radar:end -->
