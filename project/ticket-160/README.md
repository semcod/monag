# Ticket 160: Run recurring read-only URTLog triage for an explicitly configured producer (PLF-29787)

- **ID**: ticket-160
- **Owner**: agent:codex
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-11-24

## Goal and scope

Ship a producer-scoped user timer for the existing Monag URTLog probes. Deployment is tracked by subactor/platform STARTER-047. The user requested implementation and delivery in the current session.

## Acceptance criteria

- Verify the service and timer with systemd.
- Replay a timed-out episode and a recovered episode through the configured command.

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
| Estimated effort | 44 min |
| Planning budget | 30 min |
| Split recommended | yes |

Diagnostics: RADAR-ACCEPTANCE-MISSING, RADAR-BUDGET-EXCEEDED.
<!-- ticket-radar:end -->
