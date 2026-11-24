# Ticket 165: Preserve canonical Planfile execution waits in resume (PLF-29791)

- **ID**: ticket-165
- **Owner**: agent:codex
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-11-24

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: Continue workspace PLF-25979. Preserve explicit execution blockers in the Monag resume readout of live Planfile records. The canonical URTLog store and Monag disagree on PLF-29704.

## Acceptance criteria

- Preserve a consistent execution blocker on an open canonical ticket and include it in the blocked count.
- Conflicting identities, mixed states and older records must not invent a wait. Export only the bounded state.

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
