# Ticket 133: Read a Planfile task without status as open, matching Planfile's default

- **ID**: ticket-133
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-10-28

## Goal and scope

`semcod/goal/planfile.yaml` has a legacy task `Q01` without a `status`. monag read it as `unknown`, so `unknown_statuses=1` and autonom fleet admission refused every Willman campaign for semcod/goal with `ambiguous_queue_state`. Planfile itself creates tasks as `open`; monag now uses the same default.

## Acceptance criteria

- [x] AC-01: resume tests pass, including a statusless-task regression; governance gate passes.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
