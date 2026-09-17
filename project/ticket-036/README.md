# Ticket 036: raise default row limit to 30

- **ID**: ticket-036
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-09-17

SESSION_EXECUTION_AUTHORIZATION: the user asked that `monag usage` show the
whole agent list and that the row limit default be 30, after low-CPU agents
(e.g. the IDE's own `devin acp` processes) were hidden behind the default
12-row cut-off.

## Goal and scope

Raise the global `--limit` default from 12 to 30 rows per section. The flag
remains the explicit override; `--json` already emits all observed rows.

## Acceptance criteria

- [ ] AC-01: `monag usage` renders up to 30 agent rows without `--limit`.
- [ ] AC-02: focused and full test suites plus the governance gate pass.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
