# Ticket 162: Respect execution boundaries in Git and process observations (PLF-29788)

- **ID**: ticket-162
- **Owner**: agent:codex
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-11-24

## Goal and scope

Correct Monag observations that borrowed the repository and ticket identity of the enclosing checkout when a process worked in an isolated directory. The request to repair observed defects authorizes this change in the current session.

## Acceptance criteria

- Verify an isolated non-repository remains unknown even below an active ticket.
- Verify real Git repositories and ticket worktrees within the execution boundary remain observable.

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
