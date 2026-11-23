# Ticket 156: Publish Monag resume snapshots and Bottlenecks observations for Reflex

- **ID**: ticket-156
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-11-23

## Goal and scope

Expose atomic resume snapshots and optional Bottlenecks delivery observations for Reflex. The workspace owner requested this integration under PLF-25979.

## Acceptance criteria

- [x] AC-01: Verify that a failed scan preserves the previous file and that Reflex consumes the new projection.

## Operator use

The scheduler can send standard output to the journal and persist the snapshot with
`monag --json resume --snapshot-file /path/to/resume.json`.
The destination directory must exist. Directing systemd standard output to the same
file with `truncate:` reopens it for each additional service command.

With a Bottlenecks installation providing `delivery.planfile`, run
`monag resume --reflex-output /path/to/delivery.jsonl` and supply that file to
`reflex analyze --source` or `monag advise --reflex-source`.
Both exports retain the normal terminal output and replace their destination atomically.

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
