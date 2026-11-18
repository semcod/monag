# Ticket 149: Bound panel autodiagnosis request latency

- **ID**: ticket-149
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-11-18

## Goal and scope

Workspace PLF-25977. A cold read of the fleet report can exceed the HTTP deadline and concurrent callers duplicate the same host probes. Bound the panel and assistant reads, share a refresh, and retain full-result dispatch semantics. SESSION_EXECUTION_AUTHORIZATION: the operator requested implementation, testing and independent publication on 2026-11-18.

## Acceptance criteria

- [x] Fast reads retain their existing result. A slow scan returns progress and lets the dashboard poll for completion.
- [x] Concurrent reads, force-refresh and dispatch share one in-flight scan. Failed scans can be retried without publishing partial tickets.
- [x] Exercise the HTTP routes with a controlled slow adapter and keep routine route tests independent of live host probes.

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
| Estimated effort | 54 min |
| Planning budget | 30 min |
| Split recommended | yes |

Diagnostics: RADAR-ACCEPTANCE-MISSING, RADAR-BUDGET-EXCEEDED.
<!-- ticket-radar:end -->
