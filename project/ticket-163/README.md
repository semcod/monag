# Ticket 163: Serialize Monag journal bootstrap and concurrent fact writers (PLF-29789)

- **ID**: ticket-163
- **Owner**: agent:codex
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-11-24

## Goal and scope

Two concurrent observations of the same fact failed during schema initialization. Preserve event and snapshot atomicity, existing data, and private file permissions under competing Monag writers. The user requested repair of logging and duplicate-fact handling.

## Acceptance criteria

- Concurrent writers against an empty journal record exactly one event.
- Existing private journals remain readable while a writer holds a transaction.

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
