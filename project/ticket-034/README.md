# Ticket 034: Opt in monag to Koru fleet via .planfile/.koru/policy.yaml and mark PLF-002 done

- **ID**: ticket-034
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-09-17

SESSION_EXECUTION_AUTHORIZATION: The user requested checking subactor/reflex and semcod/monag autonomy status and continuing improvements. Audit confirmed monag is missing .planfile/.koru/policy.yaml (preventing Koru fleet management) and PLF-002 is delivered but remained open in Planfile.

## Goal and scope

1. Add `.planfile/.koru/policy.yaml` to opt `semcod/monag` into the Koru autonomous fleet.
2. Mark `PLF-002` as `done` in `.planfile/sprints/current.yaml` and record closure.
3. Update `project/TICKETS.md` index.

## Acceptance criteria

- [x] AC-01: `.planfile/.koru/policy.yaml` exists with standard LLM agent policy and universal CI test execution.
- [x] AC-02: `PLF-002` in `.planfile/sprints/current.yaml` is marked with `status: done`.
- [x] AC-03: Governance checks and tests pass with 0 errors.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
