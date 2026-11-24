# Ticket 164: Discover the deployed URTLog journal in the Monag daily report (PLF-29790)

- **ID**: ticket-164
- **Owner**: agent:codex
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-11-24

## Goal and scope

The user requested continued fixes for URTLog coverage. The default daily report missed the deployed XDG journal used by both user services. PLF-29790 records the read-only comparison.

## Acceptance criteria

- Report the service journal when no explicit database or state directory is supplied.
- Preserve explicit paths and discovery of the earlier nested XDG layout. Count exactly one journal when both exist.

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
