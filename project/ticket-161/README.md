# Ticket 161: Preserve observed ExecCondition when deriving Monag remediation (PLF-29785)

- **ID**: ticket-161
- **Owner**: agent:codex
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-11-24

## Goal and scope

The active model recommended restarting a unit whose ExecCondition deliberately declined to start it. Preserve the source observation and its owner through the synthesis entry point. Session authority comes from the request to repair the reported anomalies.

## Acceptance criteria

- Verify the same diagnostic for a model proposing a restart and for an unavailable model.
- Preserve normal processing for a failed unit and suppress tickets for a healthy unit.

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
