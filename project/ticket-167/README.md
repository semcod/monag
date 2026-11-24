# Ticket 167: PLF-29793 Observe the scheduled continuation snapshot from an independent timer

- **ID**: ticket-167
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-11-24

## Goal and scope

Check the on-disk snapshot from a timer independent of the scan. Emit a Reflex fact carrying the observed cause and a content digest without publishing the project list.

## Acceptance criteria

- [x] Report missing, stale, malformed or misdirected snapshots and verified recovery under the same check identity.

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
