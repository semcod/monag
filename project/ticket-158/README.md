# Ticket 158: Read native URTLog timestamps in daily telemetry (PLF-29786)

- **ID**: ticket-158
- **Owner**: agent:codex
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-11-24

## Goal and scope

Read the URTLog journal used by development and operations from Monag's rolling daily report. A real isolated journal contained eight events, including three failed events, while both reported counts were zero.

## Acceptance criteria

- [x] AC-01: Count native UTC microseconds within both window boundaries and preserve support for legacy epoch seconds and ISO timestamps.
- [x] AC-02: Read an explicitly selected journal, then URTLOG_STATE_DIR, then the XDG default. Report coverage in JSON and Markdown, including empty, missing, unsupported and unreadable data.

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
