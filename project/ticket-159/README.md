# Ticket 159: Detect overdue OQLLM fact advisories from the URTLog journal (PLF-25980)

- **ID**: ticket-159
- **Owner**: agent:codex
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-11-24

## Goal and scope

PLF-25980. Monitor the actual fact-review route through the native journal in live operator triage. The request is advisory. Reading the journal must have no model or repair side effects.

## Acceptance criteria

- [x] AC-01: Identify a completed timeout, other measured failures and a missing outcome after the recorded caller deadline using the same episode key.
- [x] AC-02: Report backoff or retry eligibility from the producer's recorded cutoff. A matching advice receipt or observed recovery clears the alarm, including pre-upgrade receipts.
- [x] AC-03: Report unavailable, partial and legacy observations. Limit scan time and result size. Inspect only the owner principal selected by the operator.

Set `MONAG_OQLLM_FACT_PRINCIPAL` to the principal used by the URTLog producer, and `URTLOG_STATE_DIR` to its journal directory in the Monag environment. Run `monag triage` to inspect the advisory in the same queue as other operator alerts. An unset principal leaves monitoring opt-in.

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
