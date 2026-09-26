# Ticket 094: align planfile dispatch format with koru sprint tickets mapping

- **ID**: ticket-094
- **Owner**: antigravity
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-09-26

## Goal and scope

Align Planfile ticket dispatching in `monag.autodiagnosis` with Koru's native sprint storage format.
Koru's `planfile_compat` and `multi_agent` modules expect tickets to be mapped under `sprint.tickets` (or top-level `tickets`) as `{ticket_id: {...}}` with `status: ready` and execution metadata (`state: ready`, `queue: default`). Ensure `dispatch_tickets_to_planfile` populates both `sprint.tickets` mapping and `tasks` list so Koru can immediately intake dispatched tickets.

## Acceptance criteria

- [x] AC-01: `dispatch_tickets_to_planfile` writes tickets into both `sprint.tickets` dictionary mapping and `tasks` array.
- [x] AC-02: Dispatched ticket entries in `sprint.tickets` contain `execution` (`state: ready`, `queue: default`), `status: ready`, and full inputs/labels compatible with Koru autonomous intake.
- [x] AC-03: Tests verify that dispatched sprint YAML contains valid `sprint.tickets` mapping loadable by Koru's `planfile_compat` logic.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.

