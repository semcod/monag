# Ticket 157: Check declared central Planfile telemetry health in live triage (PLF-25978)

- **ID**: ticket-157
- **Owner**: agent:codex
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-11-24

## Goal and scope

PLF-25978 under workspace PLF-25979. Identify an explicitly expected, unavailable URTLog bridge even when the central Planfile API is healthy.

## Acceptance criteria

- [x] AC-01: Exercise the configured endpoint in triage and distinguish disabled, unverified, ready and unmonitored installations.

The deployment that expects Planfile telemetry sets `MONAG_PLANFILE_URTLOG_HEALTH_URL` to its Planfile health endpoint. The live triage records the fields reported by that endpoint.

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
